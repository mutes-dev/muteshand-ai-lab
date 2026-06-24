"""
WEBSOCKET MANAGER — Sprint 9C-1B Backend Foundation

Per OBSERVABILITY_AND_DASHBOARD_ARCHITECTURE_CONTRACT_V1 §4:
- WebSocket is transport-only.
- NOT authority owner, lifecycle owner, or orchestration coordinator.
- Full-payload event delivery only. NO projection snapshots over WebSocket.
- NO lifecycle mutation. NO persistence mutation. NO memory cleanup.

Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
- Runtime registry remains lifecycle authority.
- WebSocket does not directly mutate lifecycle state.

Per GUI_FUNCTIONALITY_CONTRACT_V1:
- Frontend sends intent only.
- Command ack means request accepted; lifecycle truth arrives via events.

Per PROJECTION_CONTINUITY_CONTRACT_V1:
- Reconnect replay uses bus_sequence_id as authoritative cursor.
- Journal replay for missed events before live queue streaming.
"""

import asyncio
import json
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from fastapi import WebSocket, WebSocketDisconnect

# Reuse existing EventBus infrastructure
from system.interface.event_bus import (
    get_event_bus,
    get_events,
    get_latest_sequence,
)

# Sprint 9C-4B: Import lifecycle authority functions used by HTTP endpoints
from system.orchestrator.workflow_control import (
    pause_workflow,
    cancel_workflow,
)

# =============================================================================
# Constants
# =============================================================================

HEARTBEAT_INTERVAL_SECONDS = 15.0
HEARTBEAT_TIMEOUT_SECONDS = 30.0
REPLAY_LIMIT = 100
MAX_QUEUE_SIZE = 1000

# Allowed commands
# Sprint 9C-4B: pause, resume, cancel are now thin wrappers around HTTP authority
ALLOWED_COMMANDS: Set[str] = {
    "ping",
    "client_hello",
    "client_ready",
    "subscribe_workflow",
    "unsubscribe_workflow",
    "request_resync",
    "request_snapshot_refresh",
    "pause",
    "resume",
    "cancel",
}

# Prohibited lifecycle / mutation commands (for explicit rejection logging)
PROHIBITED_COMMANDS: Set[str] = {
    "stop",
    "retry",
    "force_retry",
    "approve",
    "deny",
    "reject_approval",
    "accept_user_control",
    "reject_user_control",
    "request_mutation",
    "replan",
    "archive",
    "dismiss",
}


# =============================================================================
# Message Envelope Builders
# =============================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_event_message(
    workflow_id: str,
    event_type: str,
    bus_sequence_id: int,
    execution_generation: Optional[int],
    payload: Dict[str, Any],
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a server → client event message with full payload."""
    return {
        "type": "event",
        "schema_version": 1,
        "message_id": message_id or f"evt_{bus_sequence_id}_{uuid.uuid4().hex[:8]}",
        "workflow_id": workflow_id,
        "timestamp": _now_iso(),
        "correlation_id": None,
        "event_type": event_type,
        "bus_sequence_id": bus_sequence_id,
        "execution_generation": execution_generation,
        "payload": payload,
    }


def build_ack_message(
    workflow_id: str,
    command: str,
    correlation_id: str,
    status: str,
    payload: Optional[Dict[str, Any]] = None,
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a server → client ack message."""
    return {
        "type": "ack",
        "schema_version": 1,
        "message_id": message_id or f"ack_{uuid.uuid4().hex[:12]}",
        "workflow_id": workflow_id,
        "timestamp": _now_iso(),
        "correlation_id": correlation_id,
        "command": command,
        "status": status,
        "payload": payload or {},
    }


def build_error_message(
    workflow_id: str,
    correlation_id: Optional[str],
    status: str,
    reason: str,
    detail: Optional[str] = None,
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a server → client error message."""
    return {
        "type": "error",
        "schema_version": 1,
        "message_id": message_id or f"err_{uuid.uuid4().hex[:12]}",
        "workflow_id": workflow_id,
        "timestamp": _now_iso(),
        "correlation_id": correlation_id,
        "status": status,
        "reason": reason,
        "detail": detail,
    }


def build_heartbeat_message(message_id: Optional[str] = None) -> Dict[str, Any]:
    """Build a bidirectional heartbeat message."""
    return {
        "type": "heartbeat",
        "schema_version": 1,
        "message_id": message_id or f"hb_{uuid.uuid4().hex[:8]}",
        "timestamp": _now_iso(),
    }


# =============================================================================
# Command Parser
# =============================================================================

def parse_command(raw: Any) -> Optional[Dict[str, Any]]:
    """
    Parse and validate an incoming WebSocket command message.

    Returns:
        Normalized command dict with fields:
        - command: str
        - payload: dict
        - message_id: str
        - workflow_id: str
        - timestamp: str (original)
        Or None if validation fails.
    """
    if not isinstance(raw, dict):
        return None

    msg_type = raw.get("type")
    if msg_type != "command":
        return None

    command = raw.get("command")
    if not isinstance(command, str) or not command:
        return None

    payload = raw.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    return {
        "command": command,
        "payload": payload,
        "message_id": raw.get("message_id") or f"cmd_{uuid.uuid4().hex[:8]}",
        "workflow_id": raw.get("workflow_id") or "",
        "timestamp": raw.get("timestamp") or _now_iso(),
    }


# =============================================================================
# Connection Manager
# =============================================================================

class _ConnectionState:
    """Per-WebSocket connection state. Immutable after creation."""
    __slots__ = ("websocket", "queue", "task", "send_lock", "disconnected")

    def __init__(self, websocket: WebSocket, queue: asyncio.Queue, task: asyncio.Task):
        self.websocket = websocket
        self.queue = queue
        self.task = task
        self.send_lock = asyncio.Lock()
        self.disconnected = False


class WorkflowWebSocketManager:
    """
    Per-workflow WebSocket connection manager.

    Responsibilities:
    - Track active WebSocket connections per workflow_id
    - Bridge EventBus async subscriptions to WebSocket send loops
    - Handle reconnect replay from journal
    - Send heartbeats
    - Clean up on disconnect (unsubscribe only — no persistence mutation)

    Safety guarantees:
    - Does NOT call runtime registry mutation functions.
    - Does NOT call projection mutation functions.
    - Does NOT write to active_workflows/ or memory/.
    - Does NOT clear workflow events or journal files.
    - Cleanup removes only WebSocket runtime connection/subscription resources.
    """

    def __init__(self):
        # workflow_id -> list of _ConnectionState
        self._states: Dict[str, List[_ConnectionState]] = defaultdict(list)
        # websocket -> _ConnectionState for O(1) send-lock lookup
        self._state_by_socket: Dict[WebSocket, _ConnectionState] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        workflow_id: str,
        websocket: WebSocket,
    ) -> None:
        """
        Accept a WebSocket connection and subscribe to EventBus.

        Does NOT replay events here — replay is handled on subscribe_workflow command.
        Creates exactly one EventBus subscription and one event consumer per socket.
        """
        await websocket.accept()

        # Subscribe to EventBus for this workflow
        bus = get_event_bus()
        queue = bus.subscribe_async(workflow_id)

        # Start event consumer task BEFORE tracking so it is ready
        task = asyncio.create_task(
            self._event_consumer(workflow_id, websocket, queue),
            name=f"ws_consumer_{workflow_id}_{id(websocket)}",
        )

        state = _ConnectionState(websocket, queue, task)

        async with self._lock:
            self._states[workflow_id].append(state)
            self._state_by_socket[websocket] = state

        print(f"[WS] Connected: workflow={workflow_id}, client={websocket.client}")

    async def disconnect(
        self,
        workflow_id: str,
        websocket: WebSocket,
    ) -> None:
        """
        Clean up a WebSocket connection.

        Idempotent: safe to call more than once.
        Unsubscribes only THIS socket's EventBus queue.
        Cancels only THIS socket's consumer task.
        Does NOT touch workflow persistence.
        """
        async with self._lock:
            state = self._state_by_socket.get(websocket)

            if state is None:
                # Already disconnected or never tracked
                return

            # Remove from both indexes
            self._state_by_socket.pop(websocket, None)
            if state in self._states.get(workflow_id, []):
                self._states[workflow_id].remove(state)

            # Mark disconnected to prevent duplicate cleanup
            state.disconnected = True

        # Unsubscribe this specific queue from EventBus
        bus = get_event_bus()
        try:
            bus.unsubscribe_async(workflow_id, state.queue)
        except Exception:
            pass

        # Cancel this specific consumer task
        if not state.task.done():
            state.task.cancel()
            try:
                await state.task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        print(f"[WS] Disconnected: workflow={workflow_id}, client={websocket.client}")

    async def _send_locked(
        self,
        websocket: WebSocket,
        message: Dict[str, Any],
    ) -> bool:
        """
        Send a message to a specific WebSocket under its per-connection lock.

        Serializes all outbound traffic for a single socket to prevent
        concurrent-send corruption from multiple async tasks.
        Returns True if sent successfully, False if socket is dead.
        """
        state = self._state_by_socket.get(websocket)

        # Fallback: if state not found (e.g., during cleanup), try direct send
        if state is None:
            try:
                await websocket.send_json(message)
                return True
            except Exception:
                return False

        async with state.send_lock:
            try:
                await websocket.send_json(message)
                return True
            except Exception:
                return False

    async def send_to_socket(
        self,
        websocket: WebSocket,
        message: Dict[str, Any],
    ) -> bool:
        """
        Public wrapper for _send_locked.

        Used by the endpoint command loop to serialize ack/error/heartbeat
        sends with the event consumer's event sends.
        """
        return await self._send_locked(websocket, message)

    async def _event_consumer(
        self,
        workflow_id: str,
        websocket: WebSocket,
        queue: asyncio.Queue,
    ) -> None:
        """
        Consume events from EventBus queue and send to WebSocket.

        Failure-isolated: send failures trigger disconnect of dead socket.
        All sends go through _send_locked for serialization.
        """
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    if not await self._send_locked(websocket, build_heartbeat_message()):
                        # Socket dead — exit consumer
                        break
                    continue

                # Build full-payload event message (NOT hint-only like SSE)
                msg = build_event_message(
                    workflow_id=event.get("workflow_id", workflow_id),
                    event_type=event.get("event_type", "unknown"),
                    bus_sequence_id=event.get("bus_sequence_id", 0),
                    execution_generation=event.get("data", {}).get("execution_generation"),
                    payload=event.get("data", {}),
                )

                if not await self._send_locked(websocket, msg):
                    # Socket dead — exit consumer
                    break

        except asyncio.CancelledError:
            # Normal shutdown
            pass
        except Exception as e:
            print(f"[WS] Event consumer error for {workflow_id}: {e}")
        finally:
            # Unsubscribe this specific queue from EventBus
            bus = get_event_bus()
            try:
                bus.unsubscribe_async(workflow_id, queue)
            except Exception:
                pass

    async def broadcast_to_workflow(
        self,
        workflow_id: str,
        message: Dict[str, Any],
    ) -> None:
        """
        Broadcast a message to all connections for a workflow.

        Dead sockets are removed. Does NOT mutate workflow state.
        """
        async with self._lock:
            states = list(self._states.get(workflow_id, []))

        dead: List[_ConnectionState] = []
        for state in states:
            if not await self._send_locked(state.websocket, message):
                dead.append(state)

        if dead:
            async with self._lock:
                for d in dead:
                    if d in self._states[workflow_id]:
                        self._states[workflow_id].remove(d)

    async def replay_missed_events(
        self,
        workflow_id: str,
        websocket: WebSocket,
        since_sequence: int,
    ) -> int:
        """
        Replay missed events from journal to a WebSocket connection.

        Replay events are sent through the same _send_locked path as live
        events, so they are serialized with all other outbound traffic.
        Returns the number of events replayed.
        Does NOT mutate workflow state or journal.

        NOTE: The live consumer is already running, so live events may
        interleave with replayed events. Clients MUST deduplicate by
        bus_sequence_id, which is monotonic per workflow.
        """
        try:
            missed_events = get_events(
                workflow_id,
                since_sequence=since_sequence,
                limit=REPLAY_LIMIT,
            )
            # Sort by bus_sequence_id for deterministic delivery
            missed_events.sort(key=lambda e: e.get("bus_sequence_id", 0))

            replayed = 0
            for event in missed_events:
                msg = build_event_message(
                    workflow_id=event.get("workflow_id", workflow_id),
                    event_type=event.get("event_type", "unknown"),
                    bus_sequence_id=event.get("bus_sequence_id", 0),
                    execution_generation=event.get("data", {}).get("execution_generation"),
                    payload=event.get("data", {}),
                )
                if await self._send_locked(websocket, msg):
                    replayed += 1
                else:
                    # Socket died during replay — stop
                    break

            return replayed
        except Exception as e:
            print(f"[WS] Replay error for {workflow_id}: {e}")
            return 0


# =============================================================================
# Command Handler
# =============================================================================

class WebSocketCommandHandler:
    """
    Handle non-mutating WebSocket commands.

    Phase 1B scope only — NO lifecycle mutation commands.
    Each command returns an ack message dict.
    """

    def __init__(self, manager: WorkflowWebSocketManager):
        self._manager = manager

    async def handle(
        self,
        workflow_id: str,
        websocket: WebSocket,
        command: str,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Dispatch a command to its handler.

        Returns an ack/error message dict, or None if no response needed.
        """
        # Explicitly reject prohibited commands
        if command in PROHIBITED_COMMANDS:
            return build_error_message(
                workflow_id=workflow_id,
                correlation_id=correlation_id,
                status="blocked",
                reason="command_prohibited_in_phase_1b",
                detail=f"Command '{command}' is not allowed in Phase 1B. Use existing HTTP endpoints.",
            )

        if command not in ALLOWED_COMMANDS:
            return build_ack_message(
                workflow_id=workflow_id,
                command=command,
                correlation_id=correlation_id,
                status="rejected",
                payload={"reason": "unknown_command", "allowed": sorted(ALLOWED_COMMANDS)},
            )

        handler = getattr(self, f"_handle_{command}", None)
        if handler is None:
            return build_ack_message(
                workflow_id=workflow_id,
                command=command,
                correlation_id=correlation_id,
                status="rejected",
                payload={"reason": "handler_not_found"},
            )

        try:
            return await handler(workflow_id, websocket, payload, correlation_id)
        except Exception as e:
            return build_ack_message(
                workflow_id=workflow_id,
                command=command,
                correlation_id=correlation_id,
                status="server_error",
                payload={"reason": str(e)},
            )

    async def _handle_ping(
        self,
        workflow_id: str,
        websocket: WebSocket,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        return build_ack_message(
            workflow_id=workflow_id,
            command="ping",
            correlation_id=correlation_id,
            status="accepted",
            payload={"pong": True},
        )

    async def _handle_client_hello(
        self,
        workflow_id: str,
        websocket: WebSocket,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        return build_ack_message(
            workflow_id=workflow_id,
            command="client_hello",
            correlation_id=correlation_id,
            status="accepted",
            payload={
                "server_schema_version": 1,
                "supported_commands": sorted(ALLOWED_COMMANDS),
                "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
            },
        )

    async def _handle_client_ready(
        self,
        workflow_id: str,
        websocket: WebSocket,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        return build_ack_message(
            workflow_id=workflow_id,
            command="client_ready",
            correlation_id=correlation_id,
            status="accepted",
        )

    async def _handle_subscribe_workflow(
        self,
        workflow_id: str,
        websocket: WebSocket,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Handle subscribe_workflow command.

        If payload includes since_sequence, replay missed events from journal.
        Does NOT mutate workflow state.
        """
        since_sequence = payload.get("since_sequence")
        replayed = 0

        if isinstance(since_sequence, int) and since_sequence >= 0:
            replayed = await self._manager.replay_missed_events(
                workflow_id, websocket, since_sequence
            )

        latest_seq = get_latest_sequence(workflow_id)

        return build_ack_message(
            workflow_id=workflow_id,
            command="subscribe_workflow",
            correlation_id=correlation_id,
            status="accepted",
            payload={
                "subscribed_at_sequence": latest_seq,
                "replayed_events": replayed,
                "current_projection_version": None,  # Projection not delivered over WS
            },
        )

    async def _handle_unsubscribe_workflow(
        self,
        workflow_id: str,
        websocket: WebSocket,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Handle unsubscribe_workflow command.

        Returns ack. Actual cleanup happens on disconnect.
        Does NOT mutate workflow state.
        """
        return build_ack_message(
            workflow_id=workflow_id,
            command="unsubscribe_workflow",
            correlation_id=correlation_id,
            status="accepted",
            payload={"note": "Cleanup occurs on disconnect."},
        )

    async def _handle_request_resync(
        self,
        workflow_id: str,
        websocket: WebSocket,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Handle request_resync command.

        Returns ack instructing client to refresh via existing HTTP projection endpoint.
        Does NOT send projection payload over WebSocket.
        """
        return build_ack_message(
            workflow_id=workflow_id,
            command="request_resync",
            correlation_id=correlation_id,
            status="accepted",
            payload={
                "action": "refresh_projection_via_http",
                "endpoint": f"/projection/{workflow_id}",
                "note": "Projection payload not delivered over WebSocket. Use HTTP snapshot.",
            },
        )

    async def _handle_request_snapshot_refresh(
        self,
        workflow_id: str,
        websocket: WebSocket,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Handle request_snapshot_refresh command.

        Returns ack instructing client to refresh via existing HTTP projection endpoint.
        Does NOT send projection payload over WebSocket.
        """
        return build_ack_message(
            workflow_id=workflow_id,
            command="request_snapshot_refresh",
            correlation_id=correlation_id,
            status="accepted",
            payload={
                "action": "refresh_projection_via_http",
                "endpoint": f"/projection/{workflow_id}",
                "note": "Projection payload not delivered over WebSocket. Use HTTP snapshot.",
            },
        )

    # =========================================================================
    # Sprint 9C-4B: Minimal lifecycle command wrappers
    # =========================================================================
    # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
    # - WebSocket is transport-only.
    # - These handlers call the SAME authority functions used by HTTP endpoints.
    # - Ack = accepted/rejected/validation_error only.
    # - Lifecycle truth still arrives via runtime/projection/events.
    # =========================================================================

    def _validate_wrapper_payload(
        self,
        workflow_id: str,
        payload: Dict[str, Any],
        correlation_id: str,
        command: str,
    ) -> Optional[Dict[str, Any]]:
        """Validate payload workflow_id matches socket path workflow_id."""
        payload_wf_id = payload.get("workflow_id")
        if payload_wf_id is not None and payload_wf_id != workflow_id:
            return build_error_message(
                workflow_id=workflow_id,
                correlation_id=correlation_id,
                status="validation_error",
                reason="missing_or_mismatched_workflow_id",
                detail=f"Socket path workflow_id ({workflow_id}) does not match payload workflow_id ({payload_wf_id}).",
            )
        return None

    async def _handle_pause(
        self,
        workflow_id: str,
        websocket: WebSocket,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Handle pause command.
        Calls pause_workflow() — the same authority used by POST /pause/{workflow_id}.
        """
        validation_err = self._validate_wrapper_payload(workflow_id, payload, correlation_id, "pause")
        if validation_err:
            return validation_err

        result = pause_workflow(workflow_id)
        if result.get("status") == "failure":
            return build_ack_message(
                workflow_id=workflow_id,
                command="pause",
                correlation_id=correlation_id,
                status="rejected",
                payload={"reason": result.get("reason", "unknown")},
            )
        return build_ack_message(
            workflow_id=workflow_id,
            command="pause",
            correlation_id=correlation_id,
            status="accepted",
            payload={
                "note": "Forwarded to lifecycle authority. Transition truth arrives via events.",
                "previous_state": result.get("previous_state"),
                "new_state": result.get("new_state"),
            },
        )

    async def _handle_resume(
        self,
        workflow_id: str,
        websocket: WebSocket,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Handle resume command.
        Calls _trigger_execution_resume() — the same authority used by POST /resume/{workflow_id}.
        """
        validation_err = self._validate_wrapper_payload(workflow_id, payload, correlation_id, "resume")
        if validation_err:
            return validation_err

        # Local import to avoid circular dependency with api.py
        from ai_lab_gui.backend.api import _trigger_execution_resume
        result = _trigger_execution_resume(workflow_id)
        if result.get("status") == "failure":
            return build_ack_message(
                workflow_id=workflow_id,
                command="resume",
                correlation_id=correlation_id,
                status="rejected",
                payload={"reason": result.get("reason", "unknown")},
            )
        return build_ack_message(
            workflow_id=workflow_id,
            command="resume",
            correlation_id=correlation_id,
            status="accepted",
            payload={
                "note": "Forwarded to lifecycle authority. Transition truth arrives via events.",
                "bg_id": result.get("bg_id"),
            },
        )

    async def _handle_cancel(
        self,
        workflow_id: str,
        websocket: WebSocket,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        """
        Handle cancel command.
        Calls cancel_workflow() — the same authority used by POST /workflow/cancel.
        """
        validation_err = self._validate_wrapper_payload(workflow_id, payload, correlation_id, "cancel")
        if validation_err:
            return validation_err

        # Use "user_cancel" reason to match HTTP endpoint behavior
        result = cancel_workflow(workflow_id, reason="user_cancel")
        if result.get("status") == "failure":
            return build_ack_message(
                workflow_id=workflow_id,
                command="cancel",
                correlation_id=correlation_id,
                status="rejected",
                payload={"reason": result.get("reason", "unknown")},
            )
        return build_ack_message(
            workflow_id=workflow_id,
            command="cancel",
            correlation_id=correlation_id,
            status="accepted",
            payload={
                "note": "Forwarded to lifecycle authority. Transition truth arrives via events.",
            },
        )


# =============================================================================
# Global singleton instance
# =============================================================================

# Per ISSUE-002: Global singleton concurrency debt is acknowledged.
# For Phase 1B, a single manager instance is sufficient.
# Future multi-workflow hardening may require instance isolation.
_ws_manager: Optional[WorkflowWebSocketManager] = None


def get_websocket_manager() -> WorkflowWebSocketManager:
    """Get or create the global WebSocket manager instance."""
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WorkflowWebSocketManager()
    return _ws_manager


def get_command_handler() -> WebSocketCommandHandler:
    """Get a command handler bound to the global manager."""
    return WebSocketCommandHandler(get_websocket_manager())
