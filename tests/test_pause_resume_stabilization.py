"""
PAUSE / RESUME LIFECYCLE STABILIZATION — TEST SUITE
Phase 1A

Validates ACTIVE ↔ PAUSED transitions for:
  - Basic pause/resume FSM correctness
  - BLOCKED dependency-wait step handling during pause/resume
  - Scheduler authoritative-state read after resume
  - Resume endpoint registry-vs-dict authority check
  - No escalation of PAUSED state to terminal BLOCKED
  - Projection continuity across pause/resume

Architecture authorities:
  HAND_ARCHITECTURE_V2 §4, §7, §12
  SYSTEM_GOALS_V2 §12, §14

Test categories:
  1. FSM correctness
  2. Scheduler guard (fix 3)
  3. Registry authority on resume (fix 1)
  4. Async re-entry shape (fix 2)
  5. Dependency-blocked chain pause/resume
  6. Adversarial / edge cases
"""

import os
import sys
import time
import threading
import traceback

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_passed = 0
_failed = 0
_traces = []


def check(label, cond, detail=""):
    global _passed, _failed
    marker = "[PASS]" if cond else "[FAIL]"
    msg = f"  {marker} {label}"
    if detail and not cond:
        msg += f"\n         {detail}"
    print(msg)
    _traces.append({"label": label, "pass": cond, "detail": detail})
    if cond:
        _passed += 1
    else:
        _failed += 1


# ── import helpers ────────────────────────────────────────────────────────────

from system.orchestrator.workflow_control import (
    pause_workflow,
    resume_workflow,
    _update_workflow_state,
    _get_workflow_state,
    _is_valid_state_transition,
    _workflow_state_registry,
    _workflow_state_lock,
)
from system.orchestrator.execution_scheduler import create_execution_group, _get_workflow_state as sched_get_state
from system.orchestrator.conflict_detector import ConflictDetector


def _fresh_wf_id():
    import uuid
    return f"test_wf_{uuid.uuid4().hex[:12]}"


def _register(wf_id, status):
    _update_workflow_state(wf_id, status, "test_setup")


# =============================================================================
# TEST 1 — FSM CORRECTNESS
# =============================================================================

def test_fsm_correctness():
    print("\n" + "=" * 60)
    print("  TEST 1 — FSM Correctness")
    print("=" * 60)

    # 1A: ACTIVE → PAUSED is valid
    check("1A: ACTIVE→PAUSED valid in FSM",
          _is_valid_state_transition("ACTIVE", "PAUSED"))

    # 1B: PAUSED → ACTIVE is valid (resume)
    check("1B: PAUSED→ACTIVE valid in FSM",
          _is_valid_state_transition("PAUSED", "ACTIVE"))

    # 1C: PAUSED → FAILED is valid (stop)
    check("1C: PAUSED→FAILED valid in FSM",
          _is_valid_state_transition("PAUSED", "FAILED"))

    # 1D: PAUSED → BLOCKED is NOT valid (PAUSED is not an escalation path)
    check("1D: PAUSED→BLOCKED NOT valid in FSM",
          not _is_valid_state_transition("PAUSED", "BLOCKED"))

    # 1E: BLOCKED → ACTIVE is valid (dependency wait resolved)
    check("1E: BLOCKED→ACTIVE valid in FSM",
          _is_valid_state_transition("BLOCKED", "ACTIVE"))

    # 1F: COMPLETED → PAUSED is NOT valid (terminal)
    check("1F: COMPLETED→PAUSED NOT valid in FSM",
          not _is_valid_state_transition("COMPLETED", "PAUSED"))

    # 1G: FAILED → ACTIVE is NOT valid (terminal)
    check("1G: FAILED→ACTIVE NOT valid in FSM",
          not _is_valid_state_transition("FAILED", "ACTIVE"))


# =============================================================================
# TEST 2 — pause_workflow / resume_workflow against registry
# =============================================================================

def test_pause_resume_registry():
    print("\n" + "=" * 60)
    print("  TEST 2 — pause_workflow / resume_workflow registry")
    print("=" * 60)

    wf_id = _fresh_wf_id()
    _register(wf_id, "ACTIVE")

    # 2A: Pause from ACTIVE succeeds
    result = pause_workflow(wf_id)
    check("2A: pause_workflow returns success", result.get("status") == "success",
          str(result))
    check("2A: new_state is PAUSED", result.get("new_state") == "PAUSED")

    # 2B: Registry reflects PAUSED
    state = _get_workflow_state(wf_id)
    check("2B: registry state is PAUSED after pause",
          state and state.get("status") == "PAUSED",
          f"state={state}")

    # 2C: Pause again from PAUSED → rejected (not ACTIVE)
    result2 = pause_workflow(wf_id)
    check("2C: pause from PAUSED → rejected",
          result2.get("status") == "failure",
          str(result2))

    # 2D: Resume from PAUSED succeeds
    result3 = resume_workflow(wf_id)
    check("2D: resume_workflow returns success", result3.get("status") == "success",
          str(result3))
    check("2D: new_state is ACTIVE", result3.get("new_state") == "ACTIVE")

    # 2E: Registry reflects ACTIVE
    state2 = _get_workflow_state(wf_id)
    check("2E: registry state is ACTIVE after resume",
          state2 and state2.get("status") == "ACTIVE",
          f"state={state2}")

    # 2F: Resume again from ACTIVE → rejected (not PAUSED or BLOCKED)
    result4 = resume_workflow(wf_id)
    check("2F: resume from ACTIVE → rejected",
          result4.get("status") == "failure",
          str(result4))


# =============================================================================
# TEST 3 — Scheduler authoritative-state read (Fix 3)
# =============================================================================

def test_scheduler_authoritative_state():
    print("\n" + "=" * 60)
    print("  TEST 3 — Scheduler authoritative state read (Fix 3)")
    print("=" * 60)

    detector = ConflictDetector()

    # 3A: PAUSED workflow → scheduler must return None (no group)
    wf_id = _fresh_wf_id()
    _register(wf_id, "PAUSED")
    workflow = {
        "id": wf_id,
        "status": "PAUSED",   # in-memory dict says PAUSED
        "steps": [{"id": "s1", "status": "PENDING", "depends_on": [], "risk": "LOW", "type": "ANALYZE", "resource_targets": []}]
    }
    step_states = {"s1": "PENDING"}
    group = create_execution_group(workflow, step_states, detector, wf_id)
    check("3A: scheduler returns None when registry=PAUSED",
          group is None,
          f"group={group}")

    # 3B: After resume (registry → ACTIVE), same workflow + stale dict status "PAUSED" →
    # scheduler MUST now use registry (ACTIVE) and form a group
    _register(wf_id, "ACTIVE")
    # dict still says "PAUSED" (simulates the stale-dict scenario fixed by Fix 3)
    workflow["status"] = "PAUSED"
    group2 = create_execution_group(workflow, step_states, detector, wf_id)
    check("3B: scheduler forms group when registry=ACTIVE even if dict says PAUSED",
          group2 is not None,
          f"group={group2}")

    # 3C: Scheduler must return None when registry explicitly PAUSED (no false resume)
    _register(wf_id, "PAUSED")
    workflow["status"] = "ACTIVE"   # dict says ACTIVE, registry says PAUSED
    group3 = create_execution_group(workflow, step_states, detector, wf_id)
    check("3C: scheduler returns None when registry=PAUSED even if dict says ACTIVE",
          group3 is None,
          f"group={group3}")


# =============================================================================
# TEST 4 — Resume endpoint: registry authority check (Fix 1)
# =============================================================================

def test_resume_registry_authority():
    print("\n" + "=" * 60)
    print("  TEST 4 — Resume endpoint registry authority (Fix 1)")
    print("=" * 60)

    wf_id = _fresh_wf_id()

    # 4A: resume_workflow on non-existent workflow → failure
    result = resume_workflow("nonexistent_wf_" + wf_id)
    check("4A: resume of unknown workflow → failure",
          result.get("status") == "failure",
          str(result))

    # 4B: resume_workflow on PAUSED workflow → success, registry becomes ACTIVE
    _register(wf_id, "PAUSED")
    result2 = resume_workflow(wf_id)
    check("4B: resume_workflow from PAUSED → success",
          result2.get("status") == "success",
          str(result2))

    # 4C: authoritative registry reflects ACTIVE after resume
    state = _get_workflow_state(wf_id)
    check("4C: authoritative registry = ACTIVE after resume_workflow",
          state and state.get("status") == "ACTIVE",
          f"state={state}")

    # 4D: The Fix 1 code path: _get_workflow_state must return ACTIVE
    # (simulating the endpoint check that was previously using stale persistence dict)
    auth_check = _get_workflow_state(wf_id)
    check("4D: Fix-1 guard: _get_workflow_state returns ACTIVE status",
          auth_check and auth_check.get("status") == "ACTIVE",
          f"auth_check={auth_check}")


# =============================================================================
# TEST 5 — Dependency-blocked chain: pause/resume
# =============================================================================

def test_dependency_blocked_pause_resume():
    print("\n" + "=" * 60)
    print("  TEST 5 — Dependency-blocked chain pause/resume")
    print("=" * 60)

    detector = ConflictDetector()
    wf_id = _fresh_wf_id()
    _register(wf_id, "ACTIVE")

    # s1 is COMPLETED; s2 depends on s1 (should be schedulable)
    # s3 depends on s2 (still blocked)
    steps = [
        {"id": "s1", "status": "COMPLETED", "depends_on": [], "risk": "LOW", "type": "ANALYZE", "resource_targets": []},
        {"id": "s2", "status": "PENDING",   "depends_on": ["s1"], "risk": "LOW", "type": "ANALYZE", "resource_targets": []},
        {"id": "s3", "status": "PENDING",   "depends_on": ["s2"], "risk": "LOW", "type": "ANALYZE", "resource_targets": []},
    ]
    workflow = {"id": wf_id, "status": "ACTIVE", "steps": steps}
    step_states = {s["id"]: s["status"] for s in steps}

    # 5A: Scheduler picks s2 (s1 complete, s3 blocked)
    group = create_execution_group(workflow, step_states, detector, wf_id)
    check("5A: scheduler picks s2 when s1=COMPLETED",
          group is not None and "s2" in group.get("steps", []),
          f"group={group}")

    # 5B: Pause workflow mid-chain
    pause_workflow(wf_id)
    group_paused = create_execution_group(workflow, step_states, detector, wf_id)
    check("5B: scheduler returns None when paused mid-chain",
          group_paused is None,
          f"group={group_paused}")

    # 5C: Resume — s2 still PENDING, should be schedulable again
    resume_workflow(wf_id)
    workflow["status"] = "ACTIVE"  # sync in-memory dict after resume
    group_resumed = create_execution_group(workflow, step_states, detector, wf_id)
    check("5C: scheduler resumes scheduling s2 after resume",
          group_resumed is not None and "s2" in group_resumed.get("steps", []),
          f"group={group_resumed}")

    # 5D: BLOCKED step becomes runnable when dependency completes (after resume)
    steps[1]["status"] = "COMPLETED"   # s2 completes
    step_states["s2"] = "COMPLETED"
    group_s3 = create_execution_group(workflow, step_states, detector, wf_id)
    check("5D: s3 becomes schedulable after s2 completes post-resume",
          group_s3 is not None and "s3" in group_s3.get("steps", []),
          f"group={group_s3}")


# =============================================================================
# TEST 6 — PAUSED ≠ terminal BLOCKED escalation
# =============================================================================

def test_paused_not_escalation():
    print("\n" + "=" * 60)
    print("  TEST 6 — PAUSED is NOT terminal BLOCKED escalation")
    print("=" * 60)

    wf_id = _fresh_wf_id()
    _register(wf_id, "ACTIVE")

    # 6A: Pause succeeds
    pause_workflow(wf_id)
    state = _get_workflow_state(wf_id)
    check("6A: workflow is PAUSED (not BLOCKED) after user pause",
          state and state.get("status") == "PAUSED",
          f"state={state}")

    # 6B: PAUSED reason is user_pause, not escalated/max_retries_exceeded
    check("6B: pause reason is user_pause (not escalation reason)",
          state and state.get("reason") == "user_pause",
          f"reason={state.get('reason') if state else 'N/A'}")

    # 6C: Resume from PAUSED is allowed (not a terminal block)
    result = resume_workflow(wf_id)
    check("6C: PAUSED workflow can be resumed (not terminal)",
          result.get("status") == "success",
          str(result))

    # 6D: Terminal BLOCKED reasons are NOT resumable
    wf_id2 = _fresh_wf_id()
    _update_workflow_state(wf_id2, "BLOCKED", "max_steps_exceeded")
    result2 = resume_workflow(wf_id2)
    check("6D: BLOCKED with max_steps_exceeded is NOT resumable",
          result2.get("status") == "failure",
          str(result2))

    wf_id3 = _fresh_wf_id()
    _update_workflow_state(wf_id3, "BLOCKED", "escalated")
    result3 = resume_workflow(wf_id3)
    check("6D: BLOCKED with escalated is NOT resumable",
          result3.get("status") == "failure",
          str(result3))

    # 6E: BLOCKED dependency-wait (no terminal reason) IS resumable
    wf_id4 = _fresh_wf_id()
    _update_workflow_state(wf_id4, "BLOCKED", "dependency_not_completed:s1:PENDING")
    result4 = resume_workflow(wf_id4)
    check("6E: BLOCKED with dependency_wait reason IS resumable",
          result4.get("status") == "success",
          str(result4))


# =============================================================================
# TEST 7 — Repeated pause/resume cycles (adversarial)
# =============================================================================

def test_repeated_pause_resume():
    print("\n" + "=" * 60)
    print("  TEST 7 — Repeated pause/resume cycles (adversarial)")
    print("=" * 60)

    wf_id = _fresh_wf_id()
    _register(wf_id, "ACTIVE")

    cycles = 5
    for i in range(cycles):
        p = pause_workflow(wf_id)
        r = resume_workflow(wf_id)
        ok = p.get("status") == "success" and r.get("status") == "success"
        check(f"7: cycle {i+1}/{cycles} pause+resume succeeds", ok,
              f"pause={p} resume={r}")

    # Final state: ACTIVE
    final = _get_workflow_state(wf_id)
    check("7: final state after all cycles = ACTIVE",
          final and final.get("status") == "ACTIVE",
          f"final={final}")


# =============================================================================
# TEST 8 — Concurrent pause attempt (race guard)
# =============================================================================

def test_concurrent_pause():
    print("\n" + "=" * 60)
    print("  TEST 8 — Concurrent pause attempt (race guard)")
    print("=" * 60)

    wf_id = _fresh_wf_id()
    _register(wf_id, "ACTIVE")

    results = []

    def _do_pause():
        results.append(pause_workflow(wf_id))

    t1 = threading.Thread(target=_do_pause)
    t2 = threading.Thread(target=_do_pause)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    successes = [r for r in results if r.get("status") == "success"]
    failures  = [r for r in results if r.get("status") == "failure"]

    check("8: exactly one pause succeeds under concurrent attempts",
          len(successes) == 1,
          f"successes={len(successes)} failures={len(failures)}")
    check("8: exactly one pause fails (duplicate rejected)",
          len(failures) == 1,
          f"failures={len(failures)}")


# =============================================================================
# PHASE 5 — ARCHITECTURE VALIDATION (source-level checks)
# =============================================================================

def test_architecture_validation():
    print("\n" + "=" * 60)
    print("  TEST 9 — Architecture Validation (10 rules)")
    print("=" * 60)

    import re

    def _read(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    wc_src   = _read(os.path.join(os.path.dirname(__file__), "..", "system", "orchestrator", "workflow_control.py"))
    sched_src = _read(os.path.join(os.path.dirname(__file__), "..", "system", "orchestrator", "execution_scheduler.py"))
    api_src  = _read(os.path.join(os.path.dirname(__file__), "..", "ai_lab_gui", "backend", "api.py"))
    rt_src   = _read(os.path.join(os.path.dirname(__file__), "..", "system", "orchestrator", "orchestrator_runtime.py"))

    # Rule 1: Authority model integrity — workflow_control owns lifecycle authority
    check("Rule 1: workflow_control owns lifecycle authority (_is_valid_state_transition)",
          "_is_valid_state_transition" in wc_src)

    # Rule 2: system_entry remains sole execution path (not bypassed in resume)
    check("Rule 2: system_entry not bypassed in api.py resume endpoint",
          "system_entry" not in api_src.split("resume_workflow_endpoint")[1].split("def ")[0])

    # Rule 3: No cross-layer violations — scheduler does NOT directly mutate lifecycle
    check("Rule 3: scheduler uses request_step_transition (not direct status=)",
          "request_step_transition" in sched_src)
    check("Rule 3: scheduler does NOT import _update_workflow_state directly",
          "_update_workflow_state" not in sched_src.split("_get_workflow_state")[0])

    # Rule 4: No control flow redesign — resume still calls run_workflow
    check("Rule 4: resume endpoint calls run_workflow",
          "run_workflow" in api_src.split("resume_workflow_endpoint")[1].split("@app.")[0])

    # Rule 5: Observability preserved — events emitted on pause/resume
    check("Rule 5: pause emits PROJECT_PAUSED event",
          "PROJECT_PAUSED" in wc_src)
    check("Rule 5: resume emits PROJECT_RESUMED event",
          "PROJECT_RESUMED" in wc_src)

    # Rule 6: Determinism preserved — scheduler reads authoritative state (Fix 3)
    check("Rule 6: scheduler reads authoritative state via _get_workflow_state",
          "_get_workflow_state" in sched_src and "_sched_auth_state" in sched_src)

    # Rule 7: Projection authority preserved — stream registry is projection cache only
    check("Rule 7: stream registry is projection-only (not lifecycle authority)",
          "Stream registry is projection-only" in api_src or
          "projection_only" in api_src.lower() or
          "projection cache" in api_src.lower())

    # Rule 8: Lifecycle authority preserved — Fix 1 uses registry not stale dict
    check("Rule 8: resume endpoint uses _get_workflow_state (not stale dict status check)",
          "_authoritative = _get_workflow_state(workflow_id)" in api_src)

    # Rule 9: No optimistic lifecycle state — scheduler returns None on PAUSED
    check("Rule 9: scheduler returns None when PAUSED (no auto-resume)",
          "_sched_auth_state == \"PAUSED\"" in sched_src and
          "return None" in sched_src.split("_sched_auth_state == \"PAUSED\"")[1][:50])

    # Rule 10: t.join() removed — resume is async (Fix 2)
    check("Rule 10: t.join() removed from resume endpoint (async re-entry)",
          "t.join()" not in api_src.split("_resume_execute_wrapper")[1].split("return {")[0])


# =============================================================================
# PHASE 6 — ADVERSARIAL VALIDATION
# =============================================================================

def test_adversarial():
    print("\n" + "=" * 60)
    print("  TEST 10 — Adversarial Validation")
    print("=" * 60)

    # 10A: Pause non-existent workflow
    result = pause_workflow("ghost_wf_12345")
    check("10A: pause non-existent workflow → failure (not crash)",
          result.get("status") == "failure",
          str(result))

    # 10B: Resume non-existent workflow
    result2 = resume_workflow("ghost_wf_12345")
    check("10B: resume non-existent workflow → failure (not crash)",
          result2.get("status") == "failure",
          str(result2))

    # 10C: Pause during BLOCKED dependency-wait is NOT valid
    # (BLOCKED → PAUSED is not in FSM)
    wf_id = _fresh_wf_id()
    _register(wf_id, "BLOCKED")
    result3 = pause_workflow(wf_id)
    check("10C: pause from BLOCKED → rejected (not in FSM)",
          result3.get("status") == "failure",
          str(result3))

    # 10D: Resume from COMPLETED → rejected (terminal state)
    wf_id2 = _fresh_wf_id()
    _register(wf_id2, "COMPLETED")
    result4 = resume_workflow(wf_id2)
    check("10D: resume from COMPLETED → rejected (terminal)",
          result4.get("status") == "failure",
          str(result4))

    # 10E: Scheduler with no steps → returns None (no crash)
    detector = ConflictDetector()
    wf_id3 = _fresh_wf_id()
    _register(wf_id3, "ACTIVE")
    workflow_empty = {"id": wf_id3, "status": "ACTIVE", "steps": []}
    group = create_execution_group(workflow_empty, {}, detector, wf_id3)
    check("10E: scheduler returns None on empty step list (no crash)",
          group is None,
          f"group={group}")

    # 10F: Pause with empty workflow_id
    result5 = pause_workflow("")
    check("10F: pause with empty workflow_id → failure",
          result5.get("status") == "failure",
          str(result5))

    # 10G: Resume with empty workflow_id
    result6 = resume_workflow("")
    check("10G: resume with empty workflow_id → failure",
          result6.get("status") == "failure",
          str(result6))


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 60)
    print("  PAUSE/RESUME STABILIZATION — TEST SUITE (Phase 1A)")
    print("=" * 60)

    tests = [
        test_fsm_correctness,
        test_pause_resume_registry,
        test_scheduler_authoritative_state,
        test_resume_registry_authority,
        test_dependency_blocked_pause_resume,
        test_paused_not_escalation,
        test_repeated_pause_resume,
        test_concurrent_pause,
        test_architecture_validation,
        test_adversarial,
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

    if _failed:
        print("\n" + "=" * 60)
        print("  FAILURES")
        print("=" * 60)
        for t in _traces:
            if not t["pass"]:
                print(f"  [FAIL] {t['label']}")
                if t["detail"]:
                    print(f"         {t['detail']}")

    return _failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
