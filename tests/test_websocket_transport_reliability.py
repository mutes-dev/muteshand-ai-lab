"""
CATEGORY: OBSERVABILITY / TRANSPORT
AUTHORITY_LAYER: WebSocket and EventBus Reliability Validation
VALIDATES:
  - EventBus burst handling and maxlen retention
  - Async queue overflow drop-oldest behavior
  - Reconnect replay using since_sequence
  - Duplicate event delivery tolerance (frontend dedupe contract)
  - Heartbeat / stale socket cleanup
  - Prohibited WebSocket command blocking
ENTRYPOINT: event_bus, websocket_manager
DIRECT_INTERNAL_CALLS:
  - event_bus.EventBus
  - event_bus.get_events
  - websocket_manager.WebSocketCommandHandler
  - websocket_manager.WorkflowWebSocketManager
MONKEYPATCH_USAGE: HEARTBEAT_INTERVAL_SECONDS, _EVENT_DIR (test-scoped only)
MOCKING_POLICY: REAL_EVENT_BUS_INSTANCES, MOCK_WEBSOCKET
TEST_INTENT: UNIT_LEVEL_VALIDATION
ARCHITECTURAL_SCOPE: WebSocket transport and EventBus streaming layer only

Sprint 9C-4A: WebSocket Transport Reliability Tests
"""

import sys
import os
import asyncio
import time
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.interface.event_bus import EventBus


def _temp_event_bus():
    """Create an EventBus with a temporary journal directory to avoid test cross-contamination."""
    import system.interface.event_bus as _eb_mod
    tmpdir = tempfile.mkdtemp()
    orig_dir = _eb_mod._EVENT_DIR
    _eb_mod._EVENT_DIR = tmpdir
    bus = EventBus()
    return bus, tmpdir, orig_dir, _eb_mod


# =============================================================================
# EventBus Burst and Retention Tests
# =============================================================================

class TestEventBusBurstRetention:
    """Per Sprint 9C-4A: EventBus must not grow unbounded under burst."""

    def test_burst_capped_at_maxlen(self):
        bus, tmpdir, orig_dir, _eb_mod = _temp_event_bus()
        try:
            for i in range(2000):
                bus.publish("wf_burst", "test_event", {"i": i})
            events = bus.get_events("wf_burst", limit=5000)
            assert len(events) == 1000, f"Expected 1000 events, got {len(events)}"
        finally:
            _eb_mod._EVENT_DIR = orig_dir
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_journal_fallback_for_empty_memory(self):
        bus, tmpdir, orig_dir, _eb_mod = _temp_event_bus()
        try:
            for i in range(10):
                bus.publish("wf_journal", "evt", {"i": i})
            # Clear memory queue
            bus.clear_workflow("wf_journal")
            # get_events should fallback to journal if available
            events = bus.get_events("wf_journal", limit=100)
            # Journal should have the events since publish writes to it
            assert isinstance(events, list)
            assert len(events) == 10
        finally:
            _eb_mod._EVENT_DIR = orig_dir
            shutil.rmtree(tmpdir, ignore_errors=True)


# =============================================================================
# Async Queue Overflow Tests
# =============================================================================

class TestAsyncQueueOverflow:
    """Per Sprint 9C-4A: QueueFull must drop oldest, not crash."""

    def test_queue_full_drops_oldest(self):
        queue = asyncio.Queue(maxsize=5)
        for i in range(10):
            try:
                queue.put_nowait(i)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(i)
                except Exception:
                    pass
        result = []
        while not queue.empty():
            result.append(queue.get_nowait())
        assert result == [5, 6, 7, 8, 9], f"Expected [5,6,7,8,9], got {result}"


# =============================================================================
# Replay and Dedupe Tests
# =============================================================================

class TestReplayAndDedupe:
    """Per Sprint 9C-4A: Replay must use since_sequence; frontend dedupe must be possible."""

    def test_replay_since_sequence(self):
        bus, tmpdir, orig_dir, _eb_mod = _temp_event_bus()
        try:
            for i in range(50):
                bus.publish("wf_replay", "evt", {"i": i})
            # publish increments counter before assigning seq_id, so 50 events get IDs 1..50
            # since_sequence=25 => events with ID > 25 => IDs 26..50 = 25 events
            replayed = bus.get_events("wf_replay", since_sequence=25, limit=100)
            assert len(replayed) == 25, f"Expected 25 replayed events, got {len(replayed)}"
            assert replayed[0]["bus_sequence_id"] == 26
            assert replayed[-1]["bus_sequence_id"] == 50
        finally:
            _eb_mod._EVENT_DIR = orig_dir
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_replay_limit_respected(self):
        bus, tmpdir, orig_dir, _eb_mod = _temp_event_bus()
        try:
            for i in range(100):
                bus.publish("wf_replay_lim", "evt", {"i": i})
            replayed = bus.get_events("wf_replay_lim", since_sequence=0, limit=10)
            assert len(replayed) == 10
        finally:
            _eb_mod._EVENT_DIR = orig_dir
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_duplicate_race_tolerable(self):
        """
        Backend may deliver same event via replay and live independently.
        Frontend dedupes by bus_sequence_id. This test verifies backend
        delivers consistent sequence IDs so dedupe is possible.
        """
        bus, tmpdir, orig_dir, _eb_mod = _temp_event_bus()
        try:
            bus.publish("wf_dup", "evt", {"v": 1})
            bus.publish("wf_dup", "evt", {"v": 2})
            # Simulate replay path
            replayed = bus.get_events("wf_dup", since_sequence=0, limit=100)
            # Simulate live path (same queue)
            live = bus.get_events("wf_dup", since_sequence=0, limit=100)
            seq_ids_replay = {e["bus_sequence_id"] for e in replayed}
            seq_ids_live = {e["bus_sequence_id"] for e in live}
            assert seq_ids_replay == seq_ids_live
            # Frontend can dedupe by checking seen bus_sequence_id Set
        finally:
            _eb_mod._EVENT_DIR = orig_dir
            shutil.rmtree(tmpdir, ignore_errors=True)


# =============================================================================
# Heartbeat / Stale Socket Tests
# =============================================================================

class TestHeartbeatStaleSocket:
    """Per Sprint 9C-4A: Stale sockets must be cleaned via heartbeat timeout."""

    def test_heartbeat_sends_on_empty_queue(self):
        import system.interface.websocket_manager as wm
        orig_interval = wm.HEARTBEAT_INTERVAL_SECONDS
        try:
            wm.HEARTBEAT_INTERVAL_SECONDS = 0.05
            manager = wm.WorkflowWebSocketManager()

            sent = []

            class MockWS:
                async def send_json(self, msg):
                    sent.append(msg)
                    return True

            from system.interface.event_bus import get_event_bus
            bus = get_event_bus()
            queue = bus.subscribe_async("wf_hb")

            async def run_consumer():
                task = asyncio.create_task(
                    manager._event_consumer("wf_hb", MockWS(), queue)
                )
                await asyncio.sleep(0.15)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            asyncio.run(run_consumer())
            # Should have received at least one heartbeat (type="heartbeat")
            heartbeats = [m for m in sent if m.get("type") == "heartbeat"]
            assert len(heartbeats) >= 1, f"Expected >=1 heartbeat, got {len(heartbeats)}"
        finally:
            wm.HEARTBEAT_INTERVAL_SECONDS = orig_interval

    def test_heartbeat_dead_socket_stops_consumer(self):
        import system.interface.websocket_manager as wm
        orig_interval = wm.HEARTBEAT_INTERVAL_SECONDS
        try:
            wm.HEARTBEAT_INTERVAL_SECONDS = 0.05
            manager = wm.WorkflowWebSocketManager()

            class DeadWS:
                async def send_json(self, msg):
                    raise ConnectionResetError("simulated dead socket")  # Simulate dead socket

            from system.interface.event_bus import get_event_bus
            bus = get_event_bus()
            queue = bus.subscribe_async("wf_dead")

            async def run_consumer():
                task = asyncio.create_task(
                    manager._event_consumer("wf_dead", DeadWS(), queue)
                )
                # Consumer should exit quickly because send fails; give it up to 1s
                await asyncio.wait_for(task, timeout=1.0)

            asyncio.run(run_consumer())
        finally:
            wm.HEARTBEAT_INTERVAL_SECONDS = orig_interval


# =============================================================================
# Prohibited Command Tests
# =============================================================================

class TestProhibitedCommands:
    """Per Sprint 9C-4B: pause/resume/cancel are now wrappers; retry/approve/deny remain blocked."""

    def test_pause_command_now_allowed_with_wrapper(self, monkeypatch):
        # Sprint 9C-4B: pause is no longer blocked — it's a thin wrapper
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        monkeypatch.setattr(
            "system.interface.websocket_manager.pause_workflow",
            lambda wf_id: {"status": "failure", "reason": "workflow_not_found"},
        )

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "pause", {}, "corr_1")
            assert response["status"] == "rejected"  # authority rejected, not blocked

        asyncio.run(run())

    def test_resume_command_now_allowed_with_wrapper(self, monkeypatch):
        # Sprint 9C-4B: resume is no longer blocked — it's a thin wrapper
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        monkeypatch.setattr(
            "ai_lab_gui.backend.api._trigger_execution_resume",
            lambda wf_id, skip_generation_increment=False: {"status": "failure", "reason": "not_paused"},
        )

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "resume", {}, "corr_1")
            assert response["status"] == "rejected"  # authority rejected, not blocked

        asyncio.run(run())

    def test_cancel_command_now_allowed_with_wrapper(self, monkeypatch):
        # Sprint 9C-4B: cancel is no longer blocked — it's a thin wrapper
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        monkeypatch.setattr(
            "system.interface.websocket_manager.cancel_workflow",
            lambda wf_id, reason="user_cancel": {"status": "failure", "reason": "already_terminal"},
        )

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "cancel", {}, "corr_1")
            assert response["status"] == "rejected"  # authority rejected, not blocked

        asyncio.run(run())

    def test_allowed_command_accepted(self):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "ping", {}, "corr_1")
            assert response["status"] == "accepted"

        asyncio.run(run())

    def test_unknown_command_rejected(self):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "unknown_cmd", {}, "corr_1")
            assert response["status"] == "rejected"

        asyncio.run(run())


# =============================================================================
# Per-Workflow Isolation Tests
# =============================================================================

class TestWorkflowIsolation:
    """Per Sprint 9C-4A: Events must remain isolated per workflow_id."""

    def test_cross_workflow_no_contamination(self):
        bus, tmpdir, orig_dir, _eb_mod = _temp_event_bus()
        try:
            bus.publish("wf_a", "evt", {"v": 1})
            bus.publish("wf_b", "evt", {"v": 2})
            a_events = bus.get_events("wf_a", limit=100)
            b_events = bus.get_events("wf_b", limit=100)
            assert len(a_events) == 1
            assert len(b_events) == 1
            assert a_events[0]["data"]["v"] == 1
            assert b_events[0]["data"]["v"] == 2
        finally:
            _eb_mod._EVENT_DIR = orig_dir
            shutil.rmtree(tmpdir, ignore_errors=True)


# =============================================================================
# Sprint 9C-4B: Lifecycle Command Wrapper Tests
# =============================================================================

class TestLifecycleCommandWrappers:
    """Per Sprint 9C-4B: pause/resume/cancel WebSocket wrappers call HTTP authority."""

    def test_pause_accepted(self, monkeypatch):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        # Mock pause_workflow to simulate authority acceptance
        monkeypatch.setattr(
            "system.interface.websocket_manager.pause_workflow",
            lambda wf_id: {"status": "success", "previous_state": "ACTIVE", "new_state": "PAUSED"},
        )

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "pause", {}, "corr_pause_1")
            assert response["type"] == "ack"
            assert response["status"] == "accepted"
            assert response["command"] == "pause"
            assert response["correlation_id"] == "corr_pause_1"
            assert "Transition truth arrives via events" in response["payload"]["note"]

        asyncio.run(run())

    def test_pause_rejected(self, monkeypatch):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        monkeypatch.setattr(
            "system.interface.websocket_manager.pause_workflow",
            lambda wf_id: {"status": "failure", "reason": "workflow_not_active"},
        )

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "pause", {}, "corr_pause_2")
            assert response["status"] == "rejected"
            assert response["payload"]["reason"] == "workflow_not_active"

        asyncio.run(run())

    def test_resume_accepted(self, monkeypatch):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        # Mock _trigger_execution_resume (local import target)
        monkeypatch.setattr(
            "ai_lab_gui.backend.api._trigger_execution_resume",
            lambda wf_id, skip_generation_increment=False: {
                "status": "ok", "resumed": True, "workflow_id": wf_id, "bg_id": "bg_resume_1"
            },
        )

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "resume", {}, "corr_resume_1")
            assert response["type"] == "ack"
            assert response["status"] == "accepted"
            assert response["command"] == "resume"
            assert response["correlation_id"] == "corr_resume_1"
            assert response["payload"]["bg_id"] == "bg_resume_1"

        asyncio.run(run())

    def test_resume_rejected(self, monkeypatch):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        monkeypatch.setattr(
            "ai_lab_gui.backend.api._trigger_execution_resume",
            lambda wf_id, skip_generation_increment=False: {"status": "failure", "reason": "not_paused"},
        )

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "resume", {}, "corr_resume_2")
            assert response["status"] == "rejected"
            assert response["payload"]["reason"] == "not_paused"

        asyncio.run(run())

    def test_cancel_accepted(self, monkeypatch):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        monkeypatch.setattr(
            "system.interface.websocket_manager.cancel_workflow",
            lambda wf_id, reason="user_cancel": {"status": "success", "previous_state": "ACTIVE", "new_state": "CANCELLED"},
        )

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "cancel", {}, "corr_cancel_1")
            assert response["type"] == "ack"
            assert response["status"] == "accepted"
            assert response["command"] == "cancel"
            assert response["correlation_id"] == "corr_cancel_1"

        asyncio.run(run())

    def test_cancel_rejected(self, monkeypatch):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        monkeypatch.setattr(
            "system.interface.websocket_manager.cancel_workflow",
            lambda wf_id, reason="user_cancel": {"status": "failure", "reason": "already_terminal"},
        )

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "cancel", {}, "corr_cancel_2")
            assert response["status"] == "rejected"
            assert response["payload"]["reason"] == "already_terminal"

        asyncio.run(run())

    def test_workflow_id_mismatch_returns_validation_error(self, monkeypatch):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        class MockWS:
            pass

        async def run():
            response = await handler.handle(
                "wf_socket", MockWS(), "pause", {"workflow_id": "wf_payload"}, "corr_mismatch"
            )
            assert response["type"] == "error"
            assert response["status"] == "validation_error"
            assert "missing_or_mismatched_workflow_id" in response["reason"]

        asyncio.run(run())

    def test_retry_force_retry_approve_deny_remain_blocked(self):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        class MockWS:
            pass

        async def run():
            for cmd in ("retry", "force_retry", "approve", "deny"):
                response = await handler.handle("wf_1", MockWS(), cmd, {}, f"corr_{cmd}")
                assert response["status"] == "blocked", f"Command {cmd} should be blocked"

        asyncio.run(run())

    def test_ack_correlation_id_matches_incoming(self, monkeypatch):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        monkeypatch.setattr(
            "system.interface.websocket_manager.pause_workflow",
            lambda wf_id: {"status": "success"},
        )

        class MockWS:
            pass

        async def run():
            msg_id = "my_custom_message_id_123"
            response = await handler.handle("wf_1", MockWS(), "pause", {}, msg_id)
            assert response["correlation_id"] == msg_id

        asyncio.run(run())

    def test_ack_does_not_claim_transition_completed(self, monkeypatch):
        from system.interface.websocket_manager import WebSocketCommandHandler, WorkflowWebSocketManager
        manager = WorkflowWebSocketManager()
        handler = WebSocketCommandHandler(manager)

        monkeypatch.setattr(
            "system.interface.websocket_manager.pause_workflow",
            lambda wf_id: {"status": "success"},
        )

        class MockWS:
            pass

        async def run():
            response = await handler.handle("wf_1", MockWS(), "pause", {}, "corr_1")
            assert response["status"] == "accepted"
            # Ack payload should NOT claim transition is done — only forwarded
            assert "Forward" in response["payload"]["note"] or "arrives via events" in response["payload"]["note"]
            assert "completed" not in response["payload"]["note"].lower()

        asyncio.run(run())
