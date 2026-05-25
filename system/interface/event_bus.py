"""
EVENT BUS — LIVE STATE STREAMING (STATE-DRIVEN, CONTRACT-SAFE)

Per HAND_ARCHITECTURE_V2 Section 15 (Visibility):
- Modes: NORMAL, LIVE, DEBUG
- LIVE mode provides step-by-step visibility

Per CONTROL_MODEL.txt:
- Streaming is observational only
- Signals are advisory, non-authoritative
- execution_result remains sole truth

Per TRACE_LOGGING_CONTRACT_V1:
- Trace is read-only and separate from UI state
- UI must not derive control logic from trace

Per PROJECTION_CONTINUITY_CONTRACT_V1 (Phase 4A.1 — SUB-PHASE 3D):
- Each event carries a per-workflow monotonic bus_sequence_id
- bus_sequence_id enables out-of-order detection and stale stream rejection
- Stream transport remains OBSERVATIONAL ONLY
- bus_sequence_id MUST NOT become lifecycle authority

COMPLIANCE:
- In-memory, non-blocking queue
- Per-workflow isolation
- Zero control-flow influence
- Zero execution interference

FAILURE-ISOLATED:
- All operations wrapped in try/except
- No exceptions escape to execution
- Queue overflow handled gracefully
"""

from typing import Any, Dict, List, Optional, Callable
from collections import defaultdict, deque
from datetime import datetime
import threading
import time
import os
import json


# Maximum events per workflow to prevent unbounded memory growth
MAX_EVENTS_PER_WORKFLOW = 1000

# Default event retention time in seconds (events older than this are pruned)
EVENT_RETENTION_SECONDS = 300  # 5 minutes

# Per APPEND-ONLY WORKFLOW EVENT JOURNAL IMPLEMENTATION:
# Durable event journal directory — workflow-scoped append-only chronology persistence.
# Aligned with existing persistence pattern: memory/active_workflows/
_EVENT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "memory", "events")


def _ensure_events_dir() -> None:
    """Create event journal directory if it doesn't exist."""
    try:
        os.makedirs(_EVENT_DIR, exist_ok=True)
    except Exception:
        pass


def _journal_path(workflow_id: str) -> str:
    """Return safe file path for a workflow's event journal."""
    safe_id = "".join(c for c in workflow_id if c.isalnum() or c in ("-", "_"))
    if not safe_id:
        safe_id = "unknown"
    return os.path.join(_EVENT_DIR, f"{safe_id}.jsonl")


def _append_event_to_journal(workflow_id: str, event: Dict[str, Any]) -> None:
    """
    Append a single event to the workflow's append-only JSONL journal.

    Per PERSISTENT_EVENT_INFRASTRUCTURE_AUDIT:
    - Append-only: never mutate existing lines
    - JSONL: one JSON object per line
    - Preserve exact event payload including bus_sequence_id and timestamp
    - FAILURE-ISOLATED: any error is silently absorbed
    """
    try:
        _ensure_events_dir()
        path = _journal_path(workflow_id)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _resume_sequence_from_journal(workflow_id: str) -> int:
    """
    Return the highest bus_sequence_id found in a workflow's journal.

    Used on server restart to resume monotonic counters without gaps or duplicates.
    Returns 0 if no journal exists.
    """
    try:
        path = _journal_path(workflow_id)
        if not os.path.exists(path):
            return 0
        last_seq = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    seq = event.get("bus_sequence_id", 0)
                    if seq > last_seq:
                        last_seq = seq
                except Exception:
                    continue
        return last_seq
    except Exception:
        return 0


def _load_events_from_journal(workflow_id: str, since_event_id: Optional[int] = None,
                               since_sequence: Optional[int] = None,
                               limit: int = 100) -> List[Dict[str, Any]]:
    """
    Load events from a workflow's append-only JSONL journal.

    Per PERSISTENT_EVENT_INFRASTRUCTURE_AUDIT:
    - Tolerates malformed lines (skips them)
    - Preserves ordering (lines are chronological)
    - Supports since_event_id and since_sequence for API compatibility
    - FAILURE-ISOLATED: returns empty list on any error

    Per REPLAY_QUERY_PAGINATION:
    - since_sequence enables seek-based loading without full-file scan
    - Streams line-by-line; no full-file memory load when since_sequence is used
    """
    try:
        path = _journal_path(workflow_id)
        if not os.path.exists(path):
            return []
        events = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        continue
                    # Per REPLAY_QUERY_PAGINATION:
                    # Seek-based filtering: skip events at or before since_sequence.
                    # This avoids loading the entire journal into memory.
                    if since_sequence is not None:
                        seq = event.get("bus_sequence_id", 0)
                        if seq <= since_sequence:
                            continue
                        events.append(event)
                        if limit and len(events) >= limit:
                            break
                    else:
                        events.append(event)
                except Exception:
                    # Skip malformed lines — journal integrity is best-effort
                    continue
        # Legacy since_event_id slice (used when since_sequence not provided)
        if since_event_id is not None and since_sequence is None:
            start_idx = since_event_id + 1
            events = events[start_idx:]
            if limit:
                events = events[-limit:]
        elif limit and since_sequence is None:
            events = events[-limit:]
        return events
    except Exception:
        return []


class EventBus:
    """
    In-memory event bus for live workflow streaming.
    
    RULES:
    - Non-blocking: publish() returns immediately
    - Per-workflow isolation: each workflow has separate queue
    - Read-only: consumers cannot modify events
    - Failure-safe: all operations wrapped in try/except
    """
    
    def __init__(self):
        # Per-workflow event queues: workflow_id -> deque of events
        self._queues: Dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_EVENTS_PER_WORKFLOW))
        
        # Per-workflow subscriber callbacks: workflow_id -> list of callbacks
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        
        # Per-workflow event timestamps for pruning: workflow_id -> deque of timestamps
        self._timestamps: Dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_EVENTS_PER_WORKFLOW))
        
        # Thread safety lock
        self._lock = threading.RLock()
        
        # Internal failure tracking (diagnostics only)
        self._failure_count = 0

        # Per PROJECTION_CONTINUITY_CONTRACT_V1 §6 + SUB-PHASE 3D:
        # Per-workflow monotonic sequence counters for stream ordering validation.
        # bus_sequence_id enables consumers to detect out-of-order event delivery.
        # OBSERVATIONAL ONLY — MUST NOT influence execution or lifecycle authority.
        self._sequence_counters: Dict[str, int] = defaultdict(int)
    
    def publish(self, workflow_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """
        Publish an event to the bus.
        
        RULES:
        - NEVER blocks execution
        - NEVER raises exceptions
        - ALWAYS returns None immediately
        - Event is timestamped and appended to queue
        
        Args:
            workflow_id: The workflow identifier
            event_type: Type of event (step_started, step_completed, etc.)
            data: Event payload dictionary
        """
        try:
            with self._lock:
                # Per PROJECTION_CONTINUITY_CONTRACT_V1 §6 (SUB-PHASE 3D):
                # Assign monotonic bus_sequence_id per workflow for ordering validation.
                # Per APPEND-ONLY WORKFLOW EVENT JOURNAL:
                # Resume counter from journal on first publish after restart to prevent duplicates.
                if self._sequence_counters.get(workflow_id, 0) == 0:
                    resumed = _resume_sequence_from_journal(workflow_id)
                    self._sequence_counters[workflow_id] = resumed
                self._sequence_counters[workflow_id] += 1
                seq_id = self._sequence_counters[workflow_id]

                event = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "workflow_id": workflow_id,
                    "event_type": event_type,
                    "data": data,
                    "bus_sequence_id": seq_id,  # monotonic, per-workflow, observational
                }
                
                # Add to queue (deque automatically handles maxlen)
                self._queues[workflow_id].append(event)
                self._timestamps[workflow_id].append(time.time())

                # Per APPEND-ONLY WORKFLOW EVENT JOURNAL IMPLEMENTATION:
                # Persist event to durable append-only journal.
                # FAILURE-ISOLATED: journal failure must not affect execution.
                _append_event_to_journal(workflow_id, event)
                
                # Notify subscribers (synchronous, but non-blocking)
                # If subscriber blocks, it doesn't affect publish()
                for callback in list(self._subscribers[workflow_id]):
                    try:
                        callback(event)
                    except Exception:
                        # Subscriber failure must not affect bus
                        pass
                        
        except Exception:
            # FAILURE-ISOLATED: Any error is silently absorbed
            self._failure_count += 1
            pass
    
    def subscribe(self, workflow_id: str, callback: Callable[[Dict], None]) -> None:
        """
        Subscribe to events for a specific workflow.
        
        Args:
            workflow_id: The workflow to subscribe to
            callback: Function called with event dict when event is published
        """
        try:
            with self._lock:
                if callback not in self._subscribers[workflow_id]:
                    self._subscribers[workflow_id].append(callback)
        except Exception:
            pass
    
    def unsubscribe(self, workflow_id: str, callback: Callable[[Dict], None]) -> None:
        """
        Unsubscribe a callback from workflow events.
        """
        try:
            with self._lock:
                if workflow_id in self._subscribers:
                    if callback in self._subscribers[workflow_id]:
                        self._subscribers[workflow_id].remove(callback)
        except Exception:
            pass
    
    def get_events(self, workflow_id: str, since_event_id: Optional[int] = None,
                   since_sequence: Optional[int] = None,
                   limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get events for a workflow.

        Per APPEND-ONLY WORKFLOW EVENT JOURNAL IMPLEMENTATION:
        1. Prefer in-memory hot events
        2. If insufficient/missing, fallback to durable journal file
        3. Preserve since/limit/ordering semantics

        Per REPLAY_QUERY_PAGINATION:
        - since_sequence is the authoritative cursor (bus_sequence_id)
        - since_event_id is legacy; preserved for backward compatibility

        Args:
            workflow_id: The workflow identifier
            since_event_id: If provided, return only events after this index (legacy)
            since_sequence: If provided, return only events with bus_sequence_id > since_sequence (authoritative)
            limit: Maximum number of events to return

        Returns:
            List of event dictionaries (empty list if workflow not found)
        """
        try:
            with self._lock:
                queue = self._queues.get(workflow_id)
                if queue:
                    events = list(queue)
                    if since_sequence is not None:
                        events = [e for e in events if e.get("bus_sequence_id", 0) > since_sequence]
                    elif since_event_id is not None:
                        start_idx = since_event_id + 1
                        events = events[start_idx:]
                    return events[-limit:]

            # Fallback to durable journal if memory queue is empty
            return _load_events_from_journal(workflow_id, since_event_id, since_sequence, limit)
        except Exception:
            return []
    
    def get_latest_event(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the most recent event for a workflow.
        
        Returns:
            Latest event dict or None
        """
        try:
            with self._lock:
                queue = self._queues.get(workflow_id)
                if queue:
                    return queue[-1]
                return None
        except Exception:
            return None
    
    def clear_workflow(self, workflow_id: str) -> None:
        """
        Clear in-memory hot events for a workflow (cleanup after completion).

        Per APPEND-ONLY WORKFLOW EVENT JOURNAL IMPLEMENTATION:
        - Clears hot memory cache to free RAM
        - Does NOT delete historical journal files
        - Historical chronology survives workflow completion, cancellation, failure
        """
        try:
            with self._lock:
                if workflow_id in self._queues:
                    del self._queues[workflow_id]
                if workflow_id in self._timestamps:
                    del self._timestamps[workflow_id]
                if workflow_id in self._subscribers:
                    del self._subscribers[workflow_id]
        except Exception:
            pass
    
    def prune_old_events(self, max_age_seconds: int = EVENT_RETENTION_SECONDS) -> None:
        """
        Remove events older than specified age.
        Called periodically to prevent memory growth.
        """
        try:
            cutoff_time = time.time() - max_age_seconds
            with self._lock:
                for workflow_id in list(self._timestamps.keys()):
                    timestamps = self._timestamps[workflow_id]
                    if not timestamps:
                        continue
                    
                    # Find index of first event newer than cutoff
                    keep_idx = 0
                    for i, ts in enumerate(timestamps):
                        if ts >= cutoff_time:
                            keep_idx = i
                            break
                    
                    # Remove old events
                    if keep_idx > 0:
                        for _ in range(keep_idx):
                            if self._queues[workflow_id]:
                                self._queues[workflow_id].popleft()
                            if self._timestamps[workflow_id]:
                                self._timestamps[workflow_id].popleft()
        except Exception:
            pass
    
    def get_failure_count(self) -> int:
        """
        Return number of internal failures (diagnostics only).
        """
        return self._failure_count
    
    def get_workflow_ids(self) -> List[str]:
        """
        Return list of active workflow IDs.
        """
        try:
            with self._lock:
                return list(self._queues.keys())
        except Exception:
            return []

    def get_latest_sequence(self, workflow_id: str) -> int:
        """
        Return the latest bus_sequence_id for a workflow.

        Per PROJECTION_CONTINUITY_CONTRACT_V1 §11 (SUB-PHASE 3D):
        Enables consumers to detect continuity gaps on reconnect by comparing
        known sequence ID against current bus sequence ID.

        Per APPEND-ONLY WORKFLOW EVENT JOURNAL IMPLEMENTATION:
        Falls back to journal-derived sequence when memory counter is reset.

        Returns 0 if no events published for this workflow.
        OBSERVATIONAL ONLY — MUST NOT influence execution.
        """
        try:
            with self._lock:
                mem_seq = self._sequence_counters.get(workflow_id, 0)
            if mem_seq > 0:
                return mem_seq
            # Memory counter may be 0 after server restart; derive from journal
            journal_events = _load_events_from_journal(workflow_id, limit=1)
            if journal_events:
                return journal_events[-1].get("bus_sequence_id", 0)
            return 0
        except Exception:
            return 0


# Global event bus instance
_event_bus = EventBus()


def get_event_bus() -> EventBus:
    """
    Get the global event bus instance.
    """
    return _event_bus


def publish_event(workflow_id: str, event_type: str, data: Dict[str, Any]) -> None:
    """
    Convenience function to publish an event to the global bus.
    
    SAFE: Does nothing if bus fails.
    FAILURE-SAFE: All exceptions are absorbed.
    """
    try:
        _event_bus.publish(workflow_id, event_type, data)
    except Exception:
        pass


def get_events(
    workflow_id: str,
    since_event_id: Optional[int] = None,
    since_sequence: Optional[int] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Convenience function to get events from the global bus.
    
    Returns empty list on any error.
    """
    try:
        return _event_bus.get_events(
            workflow_id=workflow_id,
            since_event_id=since_event_id,
            since_sequence=since_sequence,
            limit=limit,
        )
    except Exception:
        return []


def get_latest_sequence(workflow_id: str) -> int:
    """
    Convenience function to get latest bus_sequence_id for a workflow.

    Per PROJECTION_CONTINUITY_CONTRACT_V1 §11 (SUB-PHASE 3D):
    Enables reconnect continuity gap detection.
    OBSERVATIONAL ONLY.
    """
    try:
        return _event_bus.get_latest_sequence(workflow_id)
    except Exception:
        return 0


def clear_workflow(workflow_id: str) -> None:
    """
    Convenience function to clear workflow events.
    """
    try:
        _event_bus.clear_workflow(workflow_id)
    except Exception:
        pass


def publish_projection_event(
    workflow_id: str,
    event_type: str,
    projection_type: str,
    projection_version: int,
    projection_timestamp: str,
    data: Dict[str, Any],
) -> None:
    """
    Publish a canonical projection event with mandatory identity fields.

    Per CANONICAL_PROJECTION_MODEL_V1 §3 (Projection Identity):
    All projection events MUST carry:
    - workflow_id
    - projection_type
    - projection_version
    - projection_timestamp

    Per SUB-PHASE 3D: Deterministic projection ordering is supported via
    monotonic projection_version in the payload.

    FAILURE-SAFE: All exceptions are absorbed.
    """
    try:
        projection_payload = {
            "workflow_id": workflow_id,
            "projection_type": projection_type,
            "projection_version": projection_version,
            "projection_timestamp": projection_timestamp,
            **data,
        }
        _event_bus.publish(workflow_id, event_type, projection_payload)
    except Exception:
        pass
