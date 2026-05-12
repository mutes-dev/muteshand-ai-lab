"""
CATEGORY: INTERNAL_RUNTIME
AUTHORITY_LAYER: Runtime Behavioral Truth
VALIDATES:
  - Plan mutation infrastructure
  - Mutation integrity
  - Projection invalidation
  - Lifecycle safety
  - Frontend authority
  - Adversarial mutation scenarios
ENTRYPOINT: run_workflow
DIRECT_INTERNAL_CALLS:
  - mutation_validation internals
  - projection_schema internals
  - workflow_control internals
MONKEYPATCH_USAGE:
  - Various for adversarial testing
MOCKING_POLICY: BEHAVIORAL_CONTROL
TEST_INTENT: BEHAVIORAL_VALIDATION
ARCHITECTURAL_SCOPE: Plan mutation infrastructure

---

PLAN MUTATION INFRASTRUCTURE — TEST SUITE
Phase 4B.1

Tests:
  1. Mutation Integrity Tests       — valid/invalid mutations, dep cycles, orphan refs
  2. Projection Invalidation Tests  — invalidation, re-emission, version increment, stale rejection
  3. Lifecycle Safety Tests         — ACTIVE/TERMINAL guards, FSM authority, request_step_transition
  4. Frontend Authority Tests       — frontend sends intent only; no optimistic mutation
  5. Adversarial Tests              — dep cycles, orphans, mutation on terminal, stale projection

Per PLAN_CONTROL_CONTRACT_V1, CANONICAL_PROJECTION_MODEL_V1,
LIFECYCLE_AUTHORITY_CONTRACT_V1, PROJECTION_CONTINUITY_CONTRACT_V1.
"""

import sys
import os
import traceback
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest.mock import patch, MagicMock
from system.orchestrator.mutation_validation import (
    validate_dependency_graph,
    validate_remove_step,
    validate_reorder,
    validate_edit_payload,
    validate_workflow_mutable,
    validate_step_mutable,
    MUTATION_TYPE_EDIT_STEP,
    MUTATION_TYPE_ADD_STEP,
    MUTATION_TYPE_REMOVE_STEP,
    MUTATION_TYPE_RETRY_STEP,
    ALLOWED_MUTATION_TYPES,
    EDITABLE_STEP_FIELDS,
    PROTECTED_LIFECYCLE_FIELDS,
)
from system.orchestrator.plan_mutation_manager import (
    request_plan_mutation,
    _emit_mutation_trace,
    _invalidate_and_reemit,
)
from system.orchestrator.projection_manager import ProjectionManager
from system.orchestrator.projection_schema import (
    build_workflow_projection,
    PROJECTION_STATE_ACTIVE,
    PROJECTION_STATE_INVALIDATED,
    PROJECTION_STATE_TERMINAL,
)
from system.orchestrator.workflow_control import (
    _workflow_state_registry,
    _update_runtime_registry_only,
    request_step_transition,
    _is_valid_state_transition,
)


# =============================================================================
# HELPERS
# =============================================================================

_passed = 0
_failed = 0
_traces = []


def check(label, cond, detail=""):
    global _passed, _failed
    marker = "[PASS]" if cond else "[FAIL]"
    msg = f"  {marker} {label}"
    if detail and not cond:
        msg += f"\n         detail: {detail}"
    print(msg)
    _traces.append({"label": label, "pass": cond, "detail": detail})
    if cond:
        _passed += 1
    else:
        _failed += 1


def _step(sid, status="PENDING", depends_on=None, **kwargs):
    return {
        "id": sid,
        "status": status,
        "type": "EXECUTE_API",
        "purpose": f"step {sid}",
        "tool_call": f"USE_TOOL: noop",
        "expected_outcome": "ok",
        "risk": "LOW",
        "importance": "MEDIUM",
        "resource_targets": [],
        "retries": 0,
        "max_retries": 3,
        "depends_on": depends_on or [],
        **kwargs,
    }


def _workflow(steps, wf_id=None, status="ACTIVE"):
    wf_id = wf_id or str(uuid.uuid4())
    return {"id": wf_id, "name": "test", "status": status, "steps": steps}


def _seed_registry(wf_id, status="ACTIVE"):
    _update_runtime_registry_only(wf_id, status)


# =============================================================================
# 1. MUTATION INTEGRITY TESTS
# =============================================================================

def test_mutation_integrity():
    print("\n" + "=" * 60)
    print("  TEST 1 — Mutation Integrity")
    print("=" * 60)

    # 1A: Allowed mutation types complete
    check("1A: edit_step in ALLOWED_MUTATION_TYPES", MUTATION_TYPE_EDIT_STEP in ALLOWED_MUTATION_TYPES)
    check("1A: add_step in ALLOWED_MUTATION_TYPES", MUTATION_TYPE_ADD_STEP in ALLOWED_MUTATION_TYPES)
    check("1A: remove_step in ALLOWED_MUTATION_TYPES", MUTATION_TYPE_REMOVE_STEP in ALLOWED_MUTATION_TYPES)
    check("1A: retry_step in ALLOWED_MUTATION_TYPES", MUTATION_TYPE_RETRY_STEP in ALLOWED_MUTATION_TYPES)

    # 1B: Valid dependency graph
    steps = [_step("s1"), _step("s2", depends_on=["s1"]), _step("s3", depends_on=["s2"])]
    result = validate_dependency_graph(steps)
    check("1B: valid linear dep graph passes", result["valid"], str(result))

    # 1C: Circular dependency rejected
    steps_cycle = [
        _step("a", depends_on=["b"]),
        _step("b", depends_on=["c"]),
        _step("c", depends_on=["a"]),
    ]
    result = validate_dependency_graph(steps_cycle)
    check("1C: circular dependency rejected", not result["valid"], str(result))
    check("1C: circular reason correct", "circular" in result.get("reason", ""), result.get("reason"))

    # 1D: Orphan reference rejected
    steps_orphan = [_step("s1"), _step("s2", depends_on=["nonexistent"])]
    result = validate_dependency_graph(steps_orphan)
    check("1D: orphan dependency reference rejected", not result["valid"], str(result))
    check("1D: orphan reason correct", "orphan" in result.get("reason", ""), result.get("reason"))

    # 1E: Remove step with dependents rejected
    steps_dep = [_step("s1"), _step("s2", depends_on=["s1"])]
    result = validate_remove_step(steps_dep, "s1")
    check("1E: remove step with dependents rejected", not result["valid"], str(result))
    check("1E: dependent step identified", result.get("dependent_step_id") == "s2")

    # 1F: Remove step without dependents accepted
    result = validate_remove_step(steps_dep, "s2")
    check("1F: remove leaf step accepted", result["valid"], str(result))

    # 1G: Edit payload — lifecycle fields rejected
    for lc_field in ("status", "retries", "execution_result", "blocked_reason"):
        r = validate_edit_payload({lc_field: "anything"})
        check(f"1G: edit payload rejects lifecycle field '{lc_field}'",
              not r["valid"], str(r))

    # 1H: Edit payload — valid fields accepted
    r = validate_edit_payload({"purpose": "new purpose", "risk": "HIGH"})
    check("1H: edit payload accepts valid fields", r["valid"], str(r))

    # 1I: Unknown fields in edit payload rejected
    r = validate_edit_payload({"unknown_field": "x"})
    check("1I: edit payload rejects unknown fields", not r["valid"], str(r))

    # 1J: Reorder validation — dependency order violation
    steps_reorder = [_step("s1"), _step("s2", depends_on=["s1"])]
    r = validate_reorder(steps_reorder, ["s2", "s1"])  # s2 before s1 violates dep
    check("1J: reorder violating dep order rejected", not r["valid"], str(r))

    # 1K: Reorder validation — correct order accepted
    r = validate_reorder(steps_reorder, ["s1", "s2"])
    check("1K: valid reorder accepted", r["valid"], str(r))

    # 1L: Reorder missing steps rejected
    r = validate_reorder(steps_reorder, ["s1"])
    check("1L: reorder missing steps rejected", not r["valid"], str(r))


# =============================================================================
# 2. PROJECTION INVALIDATION + RE-EMISSION TESTS
# =============================================================================

def test_projection_invalidation():
    print("\n" + "=" * 60)
    print("  TEST 2 — Projection Invalidation + Re-emission")
    print("=" * 60)

    pm = ProjectionManager()
    wf_id = "wf-mut-proj-" + str(uuid.uuid4())[:8]
    wf = _workflow([_step("s1"), _step("s2")], wf_id)
    _seed_registry(wf_id, "ACTIVE")

    # 2A: Emit initial projection
    p1 = pm.emit_workflow_initialized(wf, "ACTIVE")
    v1 = p1["projection_version"]
    check("2A: initial projection emitted", p1 is not None, str(p1.get("projection_version")))
    check("2A: projection_version=1", v1 == 1, f"v={v1}")

    # 2B: Mutation — emit_plan_mutated increments version
    p2 = pm.emit_plan_mutated(wf, "ACTIVE")
    v2 = p2["projection_version"]
    check("2B: emit_plan_mutated increments version", v2 > v1, f"v1={v1} v2={v2}")

    # 2C: Stale projection rejected
    stale = {**p1}  # version=1, but current is v2
    is_stale = pm.is_version_stale(wf_id, stale["projection_version"])
    check("2C: older version is stale", is_stale, f"stale_version={stale['projection_version']} current={v2}")

    # 2D: invalidate_workflow sets INVALIDATED state
    pm.invalidate_workflow(wf_id)
    state = pm.get_projection_state(wf_id)
    check("2D: invalidate_workflow sets INVALIDATED state", state == PROJECTION_STATE_INVALIDATED, f"state={state}")

    # 2E: emit_plan_mutated after invalidation re-activates (non-terminal)
    p3 = pm.emit_plan_mutated(wf, "ACTIVE")
    v3 = p3["projection_version"]
    check("2E: emit_plan_mutated after invalidation emits new projection", v3 > v2, f"v2={v2} v3={v3}")

    # 2F: Terminal projection not overwritten by non-terminal
    pm2 = ProjectionManager()
    wf_id2 = "wf-term-" + str(uuid.uuid4())[:8]
    wf2 = _workflow([_step("s1")], wf_id2)
    pm2.emit_workflow_initialized(wf2, "COMPLETED")
    term_proj = pm2.emit_lifecycle_changed(wf2, "COMPLETED")
    v_term = term_proj["projection_version"]
    check("2F: terminal projection emitted", pm2.is_workflow_terminal(wf_id2), "")

    # Try to overwrite terminal with non-terminal
    non_term = pm2.emit_plan_mutated(wf2, "ACTIVE")
    check("2F: terminal projection not overwritten by non-terminal", pm2.is_workflow_terminal(wf_id2),
          f"state={pm2.get_projection_state(wf_id2)}")
    check("2F: projection version unchanged on terminal block",
          non_term["projection_version"] == v_term, f"term_v={v_term} returned_v={non_term['projection_version']}")

    # 2G: Monotonic version ordering — multiple mutations preserve monotonic order
    pm3 = ProjectionManager()
    wf_id3 = "wf-mono-" + str(uuid.uuid4())[:8]
    wf3 = _workflow([_step("s1"), _step("s2")], wf_id3)
    versions = []
    for _ in range(5):
        p = pm3.emit_plan_mutated(wf3, "ACTIVE")
        versions.append(p["projection_version"])
    check("2G: projection versions are monotonically increasing",
          versions == sorted(versions) and len(set(versions)) == len(versions),
          f"versions={versions}")


# =============================================================================
# 3. LIFECYCLE SAFETY TESTS
# =============================================================================

def test_lifecycle_safety():
    print("\n" + "=" * 60)
    print("  TEST 3 — Lifecycle Safety")
    print("=" * 60)

    # 3A: Terminal workflow mutation rejected
    for terminal in ("COMPLETED", "FAILED"):
        r = validate_workflow_mutable(terminal, MUTATION_TYPE_EDIT_STEP)
        check(f"3A: mutation on {terminal} workflow rejected", not r["valid"], str(r))

    # 3B: Active/PAUSED/BLOCKED workflows mutable
    for state in ("ACTIVE", "PAUSED", "BLOCKED"):
        r = validate_workflow_mutable(state, MUTATION_TYPE_EDIT_STEP)
        check(f"3B: mutation on {state} workflow accepted", r["valid"], str(r))

    # 3C: COMPLETED step locked for edit
    s_done = _step("s-done", status="COMPLETED")
    r = validate_step_mutable(s_done, MUTATION_TYPE_EDIT_STEP)
    check("3C: COMPLETED step locked for edit", not r["valid"], str(r))

    # 3D: ACTIVE step edit requires restart
    s_active = _step("s-active", status="ACTIVE")
    r = validate_step_mutable(s_active, MUTATION_TYPE_EDIT_STEP)
    check("3D: ACTIVE step edit accepted", r["valid"], str(r))
    check("3D: ACTIVE step edit requires restart", r.get("restart_required") is True, str(r))

    # 3E: PENDING step edit — no restart required
    s_pending = _step("s-pending", status="PENDING")
    r = validate_step_mutable(s_pending, MUTATION_TYPE_EDIT_STEP)
    check("3E: PENDING step edit accepted", r["valid"], str(r))
    check("3E: PENDING step edit no restart needed", r.get("restart_required") is False, str(r))

    # 3F: retry_step only allowed on FAILED/BLOCKED
    s_failed = _step("s-fail", status="FAILED")
    r = validate_step_mutable(s_failed, MUTATION_TYPE_RETRY_STEP)
    check("3F: retry FAILED step accepted", r["valid"], str(r))

    s_active2 = _step("s-act2", status="ACTIVE")
    r = validate_step_mutable(s_active2, MUTATION_TYPE_RETRY_STEP)
    check("3F: retry ACTIVE step rejected", not r["valid"], str(r))

    # 3G: request_step_transition remains authoritative for ACTIVE→PENDING restart
    step_restart = _step("s-restart", status="ACTIVE")
    ok = request_step_transition(step_restart, "PENDING", reason="edit_restart")
    check("3G: request_step_transition ACTIVE→PENDING for restart succeeds (now in public FSM)",
          ok and step_restart["status"] == "PENDING", f"ok={ok} status={step_restart['status']}")

    # 3H: FSM still rejects COMPLETED→ACTIVE (terminal protection)
    s_terminal = _step("s-term", status="COMPLETED")
    ok = request_step_transition(s_terminal, "ACTIVE")
    check("3H: FSM rejects COMPLETED→ACTIVE (terminal)", not ok, f"ok={ok}")


# =============================================================================
# 4. PLAN MUTATION MANAGER — INTEGRATION TESTS
# =============================================================================

def test_plan_mutation_manager():
    print("\n" + "=" * 60)
    print("  TEST 4 — Plan Mutation Manager (integration)")
    print("=" * 60)

    # Mock persistence so no filesystem required
    def _fake_save(wf):
        pass

    def _fake_load():
        return [_current_workflow]

    wf_id = "wf-pmm-" + str(uuid.uuid4())[:8]
    _current_workflow = _workflow(
        [_step("s1"), _step("s2", depends_on=["s1"]), _step("s3", depends_on=["s2"])],
        wf_id
    )
    _seed_registry(wf_id, "ACTIVE")

    with patch("system.orchestrator.plan_mutation_manager.load_active_workflows", _fake_load), \
         patch("system.orchestrator.plan_mutation_manager.save_workflow", _fake_save), \
         patch("system.orchestrator.plan_mutation_manager._invalidate_and_reemit"):

        # 4A: Valid edit_step
        r = request_plan_mutation(wf_id, "edit_step",
                                  {"step_id": "s3", "updates": {"purpose": "Updated purpose"}})
        check("4A: valid edit_step succeeds", r["status"] == "success", str(r))
        check("4A: edit_step returns projection_version", "projection_version" in r, str(r))

        # 4B: Edit lifecycle field rejected
        r = request_plan_mutation(wf_id, "edit_step",
                                  {"step_id": "s3", "updates": {"status": "COMPLETED"}})
        check("4B: edit with lifecycle field rejected", r["status"] == "failure", str(r))
        check("4B: reason is lifecycle_field_mutation_rejected",
              "lifecycle" in r.get("reason", ""), r.get("reason"))

        # 4C: Edit COMPLETED step rejected
        for s in _current_workflow["steps"]:
            if s["id"] == "s1":
                s["status"] = "COMPLETED"
        r = request_plan_mutation(wf_id, "edit_step",
                                  {"step_id": "s1", "updates": {"purpose": "try edit"}})
        check("4C: edit COMPLETED step rejected", r["status"] == "failure", str(r))
        # reset
        for s in _current_workflow["steps"]:
            if s["id"] == "s1":
                s["status"] = "PENDING"

        # 4D: add_step valid
        r = request_plan_mutation(wf_id, "add_step",
                                  {"step_data": {"id": "s4", "purpose": "new step",
                                                 "depends_on": ["s3"]}})
        check("4D: valid add_step succeeds", r["status"] == "success", str(r))

        # 4E: add_step circular dependency rejected
        r = request_plan_mutation(wf_id, "add_step",
                                  {"step_data": {"id": "s5", "purpose": "circ",
                                                 "depends_on": ["s4", "s5"]}})
        check("4E: add_step creating self-dep circular cycle rejected",
              r["status"] == "failure", str(r))

        # 4F: remove_step with dependent rejected
        r = request_plan_mutation(wf_id, "remove_step", {"step_id": "s1"})
        check("4F: remove step with dependent rejected", r["status"] == "failure", str(r))

        # 4G: unknown mutation type rejected
        r = request_plan_mutation(wf_id, "reorder_steps", {})
        check("4G: unknown mutation type rejected", r["status"] == "failure", str(r))
        check("4G: reason is unknown_mutation_type", "unknown" in r.get("reason", ""), r.get("reason"))

        # 4H: missing workflow_id
        r = request_plan_mutation("", "edit_step", {"step_id": "s1", "updates": {}})
        check("4H: missing workflow_id rejected", r["status"] == "failure", str(r))

    # 4I: mutation on terminal workflow rejected
    wf_id2 = "wf-term-" + str(uuid.uuid4())[:8]
    wf2 = _workflow([_step("s1")], wf_id2, status="COMPLETED")
    _seed_registry(wf_id2, "COMPLETED")

    with patch("system.orchestrator.plan_mutation_manager.load_active_workflows", lambda: [wf2]), \
         patch("system.orchestrator.plan_mutation_manager.save_workflow", lambda x: None):
        r = request_plan_mutation(wf_id2, "edit_step",
                                  {"step_id": "s1", "updates": {"purpose": "try"}})
        check("4I: edit on COMPLETED workflow rejected", r["status"] == "failure", str(r))
        check("4I: reason contains terminal", "terminal" in r.get("reason", ""), r.get("reason"))


# =============================================================================
# 5. FRONTEND AUTHORITY TESTS
# =============================================================================

def test_frontend_authority():
    print("\n" + "=" * 60)
    print("  TEST 5 — Frontend Authority")
    print("=" * 60)

    # 5A: api.js requestMutation function exists and sends intent only
    import inspect
    import system.orchestrator.plan_mutation_manager as pmm_mod
    src = inspect.getsource(pmm_mod)

    check("5A: plan_mutation_manager has request_plan_mutation",
          "def request_plan_mutation" in src)
    check("5B: plan_mutation_manager emits mutation trace",
          "_emit_mutation_trace" in src)
    check("5C: plan_mutation_manager calls _invalidate_and_reemit",
          "_invalidate_and_reemit" in src)
    check("5D: plan_mutation_manager does NOT directly mutate projection (no setProjection)",
          "setProjection" not in src)
    check("5E: plan_mutation_manager calls request_step_transition for ACTIVE restart",
          "request_step_transition" in src)

    # 5F: Verify mutation_validation has no lifecycle mutations
    import system.orchestrator.mutation_validation as mv_mod
    mv_src = inspect.getsource(mv_mod)
    check("5F: mutation_validation does not set step status directly",
          'step["status"]' not in mv_src and "step['status']" not in mv_src)

    # 5G: API mutation endpoint exists in api.py
    import system
    api_path = os.path.join(os.path.dirname(__file__), "..", "ai_lab_gui", "backend", "api.py")
    with open(api_path, "r") as f:
        api_src = f.read()
    check("5G: API has /workflow/{workflow_id}/mutation endpoint",
          "/workflow/{workflow_id}/mutation" in api_src)
    check("5H: API endpoint forwards to _request_plan_mutation",
          "_request_plan_mutation" in api_src)
    check("5I: API does NOT own mutation authority (import failure-isolated)",
          "_request_plan_mutation = None" in api_src)

    # 5J: Frontend api.js has requestMutation
    frontend_api_path = os.path.join(
        os.path.dirname(__file__), "..", "ai_lab_gui", "frontend", "src", "api.js"
    )
    with open(frontend_api_path, "r") as f:
        fe_src = f.read()
    check("5J: frontend api.js has requestMutation", "requestMutation" in fe_src)
    check("5K: frontend sends intent only (no local state mutation in api.js)",
          "setProjection" not in fe_src and "useState" not in fe_src)

    # 5L: PlanMutationPanel exists and sends intent only
    panel_path = os.path.join(
        os.path.dirname(__file__), "..", "ai_lab_gui", "frontend", "src",
        "components", "PlanMutationPanel.jsx"
    )
    with open(panel_path, "r") as f:
        panel_src = f.read()
    check("5L: PlanMutationPanel uses api.requestMutation", "requestMutation" in panel_src)
    check("5M: PlanMutationPanel does NOT call setProjection",
          "setProjection" not in panel_src)
    check("5N: PlanMutationPanel awaits projection refresh (onMutationComplete callback)",
          "onMutationComplete" in panel_src)
    check("5O: PlanMutationPanel explicitly notes no optimistic update",
          "optimistic" in panel_src.lower() or "no optimistic" in panel_src.lower())


# =============================================================================
# 6. ADVERSARIAL TESTS
# =============================================================================

def test_adversarial():
    print("\n" + "=" * 60)
    print("  TEST 6 — Adversarial Validation")
    print("=" * 60)

    # A1: Deep circular dependency chain
    steps_deep = [
        _step("a", depends_on=["d"]),
        _step("b", depends_on=["a"]),
        _step("c", depends_on=["b"]),
        _step("d", depends_on=["c"]),
    ]
    r = validate_dependency_graph(steps_deep)
    check("A1: deep circular dep chain rejected", not r["valid"], str(r))

    # A2: Multiple orphan references
    steps_multi_orphan = [
        _step("s1", depends_on=["ghost1", "ghost2"]),
    ]
    r = validate_dependency_graph(steps_multi_orphan)
    check("A2: multiple orphan refs detected", not r["valid"], str(r))

    # A3: Mutation type injection (unknown type bypasses ALLOWED set)
    r_inject = request_plan_mutation("wf-x", "drop_table", {})
    check("A3: mutation type injection rejected", r_inject["status"] == "failure", str(r_inject))

    # A4: Protected field injection via payload
    for bad_field in list(PROTECTED_LIFECYCLE_FIELDS):
        r = validate_edit_payload({bad_field: "injected"})
        check(f"A4: protected field '{bad_field}' injection rejected", not r["valid"])

    # A5: Projection version regression (stale overwrite)
    pm = ProjectionManager()
    wf_id = "wf-adv-" + str(uuid.uuid4())[:8]
    wf = _workflow([_step("s1")], wf_id)
    pm.emit_plan_mutated(wf, "ACTIVE")
    pm.emit_plan_mutated(wf, "ACTIVE")
    pm.emit_plan_mutated(wf, "ACTIVE")
    current_v = pm.get_projection_version(wf_id)

    # Attempt to inject old version
    old_proj = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")
    stored = pm._get_store(wf_id).store(old_proj)
    check("A5: stale projection overwrite rejected by store()", not stored, f"accepted={stored}")
    check("A5: projection version unchanged after stale rejection",
          pm.get_projection_version(wf_id) == current_v, f"v={pm.get_projection_version(wf_id)}")

    # A6: Mutation on FAILED workflow rejected
    wf_id_fail = "wf-fail-" + str(uuid.uuid4())[:8]
    wf_fail = _workflow([_step("s1")], wf_id_fail, status="FAILED")
    _seed_registry(wf_id_fail, "FAILED")
    with patch("system.orchestrator.plan_mutation_manager.load_active_workflows",
               lambda: [wf_fail]), \
         patch("system.orchestrator.plan_mutation_manager.save_workflow", lambda x: None):
        r = request_plan_mutation(wf_id_fail, "edit_step",
                                  {"step_id": "s1", "updates": {"purpose": "x"}})
        check("A6: mutation on FAILED workflow rejected", r["status"] == "failure", str(r))

    # A7: Duplicate step ID rejected on add
    wf_id3 = "wf-dup-" + str(uuid.uuid4())[:8]
    wf3 = _workflow([_step("s1"), _step("s2")], wf_id3)
    _seed_registry(wf_id3, "ACTIVE")
    with patch("system.orchestrator.plan_mutation_manager.load_active_workflows", lambda: [wf3]), \
         patch("system.orchestrator.plan_mutation_manager.save_workflow", lambda x: None), \
         patch("system.orchestrator.plan_mutation_manager._invalidate_and_reemit"):
        r = request_plan_mutation(wf_id3, "add_step",
                                  {"step_data": {"id": "s1", "purpose": "duplicate"}})
        check("A7: duplicate step ID rejected", r["status"] == "failure", str(r))
        check("A7: reason is duplicate_step_id",
              "duplicate" in r.get("reason", ""), r.get("reason"))


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 60)
    print("  PLAN MUTATION INFRASTRUCTURE — TEST SUITE")
    print("=" * 60)

    tests = [
        test_mutation_integrity,
        test_projection_invalidation,
        test_lifecycle_safety,
        test_plan_mutation_manager,
        test_frontend_authority,
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

    print("\n" + "=" * 60)
    print("  MUTATION TRACES (failures only)")
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
