"""
CATEGORY: REGRESSION
AUTHORITY_LAYER: Historical Bug Prevention
VALIDATES:
  - Lifecycle authority hotfix (BLOCKED_to_ACTIVE transition)
  - State transition enforcement
  - Pause/resume dependency handling
  - Lifecycle FSM correctness
ENTRYPOINT: direct workflow_control functions
DIRECT_INTERNAL_CALLS:
  - workflow_control._is_valid_state_transition
  - workflow_control._update_workflow_state
  - workflow_control._update_runtime_registry_only
  - workflow_control._workflow_state_registry
  - workflow_control.pause_workflow
  - workflow_control.resume_workflow
  - workflow_control.request_step_transition
  - execution_scheduler.create_execution_group
  - execution_scheduler._check_dependencies_satisfied
  - conflict_detector.ConflictDetector
MONKEYPATCH_USAGE:
  - workflow_control._update_workflow_state (side_effect for registry-only update)
MOCKING_POLICY: AS_PER_HISTORICAL_BUG
TEST_INTENT: HISTORICAL_BUG_PREVENTION
ARCHITECTURAL_SCOPE: Lifecycle authority corrections

HISTORICAL_FIX: Lifecycle authority hotfix (pause/resume BLOCKED transition)
REGRESSION_REASON: Prevent recurrence of lifecycle authority drift
PRESERVATION_PRIORITY: HIGH

---

LIFECYCLE AUTHORITY HOTFIX — TEST SUITE

Tests:
  1. Pause/Resume Dependency Test  — reproduces invalid_transition:BLOCKED_to_ACTIVE failure
  2. Lifecycle Enforcement Tests   — FSM validation via request_step_transition
  3. Regression Tests              — retries, approvals, dependency release, projections

Per STATE_TRANSITIONS_CONTRACT_V1 and LIFECYCLE_AUTHORITY_CONTRACT_V1.
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest.mock import patch
from system.orchestrator.workflow_control import (
    _is_valid_state_transition,
    _update_workflow_state,
    _update_runtime_registry_only,
    _get_workflow_state,
    _workflow_state_registry,
    pause_workflow,
    resume_workflow,
    request_step_transition,
    _INTERNAL_TRANSITIONS,
)
from system.orchestrator.execution_scheduler import (
    create_execution_group,
    _check_dependencies_satisfied,
)
from system.orchestrator.conflict_detector import ConflictDetector


# ===========================================================================
# HELPERS
# ===========================================================================

def _make_step(sid, status="PENDING", depends_on=None, blocked_reason=None):
    s = {
        "id": sid,
        "status": status,
        "type": "EXECUTE_API",
        "purpose": f"step {sid}",
        "tool_call": f"USE_TOOL: noop",
        "expected_outcome": "ok",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "retries": 0,
        "max_retries": 3,
        "depends_on": depends_on or [],
    }
    if blocked_reason:
        s["blocked_reason"] = blocked_reason
    return s


def _make_workflow(steps, wf_id="wf-test"):
    return {"id": wf_id, "name": "test", "status": "ACTIVE", "steps": steps}


_passed = 0
_failed = 0
_traces = []


def check(label, cond, detail=""):
    global _passed, _failed
    marker = "[PASS]" if cond else "[FAIL]"
    msg = f"  {marker} {label}"
    if detail:
        msg += f"\n         detail: {detail}"
    print(msg)
    _traces.append({"label": label, "pass": cond, "detail": detail})
    if cond:
        _passed += 1
    else:
        _failed += 1


# ===========================================================================
# 1. PAUSE/RESUME DEPENDENCY TEST
# Reproduces: invalid_transition:BLOCKED_to_ACTIVE
# ===========================================================================

def test_pause_resume_dependency_flow():
    print("\n" + "=" * 60)
    print("  TEST 1 — Pause/Resume Dependency Flow")
    print("=" * 60)

    wf_id = "wf-pause-resume-dep"

    # Mock _update_workflow_state to return True (avoids persistence dependency in unit tests).
    # The registry update (authoritative) still happens inside the real function before the
    # persistence mirror path — we only skip the persistence write.
    with patch("system.orchestrator.workflow_control._update_workflow_state",
               side_effect=lambda wid, st, reason=None: _update_runtime_registry_only(wid, st, reason)):

        # Seed registry as PAUSED (simulates: ACTIVE → pause → registry=PAUSED)
        _workflow_state_registry[wf_id] = {"status": "PAUSED", "last_updated": 0.0, "reason": "user_pause"}

        result = resume_workflow(wf_id)
        check(
            "1a: resume from PAUSED succeeds",
            result["status"] == "success",
            str(result)
        )
        check(
            "1b: new_state=ACTIVE after PAUSED resume",
            result.get("new_state") == "ACTIVE",
            str(result)
        )

        # Reproduce the exact failure: registry = BLOCKED (dependency_wait)
        _workflow_state_registry[wf_id] = {
            "status": "BLOCKED",
            "last_updated": 0.0,
            "reason": "dependency_not_completed:step1:PENDING"
        }
        result2 = resume_workflow(wf_id)
        check(
            "1c: resume from BLOCKED (dependency_wait) now succeeds — HOTFIX",
            result2["status"] == "success",
            str(result2)
        )
        check(
            "1d: new_state=ACTIVE after BLOCKED resume",
            result2.get("new_state") == "ACTIVE",
            str(result2)
        )
        check(
            "1e: previous_state=BLOCKED recorded correctly",
            result2.get("previous_state") == "BLOCKED",
            str(result2)
        )

        # Terminal escalation blocks must NOT be resumable
        for terminal_reason in ("max_steps_exceeded", "max_iterations_exceeded", "escalated", "invalidated"):
            _workflow_state_registry[wf_id] = {
                "status": "BLOCKED",
                "last_updated": 0.0,
                "reason": terminal_reason
            }
            r = resume_workflow(wf_id)
            check(
                f"1f: BLOCKED({terminal_reason}) rejected — not resumable",
                r["status"] == "failure" and "not_resumable" in r.get("reason", ""),
                str(r)
            )

        # approval_required BLOCKED is resumable
        _workflow_state_registry[wf_id] = {
            "status": "BLOCKED",
            "last_updated": 0.0,
            "reason": "approval_required"
        }
        r_approval = resume_workflow(wf_id)
        check(
            "1g: BLOCKED(approval_required) is resumable",
            r_approval["status"] == "success",
            str(r_approval)
        )

        # Non-resumable base states
        for bad_state in ("COMPLETED", "FAILED", "QUEUED", "ACTIVE"):
            _workflow_state_registry[wf_id] = {"status": bad_state, "last_updated": 0.0}
            r = resume_workflow(wf_id)
            check(
                f"1h: resume from {bad_state} rejected (not PAUSED/BLOCKED)",
                r["status"] == "failure",
                str(r)
            )


# ===========================================================================
# 2. LIFECYCLE ENFORCEMENT TESTS — request_step_transition
# ===========================================================================

def test_lifecycle_enforcement():
    print("\n" + "=" * 60)
    print("  TEST 2 — Lifecycle Enforcement (request_step_transition)")
    print("=" * 60)

    # --- 2A: Valid public FSM transitions ---
    valid_cases = [
        ("PENDING",   "ACTIVE",    False, "PENDING→ACTIVE"),
        ("ACTIVE",    "BLOCKED",   False, "ACTIVE→BLOCKED"),
        ("ACTIVE",    "COMPLETED", False, "ACTIVE→COMPLETED"),
        ("ACTIVE",    "FAILED",    False, "ACTIVE→FAILED"),
        ("ACTIVE",    "PAUSED",    False, "ACTIVE→PAUSED"),
        ("BLOCKED",   "ACTIVE",    False, "BLOCKED→ACTIVE"),
        ("BLOCKED",   "FAILED",    False, "BLOCKED→FAILED"),
        ("PAUSED",    "ACTIVE",    False, "PAUSED→ACTIVE"),
        ("PAUSED",    "FAILED",    False, "PAUSED→FAILED"),
        ("RETRY",     "ACTIVE",    True,  "RETRY→ACTIVE (internal)"),
        ("BLOCKED",   "PENDING",   True,  "BLOCKED→PENDING (internal dep-release)"),
    ]
    for current, target, internal, label in valid_cases:
        step = _make_step("s-valid", status=current)
        ok = request_step_transition(step, target, reason="test", _internal=internal)
        check(
            f"2A valid: {label}",
            ok and step["status"] == target,
            f"ok={ok} step.status={step.get('status')}"
        )

    # --- 2B: Invalid transitions rejected ---
    invalid_cases = [
        ("COMPLETED", "ACTIVE",   False, "COMPLETED→ACTIVE (terminal)"),
        ("FAILED",    "ACTIVE",   False, "FAILED→ACTIVE (terminal)"),
        ("BLOCKED",   "COMPLETED",False, "BLOCKED→COMPLETED (must go through ACTIVE)"),
        ("PENDING",   "COMPLETED",False, "PENDING→COMPLETED (skipped ACTIVE)"),
        ("COMPLETED", "PENDING",  False, "COMPLETED→PENDING (terminal)"),
        ("BLOCKED",   "PENDING",  False, "BLOCKED→PENDING without _internal flag"),
    ]
    for current, target, internal, label in invalid_cases:
        step = _make_step("s-invalid", status=current)
        ok = request_step_transition(step, target, reason="test", _internal=internal)
        check(
            f"2B invalid: {label} — rejected",
            not ok and step["status"] == current,
            f"ok={ok} step.status={step.get('status')}"
        )

    # --- 2C: validate=False allows initialization bypass ---
    step = _make_step("s-init", status="PENDING")
    ok = request_step_transition(step, "COMPLETED", reason="init_bypass", validate=False)
    check(
        "2C: validate=False bypasses FSM (initialization path only)",
        ok and step["status"] == "COMPLETED",
        f"ok={ok}"
    )

    # --- 2D: blocked_reason set correctly on BLOCKED transition ---
    step = _make_step("s-block", status="ACTIVE")
    request_step_transition(step, "BLOCKED", reason="approval_required")
    check(
        "2D: blocked_reason set on BLOCKED transition",
        step.get("blocked_reason") == "approval_required",
        str(step.get("blocked_reason"))
    )

    # --- 2E: blocked_reason cleared on release from BLOCKED ---
    step = _make_step("s-release", status="BLOCKED", blocked_reason="dep_not_complete")
    request_step_transition(step, "ACTIVE", reason="user_resume")
    check(
        "2E: blocked_reason cleared on BLOCKED→ACTIVE",
        "blocked_reason" not in step,
        str(step.get("blocked_reason"))
    )

    # --- 2F: BLOCKED→PENDING internal clears blocked_reason ---
    step = _make_step("s-dep-release", status="BLOCKED", blocked_reason="dep_not_complete")
    request_step_transition(step, "PENDING", reason="dep_satisfied", _internal=True)
    check(
        "2F: blocked_reason cleared on BLOCKED→PENDING dep-release",
        step.get("status") == "PENDING" and "blocked_reason" not in step,
        f"status={step.get('status')} blocked_reason={step.get('blocked_reason')}"
    )


# ===========================================================================
# 3. DEPENDENCY RELEASE FLOW
# PENDING → BLOCKED → PENDING → ACTIVE via scheduler
# ===========================================================================

def test_dependency_release_flow():
    print("\n" + "=" * 60)
    print("  TEST 3 — Dependency Release Flow (PENDING→BLOCKED→PENDING→ACTIVE)")
    print("=" * 60)

    wf_id = "wf-dep-release"
    s1 = _make_step("s1")
    s2 = _make_step("s2", depends_on=["s1"])
    s3 = _make_step("s3", depends_on=["s2"])
    workflow = _make_workflow([s1, s2, s3], wf_id)
    step_states = {s["id"]: s["status"] for s in workflow["steps"]}
    steps_map = {s["id"]: s for s in workflow["steps"]}

    # --- 3A: Initial — s1 schedulable, s2/s3 blocked ---
    sat_s1, _ = _check_dependencies_satisfied(s1, step_states, steps_map)
    sat_s2, reason_s2 = _check_dependencies_satisfied(s2, step_states, steps_map)
    sat_s3, reason_s3 = _check_dependencies_satisfied(s3, step_states, steps_map)
    check("3A: s1 deps satisfied (no deps)", sat_s1)
    check("3A: s2 deps NOT satisfied (s1 PENDING)", not sat_s2, reason_s2)
    check("3A: s3 deps NOT satisfied (s2 PENDING)", not sat_s3, reason_s3)

    # --- 3B: Simulate s1 COMPLETE — s2 should become schedulable ---
    s1["status"] = "COMPLETED"
    s2["status"] = "BLOCKED"
    s2["blocked_reason"] = "dependency_not_completed:s1:PENDING"
    step_states = {s["id"]: s["status"] for s in workflow["steps"]}

    sat_s2_after, _ = _check_dependencies_satisfied(s2, step_states, steps_map)
    check("3B: s2 deps satisfied after s1 COMPLETE", sat_s2_after)

    # Simulate scheduler pre-flight using request_step_transition
    ok = request_step_transition(s2, "PENDING", reason="dep_satisfied", _internal=True)
    check("3B: BLOCKED→PENDING via request_step_transition succeeds", ok)
    check("3B: s2 status is PENDING after dep release", s2["status"] == "PENDING")
    check("3B: s2 blocked_reason cleared after dep release", "blocked_reason" not in s2)

    # --- 3C: s2 progresses PENDING → ACTIVE → COMPLETE → s3 releases ---
    ok2 = request_step_transition(s2, "ACTIVE", reason="scheduler_dispatch")
    check("3C: s2 PENDING→ACTIVE via authority", ok2)
    ok3 = request_step_transition(s2, "COMPLETED", reason="governance_complete")
    check("3C: s2 ACTIVE→COMPLETED via authority", ok3)

    step_states = {s["id"]: s["status"] for s in workflow["steps"]}
    sat_s3_after, _ = _check_dependencies_satisfied(s3, step_states, steps_map)
    check("3C: s3 deps satisfied after s2 COMPLETE", sat_s3_after)

    # --- 3D: Full scheduler group formation ---
    _workflow_state_registry[wf_id] = {"status": "ACTIVE", "last_updated": 0.0}
    cd = ConflictDetector()
    cd.register_workflow(wf_id)

    # Set s3 to BLOCKED to exercise pre-flight release
    s3["status"] = "BLOCKED"
    s3["blocked_reason"] = "dependency_not_completed:s2:ACTIVE"
    step_states = {s["id"]: s["status"] for s in workflow["steps"]}

    group = create_execution_group(workflow, step_states, cd, wf_id)
    check(
        "3D: scheduler forms group for s3 after dep release",
        group is not None and "s3" in group.get("steps", []),
        str(group)
    )
    check(
        "3D: s3 status released to PENDING by pre-flight",
        s3["status"] == "PENDING",
        f"s3.status={s3['status']}"
    )


# ===========================================================================
# 4. REGRESSION TESTS
# ===========================================================================

def test_regression_retry():
    print("\n" + "=" * 60)
    print("  TEST 4 — Regression: Retry Flow")
    print("=" * 60)

    # RETRY state → ACTIVE is allowed internally (scheduler dispatch)
    step = _make_step("s-retry", status="FAILED")

    # retry_step sets status=RETRY directly — this is workflow_control authority
    step["status"] = "RETRY"  # as done by retry_step()
    step["retries"] = 0

    ok = request_step_transition(step, "ACTIVE", reason="retry_dispatch", _internal=True)
    check("4A: RETRY→ACTIVE (internal) via authority", ok and step["status"] == "ACTIVE")

    # RETRY→BLOCKED (approval during retry)
    step2 = _make_step("s-retry2", status="RETRY")
    ok2 = request_step_transition(step2, "BLOCKED", reason="approval_required")
    check("4B: RETRY→BLOCKED via authority", ok2 and step2["status"] == "BLOCKED")

    # RETRY→FAILED (exhausted)
    step3 = _make_step("s-retry3", status="RETRY")
    ok3 = request_step_transition(step3, "FAILED", reason="max_retries_exceeded")
    check("4C: RETRY→FAILED via authority", ok3 and step3["status"] == "FAILED")


def test_regression_approval_flow():
    print("\n" + "=" * 60)
    print("  TEST 5 — Regression: Approval Flow (BLOCKED→ACTIVE)")
    print("=" * 60)

    step = _make_step("s-approval", status="BLOCKED", blocked_reason="approval_required")

    # Approval granted — BLOCKED→ACTIVE is valid in public FSM
    ok = request_step_transition(step, "ACTIVE", reason="approval_granted")
    check("5A: BLOCKED→ACTIVE (approval) accepted by FSM", ok)
    check("5B: step.status=ACTIVE after approval", step["status"] == "ACTIVE")
    check("5C: blocked_reason cleared after approval", "blocked_reason" not in step)

    # Approval denied — step stays BLOCKED
    step2 = _make_step("s-approval2", status="BLOCKED", blocked_reason="approval_required")
    ok2 = request_step_transition(step2, "FAILED", reason="approval_denied")
    check("5D: BLOCKED→FAILED (denial) accepted", ok2 and step2["status"] == "FAILED")


def test_regression_fsm_completeness():
    print("\n" + "=" * 60)
    print("  TEST 6 — Regression: FSM Completeness")
    print("=" * 60)

    transitions = [
        ("QUEUED",    "ACTIVE",    True),
        ("ACTIVE",    "PAUSED",    True),
        ("ACTIVE",    "BLOCKED",   True),
        ("ACTIVE",    "COMPLETED", True),
        ("ACTIVE",    "FAILED",    True),
        ("PAUSED",    "ACTIVE",    True),
        ("PAUSED",    "FAILED",    True),
        ("BLOCKED",   "ACTIVE",    True),
        ("BLOCKED",   "FAILED",    True),
        ("COMPLETED", "ACTIVE",    False),
        ("FAILED",    "ACTIVE",    False),
        ("BLOCKED",   "COMPLETED", False),
        ("QUEUED",    "COMPLETED", False),
        ("COMPLETED", "FAILED",    False),
        ("FAILED",    "COMPLETED", False),
    ]
    for current, target, expected in transitions:
        result = _is_valid_state_transition(current, target)
        check(
            f"6: FSM {current}→{target} expected={'VALID' if expected else 'INVALID'}",
            result == expected,
            f"got={result}"
        )

    # Internal-only transitions: NOT in public FSM but allowed via _internal=True
    internal_only = [("BLOCKED", "PENDING")]
    for current, target in internal_only:
        public_valid = _is_valid_state_transition(current, target)
        in_set = (current, target) in _INTERNAL_TRANSITIONS
        check(
            f"6: ({current},{target}) is internal-only (not in public FSM, IS in _INTERNAL_TRANSITIONS)",
            not public_valid and in_set,
            f"public_valid={public_valid} in_internal={in_set}"
        )

    # Transitions now in public FSM (previously assumed internal-only, now promoted)
    # ACTIVE→PENDING: plan edit restart promoted per PLAN_CONTROL_CONTRACT_V1 §MID-EXECUTION EDIT RULES
    # ACTIVE→ACTIVE restart is obsoleted by ACTIVE→PENDING (canonical path); no longer in internal set
    promoted_to_public = [("PENDING", "ACTIVE"), ("PENDING", "BLOCKED"), ("RETRY", "ACTIVE"), ("ACTIVE", "PENDING")]
    for current, target in promoted_to_public:
        public_valid = _is_valid_state_transition(current, target)
        check(
            f"6: ({current},{target}) is now in public FSM — FSM gap resolved",
            public_valid,
            f"public_valid={public_valid}"
        )


def test_regression_scheduler_uses_authority():
    print("\n" + "=" * 60)
    print("  TEST 7 — Regression: Scheduler Routes Through Authority")
    print("=" * 60)

    # Verify execution_scheduler imports request_step_transition from workflow_control
    import importlib
    import ast, inspect
    import system.orchestrator.execution_scheduler as sched_mod
    src = inspect.getsource(sched_mod)

    check(
        "7A: execution_scheduler imports request_step_transition",
        "request_step_transition" in src,
        "import present in source"
    )
    check(
        "7B: execution_scheduler no longer has bare step[\"status\"] = in dep-release paths",
        # The only remaining bare step["status"] = should NOT appear in the dep-reeval block
        # We check that all four old mutation lines are gone from the two reeval loops
        src.count('step["status"] = "PENDING"') == 0 and
        src.count("step['status'] = 'PENDING'") == 0,
        f"bare PENDING mutations found: {src.count('step[\"status\"] = \"PENDING\"')}"
    )
    check(
        "7C: execution_scheduler no longer has bare step[\"status\"] = \"BLOCKED\" in dep-reeval",
        # dep-reeval BLOCKED mutations replaced; the ones in parallel_executor are separate file
        "request_step_transition(step, \"BLOCKED\"" in src or
        "request_step_transition(step, 'BLOCKED'" in src,
        "request_step_transition(step, BLOCKED) found"
    )


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    print("\n" + "=" * 60)
    print("  LIFECYCLE AUTHORITY HOTFIX — TEST SUITE")
    print("=" * 60)

    tests = [
        test_pause_resume_dependency_flow,
        test_lifecycle_enforcement,
        test_dependency_release_flow,
        test_regression_retry,
        test_regression_approval_flow,
        test_regression_fsm_completeness,
        test_regression_scheduler_uses_authority,
    ]

    for t in tests:
        try:
            t()
        except Exception as e:
            print(f"\n  [ERROR] {t.__name__}: {e}")
            traceback.print_exc()
            global _failed
            _failed += 1

    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Passed: {_passed}")
    print(f"  Failed: {_failed}")
    print(f"  Total:  {_passed + _failed}")

    print("\n" + "=" * 60)
    print("  TRANSITION TRACES")
    print("=" * 60)
    for t in _traces:
        marker = "[PASS]" if t["pass"] else "[FAIL]"
        print(f"  {marker} {t['label']}")
        if t["detail"] and not t["pass"]:
            print(f"         {t['detail']}")

    return _failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
