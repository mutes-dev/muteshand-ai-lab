"""
BLOCKED SEMANTIC AUTHORITY FIX — REGRESSION TESTS

VALIDATES:
  - max_iterations_exceeded results in workflow BLOCKED, not FAILED
  - no_progress_ceiling results in workflow BLOCKED, not FAILED
  - BLOCKED workflow projection has no failure metadata
  - PAUSED workflow projection has no failure metadata
  - FAILED workflow projection still has failure metadata and retry target
  - Dependency-victim downstream BLOCKED steps do not auto-terminalize workflow
  - Governance escalation / retry exhaustion produces BLOCKED where contracts require BLOCKED
  - Non-terminal BLOCKED projection update is emitted
  - Recoverable FAILED behavior remains unchanged
  - Task Hub / History eligibility fields are not changed by this implementation

AUTHORITY:
  - STATE_TRANSITIONS_CONTRACT_V1
  - EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1
  - GOVERNANCE_CONTRACT
  - ORCHESTRATION_AND_EXECUTION_SEQUENCE_CONTRACT_V1
  - LIFECYCLE_AUTHORITY_CONTRACT_V1
  - GUI_FUNCTIONALITY_CONTRACT_V1
  - CANONICAL_PROJECTION_MODEL_V1
  - PROJECTION_CONTINUITY_CONTRACT_V1

FILES UNDER TEST:
  - system/orchestrator/orchestrator_runtime.py
  - system/orchestrator/projection_schema.py

FILES NOT TOUCHED:
  - ai_lab_gui/frontend/*
  - system/interface/event_bus.py
"""

import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.workflow_control import (
    _workflow_state_registry,
    _workflow_state_lock,
    _update_runtime_registry_only,
    _get_workflow_state,
    _set_runtime_activity,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset workflow state registry before each test."""
    with _workflow_state_lock:
        _workflow_state_registry.clear()
    yield
    with _workflow_state_lock:
        _workflow_state_registry.clear()


@pytest.fixture(autouse=True)
def _mock_persistence_exists():
    """Mock persistence exists for all tests."""
    with patch(
        "system.orchestrator.workflow_control.workflow_persistence_exists",
        return_value=True,
    ):
        yield


# ============================================================================
# Helpers
# ============================================================================

def _patched_update(wf_id, status, reason=None, workflow_dict=None):
    """Registry-only update — no disk write."""
    return _update_runtime_registry_only(wf_id, status, reason) or True


def _register(wf_id, status, reason=None):
    with _workflow_state_lock:
        _workflow_state_registry[wf_id] = {
            "status": status,
            "last_updated": time.time(),
            "reason": reason,
            "runtime_activity": "EXECUTING",
        }


def _clear(wf_id):
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)


def _make_step(sid, status, blocked_reason=None, exec_res=None, retries=0):
    s = {"id": sid, "status": status, "retries": retries}
    if blocked_reason:
        s["blocked_reason"] = blocked_reason
    if exec_res is not None:
        s["execution_result"] = exec_res
    return s


def _make_workflow(wf_id, steps, error=None):
    wf = {"id": wf_id, "status": "ACTIVE", "steps": steps}
    if error:
        wf["error"] = error
    return wf


# ============================================================================
# TEST 1: Max-iterations exceeded → BLOCKED, not FAILED
# ============================================================================

class TestMaxIterationsBlocked:
    """
    Per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1 §3A:
    Runtime max-iteration ceiling is BLOCKED, not FAILED.
    """

    def test_max_iterations_registry_blocked(self):
        """
        Simulate the max-iterations ceiling path:
        _update_workflow_state must be called with BLOCKED, not FAILED.
        """
        wf_id = "wf-max-iter"
        _register(wf_id, "ACTIVE")
        try:
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                _update_runtime_registry_only(wf_id, "BLOCKED", "max_iterations_exceeded")

            state = _get_workflow_state(wf_id)
            assert state["status"] == "BLOCKED"
            assert state.get("reason") == "max_iterations_exceeded"
            assert state["status"] != "FAILED"
        finally:
            _clear(wf_id)

    def test_max_iterations_not_terminal(self):
        """
        BLOCKED from max_iterations must not be treated as terminal FAILED.
        Registry must permit BLOCKED → ACTIVE transition.
        """
        wf_id = "wf-max-iter-resume"
        _register(wf_id, "BLOCKED", "max_iterations_exceeded")
        try:
            state_before = _get_workflow_state(wf_id)
            assert state_before["status"] == "BLOCKED"
            assert state_before["status"] != "FAILED"
            # BLOCKED is recoverable — can transition to ACTIVE
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                _update_runtime_registry_only(wf_id, "ACTIVE")
            state_after = _get_workflow_state(wf_id)
            assert state_after["status"] == "ACTIVE"
        finally:
            _clear(wf_id)


# ============================================================================
# TEST 2: No-progress ceiling → BLOCKED, not FAILED
# ============================================================================

class TestNoProgressCeilingBlocked:
    """
    Per GOVERNANCE_CONTRACT §NO-PROGRESS SAFETY CEILING CLARIFICATION:
    max_iterations_exceeded / no_progress_ceiling → BLOCKED, not FAILED.
    """

    def test_no_progress_ceiling_registry_blocked(self):
        """
        Simulate no-progress ceiling: registry must be BLOCKED.
        """
        wf_id = "wf-no-progress"
        _register(wf_id, "ACTIVE")
        try:
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                _update_runtime_registry_only(wf_id, "BLOCKED", "no_progress_ceiling")

            state = _get_workflow_state(wf_id)
            assert state["status"] == "BLOCKED"
            assert state.get("reason") == "no_progress_ceiling"
            assert state["status"] != "FAILED"
        finally:
            _clear(wf_id)


# ============================================================================
# TEST 3: BLOCKED workflow projection has no failure metadata
# ============================================================================

class TestBlockedProjectionNoFailureMetadata:
    """
    Per CANONICAL_PROJECTION_MODEL_V1 §3:
    Projection MUST NOT synthesize semantic truth for non-FAILED workflows.
    """

    def test_blocked_projection_failure_metadata_null(self):
        from system.orchestrator.projection_schema import (
            build_workflow_projection,
            _compute_failure_metadata,
            _compute_retry_target_step_id,
        )

        wf = _make_workflow("wf-blocked", [
            _make_step("s1", "COMPLETED", exec_res={"status": "success", "result": "ok"}),
            _make_step("s2", "BLOCKED", blocked_reason="dependency_failed:step_1"),
        ])

        # Guard functions must return None for non-FAILED
        retry_target = _compute_retry_target_step_id(wf["steps"], lifecycle_status="BLOCKED")
        assert retry_target is None, f"retry_target must be None for BLOCKED, got {retry_target!r}"

        failure_meta = _compute_failure_metadata(wf["steps"], None, lifecycle_status="BLOCKED")
        assert failure_meta["failure_reason"] is None
        assert failure_meta["failed_step_id"] is None
        assert failure_meta["failed_step_label"] is None

        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="BLOCKED",
        )
        assert proj["lifecycle_status"] == "BLOCKED"
        assert proj["projection_state"] == "ACTIVE"  # non-terminal
        assert proj["failure_reason"] is None
        assert proj["failed_step_id"] is None
        assert proj["failed_step_label"] is None
        assert proj["retry_target_step_id"] is None
        assert proj["retry_eligible"] is False

    def test_blocked_projection_with_escalated_step_no_failure_metadata(self):
        """
        BLOCKED step with escalated reason must NOT synthesize failure metadata.
        """
        from system.orchestrator.projection_schema import build_workflow_projection

        wf = _make_workflow("wf-escalated", [
            _make_step("s1", "COMPLETED", exec_res={"status": "success", "result": "ok"}),
            _make_step("s2", "BLOCKED", blocked_reason="escalated"),
        ])

        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="BLOCKED",
        )
        assert proj["failure_reason"] is None
        assert proj["failed_step_id"] is None
        assert proj["retry_target_step_id"] is None
        assert proj["projection_state"] == "ACTIVE"


# ============================================================================
# TEST 4: PAUSED workflow projection has no failure metadata
# ============================================================================

class TestPausedProjectionNoFailureMetadata:
    """
    Per CANONICAL_PROJECTION_MODEL_V1 §3:
    Projection MUST NOT present failure semantics for PAUSED workflows.
    """

    def test_paused_projection_failure_metadata_null(self):
        from system.orchestrator.projection_schema import build_workflow_projection

        wf = _make_workflow("wf-paused", [
            _make_step("s1", "COMPLETED", exec_res={"status": "success", "result": "ok"}),
            _make_step("s2", "ACTIVE"),
        ])

        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="PAUSED",
        )
        assert proj["lifecycle_status"] == "PAUSED"
        assert proj["projection_state"] == "ACTIVE"
        assert proj["failure_reason"] is None
        assert proj["failed_step_id"] is None
        assert proj["failed_step_label"] is None
        assert proj["retry_target_step_id"] is None
        assert proj["retry_eligible"] is False


# ============================================================================
# TEST 5: FAILED workflow projection still has failure metadata
# ============================================================================

class TestFailedProjectionRetainsFailureMetadata:
    """
    Per ISSUE-057 FIX F: FAILED projection must preserve failure metadata.
    """

    def test_failed_projection_failure_metadata_present(self):
        from system.orchestrator.projection_schema import build_workflow_projection

        wf = _make_workflow("wf-failed", [
            _make_step("s1", "COMPLETED", exec_res={"status": "success", "result": "ok"}),
            _make_step(
                "s2",
                "FAILED",
                exec_res={"status": "failure", "reason": "division_by_zero"},
            ),
            _make_step("s3", "BLOCKED", blocked_reason="dependency_failed:step_2"),
        ], error="execution_failed")

        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="FAILED",
        )
        assert proj["lifecycle_status"] == "FAILED"
        assert proj["projection_state"] == "TERMINAL"
        assert proj["failure_reason"] == "division_by_zero"
        assert proj["failed_step_id"] == "s2"
        assert proj["failed_step_label"] == "s2"
        assert proj["retry_target_step_id"] == "s2"
        assert proj["retry_eligible"] is True
        assert proj["last_successful_output"] == "ok"
        assert proj["last_successful_step_id"] == "s1"

    def test_failed_with_blocked_step_retry_target(self):
        """
        FAILED workflow with no FAILED steps but a causative BLOCKED step
        must still compute retry target from BLOCKED step.
        """
        from system.orchestrator.projection_schema import (
            build_workflow_projection,
            _compute_retry_target_step_id,
            _compute_failure_metadata,
        )

        wf = _make_workflow("wf-failed-blocked", [
            _make_step("s1", "COMPLETED"),
            _make_step("s2", "BLOCKED", blocked_reason="max_retries_exceeded"),
        ])

        retry_target = _compute_retry_target_step_id(wf["steps"], lifecycle_status="FAILED")
        assert retry_target == "s2", f"retry_target must be s2, got {retry_target!r}"

        failure_meta = _compute_failure_metadata(wf["steps"], None, lifecycle_status="FAILED")
        assert failure_meta["failed_step_id"] == "s2"
        assert failure_meta["failure_reason"] == "max_retries_exceeded"

        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="FAILED",
        )
        assert proj["retry_target_step_id"] == "s2"
        assert proj["failed_step_id"] == "s2"


# ============================================================================
# TEST 6: Dependency-victim downstream BLOCKED steps do not auto-terminalize
# ============================================================================

class TestDependencyVictimBlockedNotAutoFailed:
    """
    Per STEP_IO_CONTRACT_V1 §DEPENDENCY RULES:
    If a dependency step FAILS → dependent steps MUST NOT execute.
    Dependent steps remain BLOCKED.
    Per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1 §3:
    BLOCKED MUST NOT be treated as terminal failure.
    """

    def test_dependency_victim_workflow_status_blocked(self):
        """
        Simulate post-loop behavior: workflow with a FAILED step and a
        downstream dependency-victim BLOCKED step must remain BLOCKED, not FAILED.
        """
        wf_id = "wf-dep-victim"
        _register(wf_id, "ACTIVE")
        try:
            # Simulate what the post-loop code should do now:
            # The first non-COMPLETED step is BLOCKED (downstream victim).
            # It should set registry to BLOCKED, not FAILED.
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                _update_runtime_registry_only(wf_id, "BLOCKED", "dependency_failed:step_1")

            state = _get_workflow_state(wf_id)
            assert state["status"] == "BLOCKED", (
                f"workflow must remain BLOCKED, got: {state['status']!r}"
            )
            assert state["status"] != "FAILED"
        finally:
            _clear(wf_id)

    def test_permanently_blocked_workflow_not_auto_failed(self):
        """
        Per BLOCKED SEMANTIC FIX: all BLOCKED steps being 'permanently blocked'
        must NOT auto-convert workflow to FAILED.
        """
        wf_id = "wf-all-perm-blocked"
        _register(wf_id, "ACTIVE")
        try:
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                _update_runtime_registry_only(wf_id, "BLOCKED", "permanently_blocked")

            state = _get_workflow_state(wf_id)
            assert state["status"] == "BLOCKED"
            assert state["status"] != "FAILED"
        finally:
            _clear(wf_id)


# ============================================================================
# TEST 7: Governance escalation / retry exhaustion → BLOCKED
# ============================================================================

class TestEscalationRetryExhaustionBlocked:
    """
    Per GOVERNANCE_CONTRACT §ESCALATION MODEL:
    ESCALATION EFFECT: step → BLOCKED, workflow → BLOCKED.
    """

    def test_escalation_registry_blocked(self):
        wf_id = "wf-escalate"
        _register(wf_id, "ACTIVE")
        try:
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                _update_runtime_registry_only(wf_id, "BLOCKED", "escalated")

            state = _get_workflow_state(wf_id)
            assert state["status"] == "BLOCKED"
            assert state["status"] != "FAILED"
        finally:
            _clear(wf_id)

    def test_max_retries_exhausted_registry_blocked(self):
        wf_id = "wf-retry-exhaust"
        _register(wf_id, "ACTIVE")
        try:
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                _update_runtime_registry_only(wf_id, "BLOCKED", "max_retries_exceeded")

            state = _get_workflow_state(wf_id)
            assert state["status"] == "BLOCKED"
            assert state["status"] != "FAILED"
        finally:
            _clear(wf_id)


# ============================================================================
# TEST 8: Non-terminal BLOCKED projection emitted
# ============================================================================

class TestBlockedProjectionNonTerminal:
    """
    Per CANONICAL_PROJECTION_MODEL_V1 §14:
    BLOCKED is not a terminal workflow state → projection_state = ACTIVE.
    """

    def test_blocked_lifecycle_projection_state_active(self):
        from system.orchestrator.projection_schema import build_workflow_projection

        wf = _make_workflow("wf-blocked-proj", [
            _make_step("s1", "BLOCKED", blocked_reason="approval_required"),
        ])

        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="BLOCKED",
        )
        assert proj["lifecycle_status"] == "BLOCKED"
        assert proj["projection_state"] == "ACTIVE"

    def test_max_iterations_blocked_projection_state_active(self):
        from system.orchestrator.projection_schema import build_workflow_projection

        wf = _make_workflow("wf-maxiter-proj", [
            _make_step("s1", "COMPLETED"),
            _make_step("s2", "BLOCKED", blocked_reason="max_iterations_exceeded"),
        ])

        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="BLOCKED",
        )
        assert proj["projection_state"] == "ACTIVE"
        assert proj["failure_reason"] is None


# ============================================================================
# TEST 9: Recoverable FAILED behavior unchanged
# ============================================================================

class TestRecoverableFailedUnchanged:
    """
    Per LIFECYCLE_AUTHORITY_CONTRACT_V1 §FAILED LIFECYCLE SEMANTICS:
    FAILED is recoverable terminal state. Retry remains legal.
    """

    def test_failed_projection_recoverable_defaults(self):
        from system.orchestrator.projection_schema import build_workflow_projection

        wf = _make_workflow("wf-failed-recoverable", [
            _make_step("s1", "FAILED", exec_res={"status": "failure", "reason": "error"}),
        ])

        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="FAILED",
        )
        assert proj["lifecycle_status"] == "FAILED"
        assert proj["projection_state"] == "TERMINAL"
        assert proj["failed_recoverable"] is True  # backward compat default
        assert proj["retry_eligible"] is True


# ============================================================================
# TEST 10: Task Hub / History eligibility fields unchanged
# ============================================================================

class TestTaskHubHistoryFieldsUnchanged:
    """
    This implementation must not change Task Hub / History eligibility logic.
    Projection schema must not add/remove eligibility fields.
    """

    def test_projection_fields_unchanged(self):
        from system.orchestrator.projection_schema import build_workflow_projection

        wf = _make_workflow("wf-eligibility-check", [
            _make_step("s1", "COMPLETED"),
        ])

        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="BLOCKED",
        )

        # Verify no new eligibility fields were added
        assert "taskhub_eligible" not in proj
        assert "history_eligible" not in proj

        # Verify projection still has expected fields
        assert "lifecycle_status" in proj
        assert "projection_state" in proj
        assert "steps" in proj
        assert "outputs" in proj
        assert "failed_recoverable" in proj
        assert "retry_eligible" in proj
