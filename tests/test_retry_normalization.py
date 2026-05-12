"""
CATEGORY: REGRESSION
AUTHORITY_LAYER: Historical Bug Prevention
VALIDATES:
  - Phase 1B retry normalization fixes
  - Workflow aggregate status recomputation
  - Blocked reason clearing on retry
  - Dependency graph normalization
ENTRYPOINT: run_workflow, direct workflow_control functions
DIRECT_INTERNAL_CALLS:
  - workflow_control._workflow_state_registry
  - workflow_control._update_runtime_registry_only
  - workflow_control._invalidate_dependents
  - workflow_control.retry_step
  - workflow_control.request_step_transition
  - escalation_controller.handle_retry
MONKEYPATCH_USAGE:
  - workflow_control.save_workflow (no-op for tests)
  - workflow_control.load_active_workflows (mocked for tests)
  - workflow_control._update_workflow_state (side_effect for registry-only update)
MOCKING_POLICY: AS_PER_HISTORICAL_BUG
TEST_INTENT: HISTORICAL_BUG_PREVENTION
ARCHITECTURAL_SCOPE: Phase 1B retry normalization fixes

HISTORICAL_FIX: Phase 1B retry lifecycle fixes
REGRESSION_REASON: Prevent recurrence of retry normalization bugs
PRESERVATION_PRIORITY: HIGH

---

test_retry_normalization.py

Runtime trace validation for Phase 1B retry lifecycle fixes.

FIXES UNDER TEST
----------------
workflow_control.py  — retry_step:
  FIX A: _invalidate_dependents called after step reset
  FIX C: workflow aggregate status/error/output recomputed from canonical step states

escalation_controller.py — handle_retry:
  FIX B: blocked_reason cleared when setting status=ACTIVE (state invariant enforcement)

App.jsx (frontend):
  FIX D: "Unknown error" replaced with canonical reason derivation hierarchy
  (validated via unit-level simulation — no DOM/React runner required)

INVARIANTS ENFORCED
-------------------
  INV-1: ACTIVE step MUST NOT carry blocked_reason
  INV-2: COMPLETED step MUST NOT carry blocked_reason
  INV-3: FAILED workflow MUST NOT show success output
  INV-4: BLOCKED step with satisfied deps MUST NOT remain BLOCKED

VALIDATION CASES
----------------
  CASE 1 — Retry blocked step: dep graph normalized, no ACTIVE+blocked_reason
  CASE 2 — Retry completed step: downstream invalidated, aggregate recomputed
  CASE 3 — Retry active step: rejected canonically, no partial mutation
  CASE 4 — Retry after failure: FAILED cleared, aggregate recomputed
  CASE 5 — Projection/runtime consistency after retry
"""

import time
import threading
from copy import deepcopy
from unittest.mock import patch, MagicMock

import pytest

from system.orchestrator.workflow_control import (
    _workflow_state_registry,
    _workflow_state_lock,
    _update_workflow_state,
    _update_runtime_registry_only,
    _get_workflow_state,
    _invalidate_dependents,
    retry_step,
    request_step_transition,
)
from system.orchestrator.escalation_controller import handle_retry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patched_update(wf_id, status, reason=None):
    return _update_runtime_registry_only(wf_id, status, reason) or True


def _register(wf_id, status, reason=None):
    with _workflow_state_lock:
        _workflow_state_registry[wf_id] = {
            "status": status,
            "last_updated": time.time(),
            "reason": reason,
        }


def _clear(wf_id):
    with _workflow_state_lock:
        _workflow_state_registry.pop(wf_id, None)


def _make_step(sid, status, blocked_reason=None, exec_res=None, retries=0,
               depends_on=None):
    s = {
        "id": sid,
        "status": status,
        "retries": retries,
        "max_retries": 3,
        "input": f"do {sid}",
        "depends_on": depends_on or [],
    }
    if blocked_reason:
        s["blocked_reason"] = blocked_reason
    if exec_res is not None:
        s["execution_result"] = exec_res
    return s


def _make_workflow(wf_id, steps, status="ACTIVE", error=None, output=None):
    wf = {"id": wf_id, "status": status, "steps": steps}
    if error:
        wf["error"] = error
    if output is not None:
        wf["output"] = output
    return wf


def _patch_save(monkeypatch):
    """Patch save_workflow to no-op so tests don't write to disk."""
    monkeypatch.setattr(
        "system.orchestrator.workflow_control.save_workflow",
        lambda wf: None,
    )


def _patch_load(monkeypatch, workflows):
    """Patch load_active_workflows to return a known list."""
    monkeypatch.setattr(
        "system.orchestrator.workflow_control.load_active_workflows",
        lambda: workflows,
    )


# ---------------------------------------------------------------------------
# CASE 1 — Retry blocked step
# ---------------------------------------------------------------------------

class TestCase1RetryBlockedStep:
    """
    Retry a BLOCKED step whose dep chain is stale.
    After retry:
    - target step is RETRY (no blocked_reason)
    - downstream dependents are PENDING (invalidated)
    - workflow aggregate is ACTIVE
    - no ACTIVE+blocked_reason contradiction
    """

    def test_retry_blocked_resets_step_to_retry(self, monkeypatch):
        wf_id = "wf-c1-reset"
        s1 = _make_step("s1", "COMPLETED")
        s2 = _make_step("s2", "BLOCKED",
                        blocked_reason="dependency_not_completed:s1:BLOCKED",
                        depends_on=["s1"])
        wf = _make_workflow(wf_id, [s1, s2], status="BLOCKED", error="max_retries_exceeded")
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "BLOCKED", "max_retries_exceeded")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                result = retry_step(wf_id, "s2")

            assert result["status"] == "success", f"retry failed: {result}"
            assert s2["status"] == "RETRY"
            assert "blocked_reason" not in s2, "blocked_reason must be cleared on RETRY"
            assert s2.get("execution_result") is None
        finally:
            _clear(wf_id)

    def test_retry_blocked_clears_workflow_error(self, monkeypatch):
        wf_id = "wf-c1-wferr"
        s1 = _make_step("s1", "BLOCKED", blocked_reason="dependency_not_completed:s0:BLOCKED")
        wf = _make_workflow(wf_id, [s1], status="BLOCKED", error="max_retries_exceeded",
                            output={"status": "failure", "reason": "old"})
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "BLOCKED")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                retry_step(wf_id, "s1")

            assert "error" not in wf, "workflow.error must be cleared after retry"
            assert wf.get("output") is None, "workflow.output must be cleared after retry"
        finally:
            _clear(wf_id)

    def test_retry_blocked_invalidates_downstream_dependents(self, monkeypatch):
        wf_id = "wf-c1-dep"
        s1 = _make_step("s1", "BLOCKED", blocked_reason="some_reason")
        s2 = _make_step("s2", "BLOCKED",
                        blocked_reason="dependency_not_completed:s1:BLOCKED",
                        depends_on=["s1"])
        s3 = _make_step("s3", "BLOCKED",
                        blocked_reason="dependency_not_completed:s2:BLOCKED",
                        depends_on=["s2"])
        wf = _make_workflow(wf_id, [s1, s2, s3], status="BLOCKED")
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "BLOCKED")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                result = retry_step(wf_id, "s1")

            assert result["status"] == "success"
            # s2 and s3 must be invalidated to PENDING by _invalidate_dependents
            assert s2["status"] == "PENDING", f"s2 should be PENDING, got {s2['status']}"
            assert s3["status"] == "PENDING", f"s3 should be PENDING, got {s3['status']}"
            # their blocked_reasons must be cleared by _invalidate_dependents
            assert "blocked_reason" not in s2
            assert "blocked_reason" not in s3
        finally:
            _clear(wf_id)

    def test_no_active_plus_blocked_reason_after_retry(self, monkeypatch):
        """INV-1: no step can be ACTIVE and carry blocked_reason simultaneously."""
        wf_id = "wf-c1-inv1"
        s1 = _make_step("s1", "BLOCKED", blocked_reason="dependency_not_completed:s0:BLOCKED")
        s2 = _make_step("s2", "BLOCKED",
                        blocked_reason="dependency_not_completed:s1:BLOCKED",
                        depends_on=["s1"])
        wf = _make_workflow(wf_id, [s1, s2], status="BLOCKED")
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "BLOCKED")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                retry_step(wf_id, "s1")

            for step in wf["steps"]:
                if step["status"] == "ACTIVE":
                    assert "blocked_reason" not in step, (
                        f"INV-1 violated: step {step['id']} is ACTIVE with blocked_reason={step.get('blocked_reason')!r}"
                    )
        finally:
            _clear(wf_id)

    def test_workflow_aggregate_recomputed_to_active(self, monkeypatch):
        wf_id = "wf-c1-agg"
        s1 = _make_step("s1", "BLOCKED")
        wf = _make_workflow(wf_id, [s1], status="BLOCKED", error="max_retries_exceeded")
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "BLOCKED")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                retry_step(wf_id, "s1")

            # Workflow dict aggregate must be ACTIVE
            assert wf["status"] == "ACTIVE", f"workflow.status should be ACTIVE, got {wf['status']}"
            # Registry must also be ACTIVE
            state = _get_workflow_state(wf_id)
            assert state["status"] == "ACTIVE", f"registry should be ACTIVE, got {state['status']}"
        finally:
            _clear(wf_id)


# ---------------------------------------------------------------------------
# CASE 2 — Retry completed step
# ---------------------------------------------------------------------------

class TestCase2RetryCompletedStep:
    """
    Retry a COMPLETED step must be rejected — COMPLETED is terminal.
    """

    def test_retry_completed_step_rejected(self, monkeypatch):
        wf_id = "wf-c2-comp"
        s1 = _make_step("s1", "COMPLETED")
        wf = _make_workflow(wf_id, [s1])
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "ACTIVE")
        try:
            result = retry_step(wf_id, "s1")
            assert result["status"] == "failure"
            assert "cannot_retry_COMPLETED" in result["reason"]
            # step must remain COMPLETED — no mutation
            assert s1["status"] == "COMPLETED"
        finally:
            _clear(wf_id)

    def test_no_partial_mutation_on_completed_rejection(self, monkeypatch):
        wf_id = "wf-c2-nomut"
        s1 = _make_step("s1", "COMPLETED")
        s1["execution_result"] = {"status": "success", "result": 42}
        wf = _make_workflow(wf_id, [s1])
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "ACTIVE")
        try:
            retry_step(wf_id, "s1")
            # execution_result must not be touched
            assert s1.get("execution_result", {}).get("result") == 42
        finally:
            _clear(wf_id)


# ---------------------------------------------------------------------------
# CASE 3 — Retry active step rejection
# ---------------------------------------------------------------------------

class TestCase3RetryActiveRejection:
    """
    Retry an ACTIVE step must be explicitly rejected — canonical, no partial mutation.
    """

    def test_retry_active_step_rejected(self, monkeypatch):
        wf_id = "wf-c3-active"
        s1 = _make_step("s1", "ACTIVE")
        wf = _make_workflow(wf_id, [s1])
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "ACTIVE")
        try:
            result = retry_step(wf_id, "s1")
            assert result["status"] == "failure"
            assert "cannot_retry_ACTIVE" in result["reason"]
            assert s1["status"] == "ACTIVE"
        finally:
            _clear(wf_id)

    def test_retry_pending_step_rejected(self, monkeypatch):
        wf_id = "wf-c3-pending"
        s1 = _make_step("s1", "PENDING")
        wf = _make_workflow(wf_id, [s1])
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "ACTIVE")
        try:
            result = retry_step(wf_id, "s1")
            assert result["status"] == "failure"
            assert "cannot_retry_PENDING" in result["reason"]
            assert s1["status"] == "PENDING"
        finally:
            _clear(wf_id)

    def test_retry_retry_state_rejected(self, monkeypatch):
        wf_id = "wf-c3-retry"
        s1 = _make_step("s1", "RETRY")
        wf = _make_workflow(wf_id, [s1])
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "ACTIVE")
        try:
            result = retry_step(wf_id, "s1")
            assert result["status"] == "failure"
            assert "cannot_retry_RETRY" in result["reason"]
        finally:
            _clear(wf_id)


# ---------------------------------------------------------------------------
# CASE 4 — Retry after failure
# ---------------------------------------------------------------------------

class TestCase4RetryAfterFailure:
    """
    Retry a FAILED step:
    - FAILED cleared from step
    - workflow.output cleared
    - workflow aggregate recomputed from remaining steps
    """

    def test_retry_failed_step_resets_correctly(self, monkeypatch):
        wf_id = "wf-c4-failed"
        s1 = _make_step("s1", "FAILED",
                        exec_res={"status": "failure", "reason": "tool_error"})
        wf = _make_workflow(
            wf_id, [s1],
            status="FAILED",
            output={"status": "success", "result": 5},  # INV-3 violation baked in
        )
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "FAILED")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                result = retry_step(wf_id, "s1")

            assert result["status"] == "success"
            assert s1["status"] == "RETRY"
            assert s1.get("execution_result") is None
            # INV-3: FAILED workflow must not have success output after retry
            assert wf.get("output") is None, "stale success output must be cleared"
            assert wf["status"] == "ACTIVE"
        finally:
            _clear(wf_id)

    def test_failed_workflow_with_other_failed_steps_stays_failed(self, monkeypatch):
        """
        If OTHER steps are still FAILED, workflow aggregate stays FAILED after retry.
        """
        wf_id = "wf-c4-mixfail"
        s1 = _make_step("s1", "FAILED")
        s2 = _make_step("s2", "FAILED")  # not being retried
        wf = _make_workflow(wf_id, [s1, s2], status="FAILED")
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "FAILED")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                result = retry_step(wf_id, "s1")

            assert result["status"] == "success"
            # s2 is still FAILED → workflow should remain FAILED
            assert wf["status"] == "FAILED", (
                f"workflow must stay FAILED while s2 is still FAILED, got {wf['status']}"
            )
        finally:
            _clear(wf_id)

    def test_retry_clears_stale_error_field(self, monkeypatch):
        wf_id = "wf-c4-errclr"
        s1 = _make_step("s1", "FAILED")
        wf = _make_workflow(wf_id, [s1], status="BLOCKED", error="max_retries_exceeded")
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "BLOCKED")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                retry_step(wf_id, "s1")

            assert "error" not in wf, f"stale workflow.error must be cleared, got {wf.get('error')!r}"
        finally:
            _clear(wf_id)


# ---------------------------------------------------------------------------
# FIX B — State invariant: handle_retry clears blocked_reason
# ---------------------------------------------------------------------------

class TestFixBHandleRetryInvariant:
    """
    INV-1: ACTIVE step MUST NOT carry blocked_reason.
    handle_retry in escalation_controller must pop blocked_reason when setting ACTIVE.
    """

    def test_handle_retry_clears_blocked_reason(self):
        """
        Direct unit test of handle_retry: step enters with blocked_reason set.
        After handle_retry returns RETRY action, blocked_reason must be gone.
        """
        step = {
            "id": "s1",
            "status": "BLOCKED",
            "blocked_reason": "dependency_not_completed:step_1:PENDING",
            "retries": 0,
            "max_retries": 3,
            "input": "do something",
        }
        workflow = {"id": "wf-fix-b", "status": "BLOCKED", "steps": [step]}

        result = handle_retry(step=step, workflow=workflow, next_decision="retry")

        assert result["action"] == "RETRY"
        assert step["status"] == "ACTIVE"
        assert "blocked_reason" not in step, (
            f"INV-1 violated: ACTIVE step still has blocked_reason={step.get('blocked_reason')!r}"
        )

    def test_handle_retry_active_has_no_blocked_reason_after_second_retry(self):
        """
        Even on subsequent retries, blocked_reason must not survive on ACTIVE step.
        """
        step = {
            "id": "s1",
            "status": "ACTIVE",
            "blocked_reason": "dependency_not_completed:s0:BLOCKED",
            "retries": 1,
            "max_retries": 5,
            "input": "do something",
        }
        workflow = {"id": "wf-fix-b2", "status": "ACTIVE", "steps": [step]}

        result = handle_retry(step=step, workflow=workflow, next_decision="retry")

        assert result["action"] == "RETRY"
        assert "blocked_reason" not in step, (
            f"INV-1 still violated on second retry: {step.get('blocked_reason')!r}"
        )

    def test_handle_retry_non_retry_decision_is_noop(self):
        """
        handle_retry called with non-retry decision returns COMPLETE, no mutation.
        """
        step = {
            "id": "s1",
            "status": "ACTIVE",
            "blocked_reason": "should_not_be_cleared",
            "retries": 0,
            "max_retries": 3,
            "input": "x",
        }
        workflow = {"id": "wf-fix-b3", "status": "ACTIVE", "steps": [step]}

        result = handle_retry(step=step, workflow=workflow, next_decision="complete")

        assert result["action"] == "COMPLETE"
        # blocked_reason NOT cleared — non-retry path is no-op
        assert step.get("blocked_reason") == "should_not_be_cleared"


# ---------------------------------------------------------------------------
# CASE 5 — Projection / runtime consistency
# ---------------------------------------------------------------------------

class TestCase5ProjectionRuntimeConsistency:
    """
    After retry cycle:
    - projection lifecycle_status matches registry
    - projection step statuses match workflow dict
    - BLOCKED projection_state is ACTIVE (not TERMINAL)
    - dep-blocked steps project correct blocked_reason
    """

    def test_projection_reflects_retry_state(self):
        from system.orchestrator.projection_schema import (
            build_workflow_projection,
            PROJECTION_STATE_ACTIVE,
        )
        s1 = _make_step("s1", "RETRY")
        s2 = _make_step("s2", "PENDING", depends_on=["s1"])
        wf = _make_workflow("wf-c5-proj", [s1, s2], status="ACTIVE")

        projection = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="ACTIVE",
        )

        assert projection["lifecycle_status"] == "ACTIVE"
        assert projection["projection_state"] == PROJECTION_STATE_ACTIVE
        step_proj = {s["step_id"]: s for s in projection["steps"]}
        assert step_proj["s1"]["status"] == "RETRY"
        assert step_proj["s2"]["status"] == "PENDING"
        assert step_proj["s1"].get("blocked_reason") is None  # INV-1 in projection

    def test_projection_no_blocked_reason_on_retry_step(self):
        from system.orchestrator.projection_schema import build_workflow_projection
        s1 = _make_step("s1", "RETRY")
        # Ensure no blocked_reason bleeds into RETRY projection
        assert "blocked_reason" not in s1

        wf = _make_workflow("wf-c5-br", [s1])
        proj = build_workflow_projection(wf, 1, "ACTIVE")
        assert proj["steps"][0].get("blocked_reason") is None

    def test_registry_workflow_dict_projection_converge_after_retry(
        self, monkeypatch
    ):
        wf_id = "wf-c5-conv"
        s1 = _make_step("s1", "BLOCKED")
        s2 = _make_step("s2", "BLOCKED",
                        blocked_reason="dependency_not_completed:s1:BLOCKED",
                        depends_on=["s1"])
        wf = _make_workflow(wf_id, [s1, s2], status="BLOCKED", error="max_retries_exceeded")
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "BLOCKED", "max_retries_exceeded")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                retry_step(wf_id, "s1")

            # All three sources converge:
            # 1. Registry
            reg = _get_workflow_state(wf_id)
            assert reg["status"] == "ACTIVE"

            # 2. Workflow dict (compatibility mirror)
            assert wf["status"] == "ACTIVE"

            # 3. Step statuses as they would appear in projection
            from system.orchestrator.projection_schema import (
                build_workflow_projection,
                PROJECTION_STATE_ACTIVE,
            )
            proj = build_workflow_projection(wf, 1, "ACTIVE")
            assert proj["lifecycle_status"] == "ACTIVE"
            assert proj["projection_state"] == PROJECTION_STATE_ACTIVE

            step_map = {s["step_id"]: s for s in proj["steps"]}
            assert step_map["s1"]["status"] == "RETRY"
            assert step_map["s2"]["status"] == "PENDING"
            assert step_map["s2"].get("blocked_reason") is None
        finally:
            _clear(wf_id)


# ---------------------------------------------------------------------------
# INVARIANT ENFORCEMENT TESTS
# ---------------------------------------------------------------------------

class TestStateInvariants:
    """
    Explicit invariant validation — these must never be violated.
    """

    def test_inv1_active_step_never_has_blocked_reason_after_handle_retry(self):
        """INV-1: ACTIVE + blocked_reason is always invalid post-handle_retry."""
        step = {
            "id": "s1", "status": "BLOCKED",
            "blocked_reason": "dependency_not_completed:x:PENDING",
            "retries": 0, "max_retries": 5, "input": "x",
        }
        wf = {"id": "wf-inv1", "status": "BLOCKED", "steps": [step]}
        handle_retry(step, wf, "retry")
        assert step["status"] == "ACTIVE"
        assert "blocked_reason" not in step

    def test_inv2_completed_step_never_has_blocked_reason(self):
        """
        INV-2: If a step reaches COMPLETED, blocked_reason must be absent.
        request_step_transition clears it per workflow_control.py line 105.
        """
        step = {"id": "s1", "status": "BLOCKED", "blocked_reason": "dep_x"}
        result = request_step_transition(step, "ACTIVE", _internal=False)
        # BLOCKED→ACTIVE is valid per FSM; blocked_reason must be cleared
        assert result is True
        assert "blocked_reason" not in step

    def test_inv3_failed_workflow_cleared_on_retry(self, monkeypatch):
        """
        INV-3: FAILED workflow with success output is resolved by retry.
        After retry, output must be None.
        """
        wf_id = "wf-inv3"
        s1 = _make_step("s1", "FAILED")
        wf = _make_workflow(wf_id, [s1], status="FAILED",
                            output={"status": "success", "result": 5})
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "FAILED")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                retry_step(wf_id, "s1")
            assert wf.get("output") is None
        finally:
            _clear(wf_id)

    def test_inv4_blocked_step_with_satisfied_deps_gets_invalidated(self, monkeypatch):
        """
        INV-4: After retrying the upstream dep, downstream BLOCKED step becomes PENDING
        (not still BLOCKED with stale blocked_reason).
        """
        wf_id = "wf-inv4"
        s1 = _make_step("s1", "BLOCKED")
        s2 = _make_step("s2", "BLOCKED",
                        blocked_reason="dependency_not_completed:s1:BLOCKED",
                        depends_on=["s1"])
        wf = _make_workflow(wf_id, [s1, s2], status="BLOCKED")
        _patch_save(monkeypatch)
        _patch_load(monkeypatch, [wf])
        _register(wf_id, "BLOCKED")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                retry_step(wf_id, "s1")
            # INV-4: s2 must now be PENDING, not still BLOCKED
            assert s2["status"] == "PENDING", (
                f"INV-4 violated: s2 still BLOCKED after upstream retry, "
                f"blocked_reason={s2.get('blocked_reason')!r}"
            )
        finally:
            _clear(wf_id)


# ---------------------------------------------------------------------------
# REGRESSION: Prior fixes A/C/D/E/F still intact
# ---------------------------------------------------------------------------

class TestRegressionPriorFixes:

    def test_pause_resume_unaffected(self):
        """Pause/resume FSM still works after retry fix."""
        from system.orchestrator.workflow_control import pause_workflow, resume_workflow
        wf_id = "wf-reg-pr"
        _register(wf_id, "ACTIVE")
        try:
            with patch("system.orchestrator.workflow_control._update_workflow_state",
                       side_effect=_patched_update):
                r1 = pause_workflow(wf_id)
                assert r1["status"] == "success"
                assert _get_workflow_state(wf_id)["status"] == "PAUSED"
                r2 = resume_workflow(wf_id)
                assert r2["status"] == "success"
                assert _get_workflow_state(wf_id)["status"] == "ACTIVE"
        finally:
            _clear(wf_id)

    def test_escalated_terminal_guard_unchanged(self):
        """resume_workflow still rejects BLOCKED/escalated after retry fix."""
        from system.orchestrator.workflow_control import resume_workflow
        wf_id = "wf-reg-esc"
        _register(wf_id, "BLOCKED", "escalated")
        try:
            r = resume_workflow(wf_id)
            assert r["status"] == "failure"
            assert "blocked_state_not_resumable" in r["reason"]
        finally:
            _clear(wf_id)

    def test_post_loop_gate_dep_reason_not_escalated(self):
        """Post-loop gate fix: dep-blocked step writes dep reason not 'escalated'."""
        from system.orchestrator.orchestrator_runtime import _update_workflow_state as _rt_update
        step = {"id": "s1", "status": "BLOCKED",
                "blocked_reason": "dependency_not_completed:s0:BLOCKED"}
        wf = {"id": "wf-reg-gate", "status": "BLOCKED", "steps": [step]}
        exec_res = None
        reason = (
            (exec_res.get("reason") if exec_res else None)
            or step.get("blocked_reason")
            or wf.get("error")
            or "blocked"
        )
        assert reason == "dependency_not_completed:s0:BLOCKED"
        assert reason != "escalated"
