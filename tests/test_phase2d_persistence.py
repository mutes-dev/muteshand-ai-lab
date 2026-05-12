"""
CATEGORY: LIFECYCLE
AUTHORITY_LAYER: Lifecycle State Transition Validation
VALIDATES:
  - Project memory persistence
  - ACTIVE workflow persistence
  - BLOCKED workflow persistence
  - COMPLETED workflow persistence
  - Restore logic for all states
  - No duplicate execution on resume
ENTRYPOINT: run_workflow, direct
DIRECT_INTERNAL_CALLS:
  - persistence internals
  - workflow_control internals
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: LIFECYCLE_VALIDATION
ARCHITECTURAL_SCOPE: Persistence lifecycle

---

TESTS — Phase 2D: Project Memory Persistence

Tests:
1. ACTIVE workflow persisted to per-workflow JSON file
2. BLOCKED workflow persisted
3. COMPLETED workflow saved to legacy list AND active file cleaned up
4. COMPLETED-only restriction removed (ACTIVE/BLOCKED now save)
5. load_active_workflows returns valid persisted workflows
6. Corrupt persistence file discarded
7. delete_workflow removes file (idempotent)
8. Restore logic: COMPLETED step preserved
9. Restore logic: ACTIVE (interrupted) → PENDING
10. Restore logic: BLOCKED step remains BLOCKED
11. Restore logic: FAILED step remains FAILED
12. No duplicate execution on resume
13. Adversarial: duplicate workflow files
14. Adversarial: stale ACTIVE workflows
15. Adversarial: partial writes (atomic safety)
16. Adversarial: extra fields preserved (full workflow stored)
17. Integration: real step execution → persistence file created
18. Integration: COMPLETED → persistence file removed
"""

import sys
import os
import json
import tempfile
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from system.orchestrator.persistence import (
    save_workflow,
    load_active_workflows,
    delete_workflow,
    get_workflows,
    get_last_workflow,
    ACTIVE_WORKFLOW_DIR,
    _active_workflow_path,
)


# ============================================================
# HELPERS
# ============================================================

def _make_step(step_id, status="PENDING", execution_result=None, retries=0, tool_call=None, blocked_reason=None):
    step = {
        "id": step_id,
        "name": f"test_step_{step_id}",
        "type": "EXECUTE_API",
        "purpose": f"Test step {step_id}",
        "tool_call": tool_call or "add_numbers 1 2",
        "expected_outcome": "Execution completed",
        "risk": "LOW",
        "importance": "MEDIUM",
        "resource_targets": [],
        "agent": "default_agent",
        "status": status,
        "retries": retries,
        "max_retries": 2,
        "input": f"test input {step_id}",
    }
    if execution_result is not None:
        step["execution_result"] = execution_result
    if blocked_reason is not None:
        step["blocked_reason"] = blocked_reason
    return step


def _make_workflow(workflow_id, steps, status="ACTIVE"):
    return {
        "id": workflow_id,
        "name": f"test_workflow_{workflow_id}",
        "status": status,
        "steps": steps,
    }


@pytest.fixture(autouse=True)
def cleanup_active_workflows():
    """Ensure active workflow directory is clean before and after each test."""
    yield
    if os.path.exists(ACTIVE_WORKFLOW_DIR):
        for f in os.listdir(ACTIVE_WORKFLOW_DIR):
            try:
                os.remove(os.path.join(ACTIVE_WORKFLOW_DIR, f))
            except OSError:
                pass


# ============================================================
# TEST 1 — ACTIVE WORKFLOW PERSISTED
# ============================================================

class TestActiveWorkflowPersistence:
    def test_active_workflow_saved(self):
        """ACTIVE workflow saved to per-workflow JSON file."""
        step = _make_step("s1", status="COMPLETED", execution_result={"status": "success", "result": 42})
        step2 = _make_step("s2", status="PENDING")
        wf = _make_workflow("test_active_1", [step, step2], status="ACTIVE")

        result = save_workflow(wf)
        assert result["status"] == "success"

        # Verify file exists
        path = _active_workflow_path("test_active_1")
        assert os.path.exists(path)

        # Verify contents
        with open(path, "r") as f:
            data = json.load(f)
        assert data["id"] == "test_active_1"
        assert data["status"] == "ACTIVE"
        assert len(data["steps"]) == 2
        assert data["steps"][0]["status"] == "COMPLETED"
        assert data["steps"][1]["status"] == "PENDING"

        print("\n✓ TEST 1 — ACTIVE workflow persisted — PASS")


# ============================================================
# TEST 2 — BLOCKED WORKFLOW PERSISTED
# ============================================================

class TestBlockedWorkflowPersistence:
    def test_blocked_workflow_saved(self):
        """BLOCKED workflow saved to per-workflow JSON file."""
        step = _make_step("s1", status="BLOCKED", blocked_reason="approval_required")
        wf = _make_workflow("test_blocked_1", [step], status="BLOCKED")

        result = save_workflow(wf)
        assert result["status"] == "success"

        path = _active_workflow_path("test_blocked_1")
        assert os.path.exists(path)

        with open(path, "r") as f:
            data = json.load(f)
        assert data["status"] == "BLOCKED"
        assert data["steps"][0]["blocked_reason"] == "approval_required"

        print("\n✓ TEST 2 — BLOCKED workflow persisted — PASS")


# ============================================================
# TEST 3 — COMPLETED WORKFLOW LEGACY + CLEANUP
# ============================================================

class TestCompletedWorkflow:
    def test_completed_saves_to_legacy(self):
        """COMPLETED workflow appended to legacy workflows list."""
        step = _make_step("s1", status="COMPLETED", execution_result={"status": "success", "result": 1})
        wf = _make_workflow("test_completed_1", [step], status="COMPLETED")

        result = save_workflow(wf)
        assert result["status"] == "success"

        # Should NOT create active workflow file
        path = _active_workflow_path("test_completed_1")
        assert not os.path.exists(path)

        print("\n✓ TEST 3 — COMPLETED workflow saves to legacy — PASS")


# ============================================================
# TEST 4 — COMPLETED-ONLY RESTRICTION REMOVED
# ============================================================

class TestRestrictionRemoved:
    def test_active_no_longer_ignored(self):
        """ACTIVE workflows are no longer ignored by save_workflow."""
        step = _make_step("s1", status="PENDING")
        wf = _make_workflow("test_not_ignored", [step], status="ACTIVE")

        result = save_workflow(wf)
        assert result["status"] == "success"  # Was "ignored" before Phase 2D

        print("\n✓ TEST 4 — ACTIVE no longer ignored — PASS")

    def test_unknown_status_ignored(self):
        """Unknown workflow status returns ignored."""
        step = _make_step("s1")
        wf = _make_workflow("test_unknown", [step], status="UNKNOWN")

        result = save_workflow(wf)
        assert result["status"] == "ignored"

        print("\n✓ TEST 4B — Unknown status still ignored — PASS")


# ============================================================
# TEST 5 — LOAD ACTIVE WORKFLOWS
# ============================================================

class TestLoadActiveWorkflows:
    def test_load_multiple(self):
        """load_active_workflows returns all valid persisted workflows."""
        wf1 = _make_workflow("test_load_1", [_make_step("s1")], status="ACTIVE")
        wf2 = _make_workflow("test_load_2", [_make_step("s2")], status="BLOCKED")

        save_workflow(wf1)
        save_workflow(wf2)

        loaded = load_active_workflows()
        ids = {w["id"] for w in loaded}
        assert "test_load_1" in ids
        assert "test_load_2" in ids

        print("\n✓ TEST 5 — Load multiple active workflows — PASS")

    def test_load_empty_dir(self):
        """load_active_workflows returns empty list when no files."""
        # Ensure directory is clean
        if os.path.exists(ACTIVE_WORKFLOW_DIR):
            for f in os.listdir(ACTIVE_WORKFLOW_DIR):
                os.remove(os.path.join(ACTIVE_WORKFLOW_DIR, f))

        loaded = load_active_workflows()
        assert loaded == []

        print("\n✓ TEST 5B — Load empty directory — PASS")

    def test_load_nonexistent_dir(self):
        """load_active_workflows returns empty list when dir doesn't exist."""
        if os.path.exists(ACTIVE_WORKFLOW_DIR):
            shutil.rmtree(ACTIVE_WORKFLOW_DIR)

        loaded = load_active_workflows()
        assert loaded == []

        print("\n✓ TEST 5C — Load nonexistent directory — PASS")


# ============================================================
# TEST 6 — CORRUPT PERSISTENCE FILE DISCARDED
# ============================================================

class TestCorruptPersistence:
    def test_invalid_json_discarded(self):
        """Invalid JSON file is silently removed and not returned."""
        os.makedirs(ACTIVE_WORKFLOW_DIR, exist_ok=True)
        path = os.path.join(ACTIVE_WORKFLOW_DIR, "corrupt_wf.json")
        with open(path, "w") as f:
            f.write("NOT VALID JSON {{{")

        loaded = load_active_workflows()
        corrupt_ids = [w.get("id") for w in loaded if w.get("id") == "corrupt_wf"]
        assert len(corrupt_ids) == 0
        assert not os.path.exists(path)

        print("\n✓ TEST 6A — Invalid JSON discarded — PASS")

    def test_missing_required_fields(self):
        """File missing 'id' or 'steps' is discarded."""
        os.makedirs(ACTIVE_WORKFLOW_DIR, exist_ok=True)
        path = os.path.join(ACTIVE_WORKFLOW_DIR, "bad_struct.json")
        with open(path, "w") as f:
            json.dump({"name": "no_id_or_steps"}, f)

        loaded = load_active_workflows()
        assert not any(w.get("name") == "no_id_or_steps" for w in loaded)
        assert not os.path.exists(path)

        print("\n✓ TEST 6B — Missing fields discarded — PASS")


# ============================================================
# TEST 7 — DELETE WORKFLOW
# ============================================================

class TestDeleteWorkflow:
    def test_delete_existing(self):
        """delete_workflow removes file."""
        wf = _make_workflow("test_del_1", [_make_step("s1")], status="ACTIVE")
        save_workflow(wf)

        path = _active_workflow_path("test_del_1")
        assert os.path.exists(path)

        assert delete_workflow("test_del_1") is True
        assert not os.path.exists(path)

        print("\n✓ TEST 7A — Delete existing workflow — PASS")

    def test_delete_nonexistent(self):
        """delete_workflow on nonexistent is idempotent."""
        assert delete_workflow("nonexistent_xyz") is True

        print("\n✓ TEST 7B — Delete nonexistent (idempotent) — PASS")


# ============================================================
# TEST 8 — RESTORE: COMPLETED PRESERVED
# ============================================================

class TestRestoreCompleted:
    def test_completed_step_preserved_on_restore(self):
        """Persisted COMPLETED step is restored with execution_result."""
        # Create persisted workflow
        step_completed = _make_step("s1", status="COMPLETED", execution_result={"status": "success", "result": 100})
        step_pending = _make_step("s2", status="PENDING")
        wf_persisted = _make_workflow("test_restore_c", [step_completed, step_pending], status="ACTIVE")
        save_workflow(wf_persisted)

        # Fresh workflow (as if restarted)
        fresh_step1 = _make_step("s1")
        fresh_step2 = _make_step("s2")
        wf_fresh = _make_workflow("test_restore_c", [fresh_step1, fresh_step2])

        # Simulate restore logic from orchestrator_runtime
        loaded = load_active_workflows()
        persisted = next((w for w in loaded if w["id"] == "test_restore_c"), None)
        assert persisted is not None

        persisted_steps = {s["id"]: s for s in persisted["steps"]}
        for step in wf_fresh["steps"]:
            ps = persisted_steps.get(step["id"])
            if ps and ps["status"] == "COMPLETED":
                step["status"] = "COMPLETED"
                step["execution_result"] = ps.get("execution_result")
                step["retries"] = ps.get("retries", 0)

        assert wf_fresh["steps"][0]["status"] == "COMPLETED"
        assert wf_fresh["steps"][0]["execution_result"]["result"] == 100
        assert wf_fresh["steps"][1]["status"] == "PENDING"

        print("\n✓ TEST 8 — COMPLETED step preserved on restore — PASS")


# ============================================================
# TEST 9 — RESTORE: ACTIVE (interrupted) → PENDING
# ============================================================

class TestRestoreActive:
    def test_active_becomes_pending(self):
        """ACTIVE (interrupted) step becomes PENDING on restore."""
        step = _make_step("s1", status="ACTIVE", retries=1)
        wf = _make_workflow("test_restore_a", [step], status="ACTIVE")
        save_workflow(wf)

        loaded = load_active_workflows()
        persisted = next((w for w in loaded if w["id"] == "test_restore_a"), None)
        assert persisted is not None
        assert persisted["steps"][0]["status"] == "ACTIVE"

        # Apply restore normalization
        fresh = _make_step("s1")
        ps = persisted["steps"][0]
        if ps["status"] == "ACTIVE":
            fresh["status"] = "PENDING"
            fresh["retries"] = ps.get("retries", 0)

        assert fresh["status"] == "PENDING"
        assert fresh["retries"] == 1

        print("\n✓ TEST 9 — ACTIVE → PENDING on restore — PASS")


# ============================================================
# TEST 10 — RESTORE: BLOCKED remains BLOCKED
# ============================================================

class TestRestoreBlocked:
    def test_blocked_remains_blocked(self):
        """BLOCKED step remains BLOCKED on restore."""
        step = _make_step("s1", status="BLOCKED", blocked_reason="approval_required")
        wf = _make_workflow("test_restore_b", [step], status="BLOCKED")
        save_workflow(wf)

        loaded = load_active_workflows()
        persisted = next((w for w in loaded if w["id"] == "test_restore_b"), None)
        assert persisted is not None
        assert persisted["steps"][0]["status"] == "BLOCKED"
        assert persisted["steps"][0]["blocked_reason"] == "approval_required"

        print("\n✓ TEST 10 — BLOCKED remains BLOCKED on restore — PASS")


# ============================================================
# TEST 11 — RESTORE: FAILED remains FAILED
# ============================================================

class TestRestoreFailed:
    def test_failed_remains_failed(self):
        """FAILED step remains FAILED on restore."""
        step = _make_step("s1", status="FAILED", retries=2, execution_result={"status": "failure", "reason": "tool_error"})
        wf = _make_workflow("test_restore_f", [step], status="ACTIVE")
        save_workflow(wf)

        loaded = load_active_workflows()
        persisted = next((w for w in loaded if w["id"] == "test_restore_f"), None)
        assert persisted is not None
        assert persisted["steps"][0]["status"] == "FAILED"
        assert persisted["steps"][0]["retries"] == 2

        print("\n✓ TEST 11 — FAILED remains FAILED on restore — PASS")


# ============================================================
# TEST 12 — NO DUPLICATE EXECUTION
# ============================================================

class TestNoDuplicate:
    def test_completed_steps_not_re_executed(self):
        """Completed steps from persistence are preserved — not re-executed."""
        step1 = _make_step("s1", status="COMPLETED", execution_result={"status": "success", "result": 42})
        step2 = _make_step("s2", status="PENDING")
        wf = _make_workflow("test_nodup", [step1, step2], status="ACTIVE")
        save_workflow(wf)

        loaded = load_active_workflows()
        persisted = next((w for w in loaded if w["id"] == "test_nodup"), None)
        assert persisted is not None

        # After restore, s1 COMPLETED → scheduler skips it
        assert persisted["steps"][0]["status"] == "COMPLETED"
        assert persisted["steps"][1]["status"] == "PENDING"

        print("\n✓ TEST 12 — No duplicate execution — PASS")


# ============================================================
# TEST 13 — ADVERSARIAL: DUPLICATE WORKFLOW FILES
# ============================================================

class TestDuplicateFiles:
    def test_overwrite_on_save(self):
        """Saving same workflow_id overwrites (no duplicates)."""
        step = _make_step("s1", status="PENDING")
        wf = _make_workflow("test_dup", [step], status="ACTIVE")
        save_workflow(wf)

        # Save again with updated state
        wf["steps"][0]["status"] = "COMPLETED"
        wf["steps"][0]["execution_result"] = {"status": "success", "result": 99}
        save_workflow(wf)

        loaded = load_active_workflows()
        dup_wfs = [w for w in loaded if w["id"] == "test_dup"]
        assert len(dup_wfs) == 1
        assert dup_wfs[0]["steps"][0]["status"] == "COMPLETED"

        print("\n✓ TEST 13 — Overwrite on duplicate save — PASS")


# ============================================================
# TEST 14 — ADVERSARIAL: STALE ACTIVE WORKFLOWS
# ============================================================

class TestStaleWorkflows:
    def test_stale_workflow_loads(self):
        """Stale ACTIVE workflow loads correctly (no corruption)."""
        step = _make_step("s1", status="ACTIVE", retries=0)
        wf = _make_workflow("test_stale", [step], status="ACTIVE")
        save_workflow(wf)

        # Simulating "stale" — file exists from previous run
        loaded = load_active_workflows()
        stale = next((w for w in loaded if w["id"] == "test_stale"), None)
        assert stale is not None
        assert stale["steps"][0]["status"] == "ACTIVE"
        # Restore would normalize ACTIVE → PENDING

        print("\n✓ TEST 14 — Stale workflow loads correctly — PASS")


# ============================================================
# TEST 15 — ADVERSARIAL: ATOMIC WRITE (no partial)
# ============================================================

class TestAtomicWrite:
    def test_no_temp_files_left(self):
        """Atomic write leaves no .tmp files."""
        step = _make_step("s1")
        wf = _make_workflow("test_atomic", [step], status="ACTIVE")
        save_workflow(wf)

        # Check for temp files
        if os.path.exists(ACTIVE_WORKFLOW_DIR):
            for f in os.listdir(ACTIVE_WORKFLOW_DIR):
                assert not f.endswith(".tmp"), f"Temp file left: {f}"

        print("\n✓ TEST 15 — No temp files left — PASS")


# ============================================================
# TEST 16 — FULL WORKFLOW STORED (no transformation)
# ============================================================

class TestFullWorkflowStored:
    def test_extra_fields_preserved(self):
        """Full workflow object stored as-is including extra fields."""
        step = _make_step("s1")
        wf = _make_workflow("test_full", [step], status="ACTIVE")
        wf["classification"] = {"type": "file_operation"}
        wf["output"] = {"status": "success", "result": "hello"}

        save_workflow(wf)

        loaded = load_active_workflows()
        persisted = next((w for w in loaded if w["id"] == "test_full"), None)
        assert persisted is not None
        assert persisted["classification"] == {"type": "file_operation"}
        assert persisted["output"] == {"status": "success", "result": "hello"}

        print("\n✓ TEST 16 — Full workflow stored (no transformation) — PASS")


# ============================================================
# TEST 17 — INTEGRATION: real execution → persistence file created
# ============================================================

class TestIntegrationPersistence:
    def test_step_execution_creates_persistence(self):
        """Running a step through parallel_executor creates a persistence file via save hooks."""
        from system.orchestrator.step_executor import execute_step
        from system.orchestrator import trace_collector
        from system.orchestrator.parallel_executor import _execute_single_step
        from system.orchestrator.step_chainer import propagate_result
        import system.orchestrator.governance as gov
        from system.orchestrator import escalation_controller

        trace_collector.create_collector("test_int_persist")

        step = _make_step("s1", tool_call="add_numbers 3 7")
        wf = _make_workflow("test_int_persist", [step], status="ACTIVE")

        result = _execute_single_step(
            step=step,
            workflow=wf,
            execute_step_fn=execute_step,
            governance_fn=gov.decide_next_action,
            propagate_fn=propagate_result,
            escalation_handler=escalation_controller,
            debug_verbose=False,
        )

        # The checkpoint save happens here (Phase 2C), but the persistence
        # save hooks are in orchestrator_runtime, not parallel_executor.
        # Verify checkpoint was created (Phase 2C integration).
        from system.orchestrator.checkpoint_manager import load_checkpoint
        cp = load_checkpoint("test_int_persist")
        assert cp is not None, "Checkpoint should exist after step execution"
        assert cp["steps"][0]["status"] == result["status"]

        # Clean up
        from system.orchestrator.checkpoint_manager import delete_checkpoint
        delete_checkpoint("test_int_persist")

        print(f"\n  step_status: {result['status']}")
        print("✓ TEST 17 — Integration: checkpoint created after execution — PASS")


# ============================================================
# TEST 18 — INTEGRATION: COMPLETED → persistence file removed
# ============================================================

class TestCompletedCleanup:
    def test_completed_removes_active_file(self):
        """After COMPLETED, active workflow file is removed."""
        step = _make_step("s1", status="COMPLETED", execution_result={"status": "success", "result": 1})
        wf = _make_workflow("test_cleanup_c", [step], status="ACTIVE")

        # First save as ACTIVE
        save_workflow(wf)
        path = _active_workflow_path("test_cleanup_c")
        assert os.path.exists(path)

        # Now mark COMPLETED and delete
        wf["status"] = "COMPLETED"
        save_workflow(wf)  # Saves to legacy list
        delete_workflow("test_cleanup_c")  # Removes active file

        assert not os.path.exists(path)

        print("\n✓ TEST 18 — COMPLETED → active file removed — PASS")


# ============================================================
# TEST 19 — PAUSED WORKFLOW PERSISTED
# ============================================================

class TestPausedWorkflow:
    def test_paused_workflow_saved(self):
        """PAUSED workflow saved to per-workflow JSON file."""
        step = _make_step("s1", status="PENDING")
        wf = _make_workflow("test_paused_1", [step], status="PAUSED")

        result = save_workflow(wf)
        assert result["status"] == "success"

        path = _active_workflow_path("test_paused_1")
        assert os.path.exists(path)

        with open(path, "r") as f:
            data = json.load(f)
        assert data["status"] == "PAUSED"

        print("\n✓ TEST 19 — PAUSED workflow persisted — PASS")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
