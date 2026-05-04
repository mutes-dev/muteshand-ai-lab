"""
Phase 2B — Background Execution Manager Validation

Tests:
1. Non-blocking execution (start returns immediately)
2. Multiple workflows concurrently
3. State transitions (QUEUED → ACTIVE → COMPLETED)
4. Execution correctness vs synchronous baseline
5. Error handling (FAILED state)
6. Status query and listing
7. Wait-for-completion
8. Thread safety under concurrent starts

All tests use real BackgroundManager with mock workflow functions.
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from system.runtime.background_manager import BackgroundManager


# ============================================================
# HELPERS
# ============================================================

def _fast_workflow(input_val):
    """Simulates a fast successful workflow."""
    return {"status": "success", "result": f"processed_{input_val}"}


def _slow_workflow(input_val, duration=0.3):
    """Simulates a slow successful workflow."""
    time.sleep(duration)
    return {"status": "success", "result": f"slow_{input_val}"}


def _failing_workflow(input_val):
    """Simulates a workflow that raises an exception."""
    raise RuntimeError(f"workflow_crashed: {input_val}")


def _blocking_workflow(event):
    """Workflow that blocks until event is set."""
    event.wait(timeout=10)
    return {"status": "success", "result": "unblocked"}


# ============================================================
# TEST 1 — NON-BLOCKING EXECUTION
# ============================================================

class TestNonBlocking:
    """Verify start_workflow returns immediately (non-blocking)."""

    def test_start_returns_immediately(self):
        mgr = BackgroundManager()
        event = threading.Event()

        start = time.monotonic()
        workflow_id = mgr.start_workflow(_blocking_workflow, event)
        elapsed = time.monotonic() - start

        print(f"\n=== TEST 1 — NON-BLOCKING ===")
        print(f"  workflow_id={workflow_id}")
        print(f"  elapsed={elapsed:.4f}s")

        assert workflow_id is not None
        assert elapsed < 0.1, f"FAIL: start_workflow took {elapsed:.4f}s — should be instant"

        # Unblock and cleanup
        event.set()
        mgr.wait_for(workflow_id, timeout=5)

        print("  ✓ start_workflow returns immediately — PASS")

    def test_cli_remains_responsive(self):
        mgr = BackgroundManager()
        event = threading.Event()

        wf_id = mgr.start_workflow(_blocking_workflow, event)

        # Simulate user checking status while workflow runs
        status = mgr.get_status(wf_id)
        assert status is not None
        assert status["status"] in ("QUEUED", "ACTIVE")

        print(f"\n=== TEST 1B — CLI RESPONSIVE ===")
        print(f"  status during execution: {status['status']}")

        event.set()
        mgr.wait_for(wf_id, timeout=5)

        print("  ✓ Status queryable during execution — PASS")


# ============================================================
# TEST 2 — MULTIPLE CONCURRENT WORKFLOWS
# ============================================================

class TestConcurrentWorkflows:
    """Verify multiple workflows can run concurrently."""

    def test_two_concurrent_workflows(self):
        mgr = BackgroundManager()

        wf1 = mgr.start_workflow(_slow_workflow, "task_a", duration=0.2)
        wf2 = mgr.start_workflow(_slow_workflow, "task_b", duration=0.2)

        assert wf1 != wf2, "FAIL: duplicate workflow IDs"

        # Both should be active
        time.sleep(0.05)
        assert mgr.active_count() >= 1

        # Wait for both
        r1 = mgr.wait_for(wf1, timeout=5)
        r2 = mgr.wait_for(wf2, timeout=5)

        print(f"\n=== TEST 2 — CONCURRENT WORKFLOWS ===")
        print(f"  wf1: {r1['status']} — {r1['result']}")
        print(f"  wf2: {r2['status']} — {r2['result']}")

        assert r1["status"] == "COMPLETED"
        assert r2["status"] == "COMPLETED"
        assert r1["result"]["result"] == "slow_task_a"
        assert r2["result"]["result"] == "slow_task_b"

        print("  ✓ Two concurrent workflows completed — PASS")

    def test_five_concurrent_workflows(self):
        mgr = BackgroundManager()

        ids = []
        for i in range(5):
            wf_id = mgr.start_workflow(_fast_workflow, f"task_{i}")
            ids.append(wf_id)

        # Wait for all
        results = []
        for wf_id in ids:
            r = mgr.wait_for(wf_id, timeout=5)
            results.append(r)

        print(f"\n=== TEST 2B — FIVE CONCURRENT ===")
        for r in results:
            print(f"  {r['workflow_id'][:8]}... {r['status']}")

        assert all(r["status"] == "COMPLETED" for r in results)
        assert len(set(r["workflow_id"] for r in results)) == 5  # unique IDs

        print("  ✓ Five concurrent workflows all completed — PASS")


# ============================================================
# TEST 3 — STATE TRANSITIONS
# ============================================================

class TestStateTransitions:
    """Verify QUEUED → ACTIVE → COMPLETED lifecycle."""

    def test_queued_to_completed(self):
        mgr = BackgroundManager()
        event = threading.Event()

        wf_id = mgr.start_workflow(_blocking_workflow, event)

        # Check initial state (may be QUEUED or ACTIVE depending on timing)
        status_before = mgr.get_status(wf_id)
        assert status_before["status"] in ("QUEUED", "ACTIVE")

        print(f"\n=== TEST 3 — STATE TRANSITIONS ===")
        print(f"  initial: {status_before['status']}")

        # Let it run
        event.set()
        result = mgr.wait_for(wf_id, timeout=5)

        print(f"  final: {result['status']}")

        assert result["status"] == "COMPLETED"
        assert result["completed_at"] is not None
        assert result["result"]["result"] == "unblocked"

        print("  ✓ QUEUED/ACTIVE → COMPLETED — PASS")

    def test_failed_state_on_exception(self):
        mgr = BackgroundManager()

        wf_id = mgr.start_workflow(_failing_workflow, "crash_test")
        result = mgr.wait_for(wf_id, timeout=5)

        print(f"\n=== TEST 3B — FAILED STATE ===")
        print(f"  status: {result['status']}")
        print(f"  error: {result['error']}")

        assert result["status"] == "FAILED"
        assert "workflow_crashed" in result["error"]
        assert result["result"] is None

        print("  ✓ Exception → FAILED state — PASS")


# ============================================================
# TEST 4 — EXECUTION CORRECTNESS
# ============================================================

class TestExecutionCorrectness:
    """Verify background execution produces same result as synchronous."""

    def test_result_matches_synchronous(self):
        mgr = BackgroundManager()

        # Synchronous
        sync_result = _fast_workflow("test_input")

        # Background
        wf_id = mgr.start_workflow(_fast_workflow, "test_input")
        bg_result = mgr.wait_for(wf_id, timeout=5)

        print(f"\n=== TEST 4 — CORRECTNESS ===")
        print(f"  sync: {sync_result}")
        print(f"  bg:   {bg_result['result']}")

        assert bg_result["result"] == sync_result

        print("  ✓ Background result matches synchronous — PASS")


# ============================================================
# TEST 5 — STATUS QUERY & LISTING
# ============================================================

class TestStatusQuery:
    """Verify status query and workflow listing."""

    def test_get_status_existing(self):
        mgr = BackgroundManager()
        wf_id = mgr.start_workflow(_fast_workflow, "q1")
        mgr.wait_for(wf_id, timeout=5)

        status = mgr.get_status(wf_id)

        print(f"\n=== TEST 5A — GET STATUS ===")
        print(f"  {status}")

        assert status is not None
        assert status["workflow_id"] == wf_id
        assert status["status"] == "COMPLETED"
        assert "thread" not in status  # Thread excluded from output

        print("  ✓ get_status returns correct data — PASS")

    def test_get_status_nonexistent(self):
        mgr = BackgroundManager()
        status = mgr.get_status("nonexistent-id")

        print(f"\n=== TEST 5B — NONEXISTENT ===")
        assert status is None
        print("  ✓ get_status returns None for unknown ID — PASS")

    def test_list_workflows(self):
        mgr = BackgroundManager()

        mgr.start_workflow(_fast_workflow, "a")
        mgr.start_workflow(_fast_workflow, "b")
        time.sleep(0.1)  # Let them complete

        wf_list = mgr.list_workflows()

        print(f"\n=== TEST 5C — LIST WORKFLOWS ===")
        for wf in wf_list:
            print(f"  {wf['workflow_id'][:8]}... {wf['status']}")

        assert len(wf_list) == 2
        assert all("thread" not in wf for wf in wf_list)

        print("  ✓ list_workflows returns all tracked — PASS")

    def test_is_active(self):
        mgr = BackgroundManager()
        event = threading.Event()

        wf_id = mgr.start_workflow(_blocking_workflow, event)
        time.sleep(0.05)

        assert mgr.is_active(wf_id) is True

        event.set()
        mgr.wait_for(wf_id, timeout=5)

        assert mgr.is_active(wf_id) is False

        print(f"\n=== TEST 5D — IS_ACTIVE ===")
        print("  ✓ is_active tracks lifecycle — PASS")


# ============================================================
# TEST 6 — WAIT FOR COMPLETION
# ============================================================

class TestWaitFor:
    """Verify wait_for blocks until completion."""

    def test_wait_returns_completed(self):
        mgr = BackgroundManager()

        wf_id = mgr.start_workflow(_slow_workflow, "wait_test", duration=0.1)
        result = mgr.wait_for(wf_id, timeout=5)

        print(f"\n=== TEST 6A — WAIT FOR ===")
        print(f"  result: {result['status']}")

        assert result["status"] == "COMPLETED"
        print("  ✓ wait_for returns after completion — PASS")

    def test_wait_nonexistent(self):
        mgr = BackgroundManager()
        result = mgr.wait_for("fake-id", timeout=1)

        print(f"\n=== TEST 6B — WAIT NONEXISTENT ===")
        assert result is None
        print("  ✓ wait_for returns None for unknown — PASS")


# ============================================================
# TEST 7 — THREAD SAFETY
# ============================================================

class TestThreadSafety:
    """Verify concurrent starts don't corrupt internal state."""

    def test_concurrent_starts(self):
        mgr = BackgroundManager()
        ids = []
        errors = []

        def start_one(idx):
            try:
                wf_id = mgr.start_workflow(_fast_workflow, f"ts_{idx}")
                ids.append(wf_id)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=start_one, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        print(f"\n=== TEST 7 — THREAD SAFETY ===")
        print(f"  started: {len(ids)}")
        print(f"  errors: {len(errors)}")

        assert len(errors) == 0, f"FAIL: Errors during concurrent starts: {errors}"
        assert len(ids) == 10
        assert len(set(ids)) == 10  # All unique

        # Wait for all
        for wf_id in ids:
            mgr.wait_for(wf_id, timeout=5)

        all_statuses = [mgr.get_status(wid)["status"] for wid in ids]
        assert all(s == "COMPLETED" for s in all_statuses)

        print("  ✓ 10 concurrent starts — no corruption — PASS")


# ============================================================
# TEST 8 — WRAPPER INTEGRITY
# ============================================================

class TestWrapperIntegrity:
    """Verify BackgroundManager doesn't modify the wrapped function."""

    def test_function_receives_correct_args(self):
        mgr = BackgroundManager()
        received = {}

        def capture_fn(*args, **kwargs):
            received["args"] = args
            received["kwargs"] = kwargs
            return {"status": "success"}

        wf_id = mgr.start_workflow(capture_fn, "arg1", "arg2", key="val")
        mgr.wait_for(wf_id, timeout=5)

        print(f"\n=== TEST 8 — WRAPPER INTEGRITY ===")
        print(f"  args: {received['args']}")
        print(f"  kwargs: {received['kwargs']}")

        assert received["args"] == ("arg1", "arg2")
        assert received["kwargs"] == {"key": "val"}

        print("  ✓ Arguments passed through unchanged — PASS")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
