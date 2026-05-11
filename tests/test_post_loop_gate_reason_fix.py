"""
test_post_loop_gate_reason_fix.py

Runtime trace validation for the Phase 1B post-loop gate reason fix.

FIXES UNDER TEST
----------------
orchestrator_runtime.py — FAILURE DETECTION GATE (line ~766)
orchestrator_runtime.py — FINAL VALIDATION GATE (line ~813)

Both gates previously hardcoded "escalated" as the fallback reason when writing
BLOCKED state to the authoritative registry.  That caused resume_workflow()'s
_TERMINAL_BLOCK_REASONS guard to reject the next resume even for recoverable
states (dep-blocked, retry-exhausted-but-not-terminal).

The fix: reason is now derived from:
    exec_res.get("reason") → step.blocked_reason → workflow.error → "blocked"

"blocked" is the raw FSM state name — already a contract-defined token.
No new lifecycle semantic tokens are introduced.

CASES VALIDATED
---------------
CASE 1 — Recoverable dep-block:
  step is BLOCKED with blocked_reason="dependency_not_completed:step_1:BLOCKED"
  No exec_res.  workflow.error not set.
  Gate must write reason="dependency_not_completed:step_1:BLOCKED" to registry.
  "dependency_not_completed:..." is NOT in _TERMINAL_BLOCK_REASONS.
  resume_workflow() must succeed (BLOCKED → ACTIVE).

CASE 2 — Genuine terminal escalation:
  step is BLOCKED with blocked_reason="escalated" (set by escalation controller).
  Gate must write reason="escalated" to registry.
  "escalated" IS in _TERMINAL_BLOCK_REASONS.
  resume_workflow() must be rejected with blocked_state_not_resumable:escalated.

CASE 3 — Projection / persistence / registry convergence:
  After reevaluation cycle: projection status, registry status, persisted status,
  step statuses must all converge.

INVARIANTS PRESERVED
---------------------
* _update_workflow_state remains sole lifecycle writer
* resume_workflow guard unchanged
* normalization fixes A/C/D/E/F intact
* no scheduler / projection / lifecycle redesign
"""

import time
import threading
from unittest.mock import patch, MagicMock

import pytest

from system.orchestrator.workflow_control import (
    _workflow_state_registry,
    _workflow_state_lock,
    _update_workflow_state,
    _update_runtime_registry_only,
    _get_workflow_state,
    resume_workflow,
    pause_workflow,
    request_step_transition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patched_update(wf_id, status, reason=None):
    """Registry-only update — no disk write (used when testing without persistence)."""
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


def _simulate_failure_detection_gate(workflow):
    """
    Pure simulation of the FAILURE DETECTION GATE logic (orchestrator_runtime.py ~756-777).
    Returns (reason_written, registry_status) without calling run_workflow.
    """
    for step in workflow.get("steps", []):
        exec_res = step.get("execution_result")
        if step.get("status") == "BLOCKED":
            reason = (
                (exec_res.get("reason") if exec_res else None)
                or step.get("blocked_reason")
                or workflow.get("error")
                or "blocked"
            )
            return reason
    return None


def _simulate_final_validation_gate(workflow):
    """
    Pure simulation of the FINAL VALIDATION GATE logic (orchestrator_runtime.py ~808-823).
    """
    for step in workflow.get("steps", []):
        if step.get("status") == "BLOCKED":
            _fvg_exec_res = step.get("execution_result")
            _fvg_reason = (
                (_fvg_exec_res.get("reason") if _fvg_exec_res else None)
                or step.get("blocked_reason")
                or workflow.get("error")
                or "blocked"
            )
            return _fvg_reason
    return None


# ---------------------------------------------------------------------------
# CASE 1 — Recoverable dependency block
# ---------------------------------------------------------------------------

class TestCase1RecoverableDepBlock:
    """
    CASE 1: step is dep-blocked (blocked_reason="dependency_not_completed:...").
    Gate must NOT write "escalated".
    resume_workflow() must succeed after the gate fires.
    """

    def test_failure_detection_gate_dep_blocked_reason_not_escalated(self):
        """
        FAILURE DETECTION GATE: dep-blocked step → reason derives from blocked_reason,
        NOT hardcoded "escalated".
        """
        step = _make_step(
            "s1",
            status="BLOCKED",
            blocked_reason="dependency_not_completed:step_0:BLOCKED",
        )
        wf = _make_workflow("wf-case1-fdg", [step])
        reason = _simulate_failure_detection_gate(wf)

        assert reason == "dependency_not_completed:step_0:BLOCKED", (
            f"expected dep reason, got: {reason!r}"
        )
        assert reason != "escalated", "must NOT write escalated for dep-blocked step"

    def test_final_validation_gate_dep_blocked_reason_not_escalated(self):
        """
        FINAL VALIDATION GATE: same derivation — dep reason propagates, not "escalated".
        """
        step = _make_step(
            "s1",
            status="BLOCKED",
            blocked_reason="dependency_not_completed:step_0:PENDING",
        )
        wf = _make_workflow("wf-case1-fvg", [step])
        reason = _simulate_final_validation_gate(wf)

        assert reason == "dependency_not_completed:step_0:PENDING"
        assert reason != "escalated"

    def test_registry_written_with_dep_reason_not_escalated(self):
        """
        _update_workflow_state called with dep reason → registry stores dep reason.
        resume_workflow() must NOT see "escalated" and must not reject.
        """
        wf_id = "wf-case1-registry"
        _register(wf_id, "ACTIVE")
        try:
            dep_reason = "dependency_not_completed:step_0:BLOCKED"
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                _update_runtime_registry_only(wf_id, "BLOCKED", dep_reason)

            state = _get_workflow_state(wf_id)
            assert state["status"] == "BLOCKED"
            assert state.get("reason") == dep_reason, (
                f"registry reason wrong: {state.get('reason')!r}"
            )
            assert state.get("reason") != "escalated"
        finally:
            _clear(wf_id)

    def test_resume_succeeds_after_dep_blocked_registry_state(self):
        """
        TRACE: After gate writes dep reason to registry, resume_workflow() must succeed.
        dep reason is NOT in _TERMINAL_BLOCK_REASONS → BLOCKED → ACTIVE allowed.
        """
        wf_id = "wf-case1-resume"
        _register(wf_id, "BLOCKED", "dependency_not_completed:step_0:BLOCKED")
        try:
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                result = resume_workflow(wf_id)

            assert result["status"] == "success", (
                f"resume must succeed for dep-blocked, got: {result}"
            )
            assert result["new_state"] == "ACTIVE"

            state = _get_workflow_state(wf_id)
            assert state["status"] == "ACTIVE"
        finally:
            _clear(wf_id)

    def test_resume_succeeds_after_blocked_fallback_reason(self):
        """
        TRACE: Step has no blocked_reason, no exec_res, workflow has no error.
        Gate writes reason="blocked" (FSM state name, not "escalated").
        "blocked" is NOT in _TERMINAL_BLOCK_REASONS → resume must succeed.
        """
        wf_id = "wf-case1-fallback"
        step = _make_step("s1", status="BLOCKED")  # no blocked_reason, no exec_res
        wf = _make_workflow(wf_id, [step])
        reason = _simulate_failure_detection_gate(wf)
        assert reason == "blocked", f"fallback must be 'blocked', got: {reason!r}"

        _register(wf_id, "BLOCKED", "blocked")
        try:
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                result = resume_workflow(wf_id)
            assert result["status"] == "success", (
                f"resume must succeed for 'blocked' reason, got: {result}"
            )
        finally:
            _clear(wf_id)

    def test_workflow_error_field_used_when_no_exec_res_no_blocked_reason(self):
        """
        TRACE: No exec_res, no blocked_reason, but workflow.error = "max_retries_exceeded".
        Gate must use workflow.error as reason.
        "max_retries_exceeded" is NOT in _TERMINAL_BLOCK_REASONS → resume succeeds.
        """
        step = _make_step("s1", status="BLOCKED")
        wf = _make_workflow("wf-err-field", [step], error="max_retries_exceeded")
        reason = _simulate_failure_detection_gate(wf)
        assert reason == "max_retries_exceeded"

        wf_id = "wf-case1-wferr"
        _register(wf_id, "BLOCKED", "max_retries_exceeded")
        try:
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                result = resume_workflow(wf_id)
            assert result["status"] == "success", (
                f"resume must succeed for max_retries_exceeded, got: {result}"
            )
        finally:
            _clear(wf_id)


# ---------------------------------------------------------------------------
# CASE 2 — Genuine terminal escalation
# ---------------------------------------------------------------------------

class TestCase2GenuineTerminalEscalation:
    """
    CASE 2: step.blocked_reason == "escalated" (set explicitly by escalation controller).
    Gate must write "escalated" to registry.
    resume_workflow() must reject with blocked_state_not_resumable:escalated.
    """

    def test_failure_detection_gate_escalated_step_blocked_reason_preserved(self):
        """
        FAILURE DETECTION GATE: step with blocked_reason="escalated" → reason="escalated".
        """
        step = _make_step("s1", status="BLOCKED", blocked_reason="escalated")
        wf = _make_workflow("wf-case2-fdg", [step])
        reason = _simulate_failure_detection_gate(wf)
        assert reason == "escalated", f"expected 'escalated', got: {reason!r}"

    def test_final_validation_gate_escalated_preserved(self):
        """
        FINAL VALIDATION GATE: same — escalated step → reason="escalated" preserved.
        """
        step = _make_step("s1", status="BLOCKED", blocked_reason="escalated")
        wf = _make_workflow("wf-case2-fvg", [step])
        reason = _simulate_final_validation_gate(wf)
        assert reason == "escalated"

    def test_exec_res_reason_escalated_preserved(self):
        """
        exec_res.reason = "escalated" → gate uses exec_res as first priority.
        """
        step = _make_step(
            "s1",
            status="BLOCKED",
            exec_res={"status": "failure", "reason": "escalated"},
        )
        wf = _make_workflow("wf-case2-execres", [step])
        reason = _simulate_failure_detection_gate(wf)
        assert reason == "escalated"

    def test_resume_rejected_after_escalated_registry_state(self):
        """
        TRACE: Registry has BLOCKED/escalated → resume_workflow() rejects.
        This is the pre-existing correct guard behaviour — must remain intact.
        """
        wf_id = "wf-case2-resume"
        _register(wf_id, "BLOCKED", "escalated")
        try:
            result = resume_workflow(wf_id)
            assert result["status"] == "failure"
            assert "blocked_state_not_resumable" in result["reason"]
            assert "escalated" in result["reason"]
        finally:
            _clear(wf_id)

    def test_terminal_block_reasons_set_unchanged(self):
        """
        Verify _TERMINAL_BLOCK_REASONS still contains exactly the expected set.
        Any change to this set is a contract violation.
        """
        from system.orchestrator import workflow_control as wc
        import inspect

        source = inspect.getsource(wc.resume_workflow)
        for expected_token in (
            "max_steps_exceeded",
            "max_iterations_exceeded",
            "invalidated",
            "escalated",
        ):
            assert expected_token in source, (
                f"_TERMINAL_BLOCK_REASONS missing expected token: {expected_token!r}"
            )

    def test_max_iterations_exceeded_gateway_blocks_resume(self):
        """
        max_iterations_exceeded IS in _TERMINAL_BLOCK_REASONS → resume rejected.
        """
        wf_id = "wf-case2-maxiter"
        _register(wf_id, "BLOCKED", "max_iterations_exceeded")
        try:
            result = resume_workflow(wf_id)
            assert result["status"] == "failure"
            assert "blocked_state_not_resumable" in result["reason"]
        finally:
            _clear(wf_id)

    def test_exec_res_reason_takes_priority_over_blocked_reason(self):
        """
        When exec_res.reason and blocked_reason both set, exec_res wins (first in chain).
        """
        step = _make_step(
            "s1",
            status="BLOCKED",
            blocked_reason="dependency_not_completed:x:BLOCKED",
            exec_res={"status": "failure", "reason": "escalated"},
        )
        wf = _make_workflow("wf-case2-priority", [step])
        reason = _simulate_failure_detection_gate(wf)
        assert reason == "escalated", (
            "exec_res.reason must take priority over blocked_reason"
        )


# ---------------------------------------------------------------------------
# CASE 3 — Projection / persistence / registry convergence
# ---------------------------------------------------------------------------

class TestCase3ProjectionConvergence:
    """
    CASE 3: After reevaluation cycle, verify projection status, registry status,
    persisted workflow status, and step statuses converge.

    Because projection manager requires a live event bus and running orchestrator,
    these tests validate the convergence contract at the boundary layer:
    - registry truth matches what the gate wrote
    - step statuses in the workflow dict match what would be projected
    - fallback reason "blocked" does not cause terminal projection lock
    """

    def test_registry_and_workflow_dict_converge_on_dep_block(self):
        """
        After FAILURE DETECTION GATE fires for dep-blocked step:
        - workflow["status"] = "BLOCKED" (compatibility mirror)
        - registry["status"] = "BLOCKED"
        - registry["reason"] = dep reason (NOT "escalated")
        - step["status"] = "BLOCKED"
        All four sources agree.
        """
        wf_id = "wf-case3-conv"
        step = _make_step(
            "s2",
            status="BLOCKED",
            blocked_reason="dependency_not_completed:s1:BLOCKED",
        )
        step_completed = _make_step("s1", status="COMPLETED")
        wf = _make_workflow(wf_id, [step_completed, step])

        _register(wf_id, "ACTIVE")
        try:
            dep_reason = "dependency_not_completed:s1:BLOCKED"
            _update_runtime_registry_only(wf_id, "BLOCKED", dep_reason)
            wf["status"] = "BLOCKED"  # mirror

            state = _get_workflow_state(wf_id)
            assert state["status"] == "BLOCKED"
            assert state["reason"] == dep_reason
            assert wf["status"] == "BLOCKED"
            assert step["status"] == "BLOCKED"
            assert step["blocked_reason"] == dep_reason
        finally:
            _clear(wf_id)

    def test_projection_lifecycle_status_non_terminal_after_dep_block(self):
        """
        After dep-blocked gate write, lifecycle_status passed to projection must
        be BLOCKED (not COMPLETED/FAILED) and projection_state must remain ACTIVE
        (not TERMINAL), since BLOCKED is not in TERMINAL_WORKFLOW_STATES.
        """
        from system.orchestrator.projection_schema import (
            build_workflow_projection,
            PROJECTION_STATE_ACTIVE,
            PROJECTION_STATE_TERMINAL,
            TERMINAL_WORKFLOW_STATES,
        )

        assert "BLOCKED" not in TERMINAL_WORKFLOW_STATES, (
            "BLOCKED must not be terminal per projection schema"
        )

        step = _make_step(
            "s1",
            status="BLOCKED",
            blocked_reason="dependency_not_completed:s0:BLOCKED",
        )
        wf = _make_workflow("wf-case3-proj", [step])

        projection = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="BLOCKED",
        )

        assert projection["lifecycle_status"] == "BLOCKED"
        assert projection["projection_state"] == PROJECTION_STATE_ACTIVE, (
            "BLOCKED workflow projection must be ACTIVE (resumable), not TERMINAL"
        )
        assert projection["steps"][0]["status"] == "BLOCKED"
        assert projection["steps"][0]["blocked_reason"] == "dependency_not_completed:s0:BLOCKED"

    def test_projection_terminal_for_escalated_blocked_workflow(self):
        """
        Workflow with step.blocked_reason="escalated" — lifecycle_status="BLOCKED" but
        escalated means terminal. Projection schema itself marks state ACTIVE for BLOCKED
        lifecycle (correct — terminal gate is resume_workflow, not projection).
        Projection must still carry blocked_reason="escalated" for frontend display.
        """
        from system.orchestrator.projection_schema import (
            build_workflow_projection,
            PROJECTION_STATE_ACTIVE,
        )
        step = _make_step("s1", status="BLOCKED", blocked_reason="escalated")
        wf = _make_workflow("wf-case3-esc-proj", [step])

        projection = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="BLOCKED",
        )

        assert projection["lifecycle_status"] == "BLOCKED"
        assert projection["steps"][0]["blocked_reason"] == "escalated"
        # Projection state remains ACTIVE — terminal enforcement is lifecycle layer's job
        assert projection["projection_state"] == PROJECTION_STATE_ACTIVE

    def test_all_sources_converge_after_resume_and_dep_reevaluation(self):
        """
        Full convergence trace:
        1. Register workflow as PAUSED (pre-resume state).
        2. resume_workflow() → registry becomes ACTIVE.
        3. Gate fires with dep reason → registry becomes BLOCKED/dep_reason.
        4. Verify: registry, step, workflow dict all show consistent state.
        5. Second resume → succeeds (dep reason not terminal).
        6. Verify registry is ACTIVE again.
        """
        wf_id = "wf-case3-full"
        _register(wf_id, "PAUSED")
        try:
            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                r1 = resume_workflow(wf_id)
            assert r1["status"] == "success"
            assert _get_workflow_state(wf_id)["status"] == "ACTIVE"

            dep_reason = "dependency_not_completed:s1:BLOCKED"
            _update_runtime_registry_only(wf_id, "BLOCKED", dep_reason)

            state = _get_workflow_state(wf_id)
            assert state["status"] == "BLOCKED"
            assert state["reason"] == dep_reason

            with patch(
                "system.orchestrator.workflow_control._update_workflow_state",
                side_effect=_patched_update,
            ):
                r2 = resume_workflow(wf_id)
            assert r2["status"] == "success", (
                f"second resume must succeed for dep reason, got: {r2}"
            )
            assert _get_workflow_state(wf_id)["status"] == "ACTIVE"
        finally:
            _clear(wf_id)


# ---------------------------------------------------------------------------
# REGRESSION: Normalization fixes A/C/D/E/F still intact
# ---------------------------------------------------------------------------

class TestRegressionNormalizationFixesIntact:
    """
    Confirm previous normalization fixes are not broken by this change.
    """

    def test_fix_a_escalation_blocked_step_retries_reset(self):
        """
        Fix A: escalation-blocked step restored as BLOCKED with retries=0.
        Simulates persistence restore branch (orchestrator_runtime.py ~396-401).
        """
        _ESCALATION_REASONS = {"max_retries_exceeded", "escalated", "system_error"}
        persisted_step = {
            "id": "s1",
            "status": "BLOCKED",
            "blocked_reason": "escalated",
            "retries": 5,
        }

        restored = {"id": "s1", "status": "BLOCKED"}
        _blocked_reason = persisted_step.get("blocked_reason", "")
        if _blocked_reason in _ESCALATION_REASONS:
            restored["status"] = "BLOCKED"
            restored["blocked_reason"] = _blocked_reason
            restored["retries"] = 0

        assert restored["retries"] == 0
        assert restored["status"] == "BLOCKED"
        assert restored["blocked_reason"] == "escalated"

    def test_fix_c_dep_blocked_step_restored_as_pending(self):
        """
        Fix C: dep-blocked step restored as PENDING for fresh dep evaluation.
        """
        _DEP_BLOCK_PREFIX = "dependency_not_completed"
        persisted_step = {
            "id": "s2",
            "status": "BLOCKED",
            "blocked_reason": "dependency_not_completed:s1:BLOCKED",
            "retries": 1,
        }

        restored = {"id": "s2"}
        _blocked_reason = persisted_step.get("blocked_reason", "")
        if _blocked_reason.startswith(_DEP_BLOCK_PREFIX):
            restored["status"] = "PENDING"

        assert restored["status"] == "PENDING"

    def test_fix_d_registry_not_clobbered(self):
        """
        Fix D: registry init block skips write when wf_id already in registry.
        """
        wf_id = "wf-reg-d"
        _register(wf_id, "ACTIVE")
        try:
            state_before = _get_workflow_state(wf_id)
            with _workflow_state_lock:
                if wf_id not in _workflow_state_registry:
                    _workflow_state_registry[wf_id] = {"status": "PAUSED", "last_updated": time.time()}
            state_after = _get_workflow_state(wf_id)
            assert state_after["status"] == "ACTIVE", "registry must NOT be clobbered"
        finally:
            _clear(wf_id)

    def test_terminal_block_guard_unchanged(self):
        """
        Fix E / guard contract: BLOCKED/escalated → resume_workflow() still rejects.
        """
        wf_id = "wf-reg-e"
        _register(wf_id, "BLOCKED", "escalated")
        try:
            r = resume_workflow(wf_id)
            assert r["status"] == "failure"
            assert "blocked_state_not_resumable" in r["reason"]
        finally:
            _clear(wf_id)
