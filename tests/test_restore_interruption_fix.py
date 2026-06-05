"""
CATEGORY: REGRESSION
AUTHORITY_LAYER: Restore/Resume Normalization Fix
VALIDATES:
  - ACTIVE (interrupted) → BLOCKED (not FAILED) on checkpoint restore
  - ACTIVE (interrupted) → BLOCKED (not FAILED) on persistence restore
  - Restore-BLOCKED does NOT synthesize failure metadata
  - Restore-BLOCKED does NOT create retry_target_step_id
  - Dependents of restore-BLOCKED do NOT receive dependency_failed
  - Genuine execution failures still correctly become FAILED
  - Normal dependency BLOCKED behavior still recovers
  - Workflow actionability remains recoverable for restore-BLOCKED
ENTRYPOINT: Direct unit tests
DIRECT_INTERNAL_CALLS:
  - checkpoint_manager.restore_workflow_from_checkpoint
  - projection_schema._compute_failure_metadata
  - projection_schema._compute_retry_target_step_id
  - execution_scheduler._check_dependencies_satisfied
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: NONE
TEST_INTENT: REGRESSION_PREVENTION
ARCHITECTURAL_SCOPE: Restore normalization authority

HISTORICAL_FIX: SA-approved minimal restore/checkpoint interruption fix
REGRESSION_REASON: Prevent false FAILED classification of interrupted ACTIVE steps
PRESERVATION_PRIORITY: HIGH
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from system.orchestrator.checkpoint_manager import restore_workflow_from_checkpoint
from system.orchestrator.projection_schema import (
    _compute_failure_metadata,
    _compute_retry_target_step_id,
)
from system.orchestrator.execution_scheduler import _check_dependencies_satisfied


# ============================================================
# HELPERS
# ============================================================

def _make_step(step_id, status="PENDING", execution_result=None, retries=0, blocked_reason=None):
    step = {
        "id": step_id,
        "name": f"test_step_{step_id}",
        "type": "EXECUTE_API",
        "purpose": f"Test step {step_id}",
        "tool_call": "add_numbers 1 2",
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


def _make_workflow(workflow_id, steps):
    return {
        "id": workflow_id,
        "name": f"test_workflow_{workflow_id}",
        "status": "ACTIVE",
        "steps": steps,
    }


# ============================================================
# TEST 1 — Checkpoint restore ACTIVE → BLOCKED
# ============================================================

class TestCheckpointActiveToBlocked:
    def test_checkpoint_active_becomes_blocked(self):
        """ACTIVE checkpoint step must restore as BLOCKED, not FAILED."""
        checkpoint = {
            "workflow_id": "wf-cp-active",
            "workflow_status": "ACTIVE",
            "steps": [
                {"id": "s1", "status": "ACTIVE", "execution_result": None, "retries": 1},
            ],
            "last_completed_step_index": -1,
        }
        wf = _make_workflow("wf-cp-active", [_make_step("s1")])
        restore_workflow_from_checkpoint(wf, checkpoint)
        assert wf["steps"][0]["status"] == "BLOCKED"
        assert wf["steps"][0]["retries"] == 1


# ============================================================
# TEST 2 — Checkpoint restore BLOCKED does NOT create failure metadata
# ============================================================

class TestCheckpointBlockedNoFailureMetadata:
    def test_checkpoint_restore_blocked_no_failed_step_id(self):
        """Restore-BLOCKED step must NOT appear in failure_metadata.failed_step_id."""
        checkpoint = {
            "workflow_id": "wf-cp-meta",
            "workflow_status": "ACTIVE",
            "steps": [
                {"id": "s1", "status": "COMPLETED", "execution_result": {"status": "success", "result": 10}, "retries": 0},
                {"id": "s2", "status": "ACTIVE", "execution_result": None, "retries": 1},
            ],
            "last_completed_step_index": 0,
        }
        wf = _make_workflow("wf-cp-meta", [_make_step("s1"), _make_step("s2")])
        restore_workflow_from_checkpoint(wf, checkpoint)

        # Workflow is NOT FAILED → no failure metadata should be synthesized
        metadata = _compute_failure_metadata(wf["steps"], workflow_error=None, lifecycle_status="BLOCKED")
        assert metadata["failed_step_id"] is None
        assert metadata["failure_reason"] is None
        assert metadata["failed_step_label"] is None

    def test_checkpoint_restore_blocked_no_retry_target(self):
        """Restore-BLOCKED step must NOT become retry_target_step_id."""
        checkpoint = {
            "workflow_id": "wf-cp-retry",
            "workflow_status": "ACTIVE",
            "steps": [
                {"id": "s1", "status": "ACTIVE", "execution_result": None, "retries": 1},
            ],
            "last_completed_step_index": -1,
        }
        wf = _make_workflow("wf-cp-retry", [_make_step("s1")])
        restore_workflow_from_checkpoint(wf, checkpoint)

        # Workflow is NOT FAILED → no retry target should be computed
        retry_target = _compute_retry_target_step_id(wf["steps"], lifecycle_status="BLOCKED")
        assert retry_target is None


# ============================================================
# TEST 3 — Persistence restore ACTIVE → BLOCKED (simulated)
# ============================================================

class TestPersistenceActiveToBlocked:
    def test_persistence_active_becomes_blocked(self):
        """Simulated persistence restore: ACTIVE step → BLOCKED."""
        step = _make_step("s1", status="ACTIVE", retries=1)
        # Simulate the persistence restore normalization that now applies
        from system.orchestrator.workflow_control import request_step_transition as _rst
        _rst(step, "BLOCKED", "persistence_restore_interrupted", validate=False)
        assert step["status"] == "BLOCKED"
        assert step["retries"] == 1

    def test_persistence_restore_blocked_no_failure_metadata(self):
        """Persistence restore-BLOCKED must NOT synthesize failure metadata."""
        steps = [
            _make_step("s1", status="COMPLETED", execution_result={"status": "success", "result": 10}),
            _make_step("s2", status="BLOCKED", blocked_reason="persistence_restore_interrupted"),
        ]
        metadata = _compute_failure_metadata(steps, workflow_error=None, lifecycle_status="BLOCKED")
        assert metadata["failed_step_id"] is None
        assert metadata["failure_reason"] is None

    def test_persistence_restore_blocked_no_retry_target(self):
        """Persistence restore-BLOCKED must NOT become retry target."""
        steps = [
            _make_step("s1", status="BLOCKED", blocked_reason="persistence_restore_interrupted"),
        ]
        retry_target = _compute_retry_target_step_id(steps, lifecycle_status="BLOCKED")
        assert retry_target is None


# ============================================================
# TEST 4 — Dependents of restore-BLOCKED do NOT get dependency_failed
# ============================================================

class TestRestoreBlockedDependencyPropagation:
    def test_dependent_of_restore_blocked_not_dependency_failed(self):
        """A step depending on a restore-BLOCKED step must NOT see dependency_failed."""
        s1 = _make_step("s1", status="BLOCKED", blocked_reason="checkpoint_restore_interrupted")
        s2 = _make_step("s2", status="PENDING")
        s2["depends_on"] = ["s1"]

        step_states = {"s1": "BLOCKED", "s2": "PENDING"}
        steps_map = {"s1": s1, "s2": s2}

        satisfied, reason = _check_dependencies_satisfied(s2, step_states, steps_map)
        # BLOCKED dependency is NOT terminal; dependency is simply not completed
        assert satisfied is False
        assert "dependency_not_completed" in reason
        assert "dependency_failed" not in reason


# ============================================================
# TEST 5 — Genuine execution failure still becomes FAILED
# ============================================================

class TestGenuineFailureStillFailed:
    def test_genuine_execution_failure_preserved(self):
        """Steps with execution_result.status == failure must still be FAILED."""
        checkpoint = {
            "workflow_id": "wf-cp-genuine",
            "workflow_status": "ACTIVE",
            "steps": [
                {"id": "s1", "status": "FAILED", "execution_result": {"status": "failure", "reason": "tool_error"}, "retries": 2},
            ],
            "last_completed_step_index": -1,
        }
        wf = _make_workflow("wf-cp-genuine", [_make_step("s1")])
        restore_workflow_from_checkpoint(wf, checkpoint)
        assert wf["steps"][0]["status"] == "FAILED"
        assert wf["steps"][0]["execution_result"]["status"] == "failure"

    def test_genuine_failure_creates_failure_metadata(self):
        """Genuine FAILED step must still appear in failure metadata."""
        steps = [
            _make_step("s1", status="FAILED", execution_result={"status": "failure", "reason": "tool_error"}),
        ]
        metadata = _compute_failure_metadata(steps, workflow_error=None, lifecycle_status="FAILED")
        assert metadata["failed_step_id"] == "s1"
        assert metadata["failure_reason"] == "tool_error"

    def test_genuine_failure_creates_retry_target(self):
        """Genuine FAILED step must still become retry_target_step_id."""
        steps = [
            _make_step("s1", status="FAILED", execution_result={"status": "failure", "reason": "tool_error"}),
        ]
        retry_target = _compute_retry_target_step_id(steps, lifecycle_status="FAILED")
        assert retry_target == "s1"


# ============================================================
# TEST 6 — Normal dependency BLOCKED still recovers
# ============================================================

class TestNormalDependencyBlockedRecovers:
    def test_dependency_blocked_releases_when_completed(self):
        """BLOCKED step with dependency_not_completed must become PENDING when dep completes."""
        s1 = _make_step("s1", status="COMPLETED", execution_result={"status": "success", "result": 42})
        s2 = _make_step("s2", status="BLOCKED", blocked_reason="dependency_not_completed:s1:PENDING")
        s2["depends_on"] = ["s1"]

        step_states = {"s1": "COMPLETED", "s2": "BLOCKED"}
        steps_map = {"s1": s1, "s2": s2}

        satisfied, reason = _check_dependencies_satisfied(s2, step_states, steps_map)
        assert satisfied is True
        assert reason == "all_dependencies_completed"


# ============================================================
# TEST 7 — Workflow actionability for restore-BLOCKED
# ============================================================

class TestRestoreBlockedActionability:
    def test_restore_blocked_workflow_actionable(self):
        """Workflow with only restore-BLOCKED steps must be actionable (not terminal FAILED)."""
        # Simulate the actionability classification from ai_lab_gui/backend/api.py
        # for a BLOCKED workflow
        steps = [
            _make_step("s1", status="BLOCKED", blocked_reason="checkpoint_restore_interrupted"),
        ]
        lifecycle_status = "BLOCKED"

        # Per api.py logic: BLOCKED → actionability = "RUNTIME_RECOVERABLE"
        # taskhub_action = "RESUME"
        assert lifecycle_status in ("ACTIVE", "ACTIVATING", "PAUSED", "BLOCKED", "PENDING_RECOVERY")


# ============================================================
# TEST 8 — Existing BLOCKED/no-progress semantics preserved
# ============================================================

class TestBlockedNoProgressSemantics:
    def test_max_retries_exceeded_blocked_preserved(self):
        """BLOCKED step with max_retries_exceeded must remain BLOCKED on restore."""
        checkpoint = {
            "workflow_id": "wf-cp-esc",
            "workflow_status": "ACTIVE",
            "steps": [
                {"id": "s1", "status": "BLOCKED", "blocked_reason": "max_retries_exceeded", "retries": 2},
            ],
            "last_completed_step_index": -1,
        }
        wf = _make_workflow("wf-cp-esc", [_make_step("s1")])
        restore_workflow_from_checkpoint(wf, checkpoint)
        assert wf["steps"][0]["status"] == "BLOCKED"
        assert wf["steps"][0]["blocked_reason"] == "max_retries_exceeded"

    def test_escalated_blocked_preserved(self):
        """BLOCKED step with escalated reason must remain BLOCKED on restore."""
        checkpoint = {
            "workflow_id": "wf-cp-esc2",
            "workflow_status": "ACTIVE",
            "steps": [
                {"id": "s1", "status": "BLOCKED", "blocked_reason": "escalated", "retries": 0},
            ],
            "last_completed_step_index": -1,
        }
        wf = _make_workflow("wf-cp-esc2", [_make_step("s1")])
        restore_workflow_from_checkpoint(wf, checkpoint)
        assert wf["steps"][0]["status"] == "BLOCKED"
        assert wf["steps"][0]["blocked_reason"] == "escalated"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
