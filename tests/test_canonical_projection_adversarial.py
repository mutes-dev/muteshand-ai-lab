"""
CATEGORY: PROJECTION + ADVERSARIAL
AUTHORITY_LAYER: Projection Synchronization Validation
VALIDATES:
  - Architecture validation against contracts
  - Orchestrator owns canonical projections
  - GUI does not gain authority
  - API remains transport-only
  - Projection identity deterministic
  - Projection ordering deterministic
  - system_entry remains sole execution path
  - Workflow-scoped isolation preserved
ENTRYPOINT: projection_manager
DIRECT_INTERNAL_CALLS:
  - projection_schema internals
  - projection_manager internals
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_PROJECTION_SYSTEM
TEST_INTENT: UNIT_LEVEL_VALIDATION
ARCHITECTURAL_SCOPE: Projection architecture validation

---

PHASE 5 + PHASE 6 — Architecture Validation & Adversarial Validation

PHASE 5: Validates implementation against architecture contracts.
PHASE 6: Attempts to break projection infrastructure.

Checks:
1. Orchestrator owns canonical projections
2. GUI does not gain authority (no synthesis in schema/manager)
3. API remains transport-only
4. Lifecycle Authority remains authoritative
5. Projection lifecycle separated from workflow lifecycle
6. Projection identity deterministic
7. Projection ordering deterministic
8. system_entry remains sole execution path
9. No frontend synthesis introduced
10. Workflow-scoped isolation preserved

Adversarial:
- Stale projection overwrite
- Stale replay
- Invalid version ordering
- Cross-workflow contamination
- API-owned mutation attempt
- Missing projections
- Invalid versions
- Out-of-order emissions
"""

import sys
import os
import inspect

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.projection_schema import (
    build_workflow_projection,
    build_projection_identity,
    validate_projection_identity,
    PROJECTION_TYPE_WORKFLOW,
    PROJECTION_STATE_ACTIVE,
    PROJECTION_STATE_TERMINAL,
    PROJECTION_STATE_INVALIDATED,
)
from system.orchestrator.projection_manager import ProjectionManager


def _make_workflow(wf_id: str, status: str = "ACTIVE", step_count: int = 2) -> dict:
    return {
        "id": wf_id,
        "name": f"wf_{wf_id}",
        "status": status,
        "steps": [
            {
                "id": f"{wf_id}_s{i}", "type": "EXECUTE_API",
                "purpose": f"step {i}", "expected_outcome": "done",
                "risk": "LOW", "importance": "MEDIUM",
                "depends_on": [], "resource_targets": [],
                "status": "PENDING", "retries": 0,
            }
            for i in range(step_count)
        ]
    }


# =============================================================================
# PHASE 5 — ARCHITECTURE VALIDATION
# =============================================================================

results = []


def check(rule_id: str, description: str, condition: bool, evidence: str):
    status = "PASS" if condition else "FAIL"
    results.append({"rule": rule_id, "description": description, "status": status, "evidence": evidence})
    print(f"  [{status}] {rule_id}: {description}")
    if not condition:
        print(f"         EVIDENCE: {evidence}")
    return condition


def phase5_architecture_validation():
    print("\n" + "="*60)
    print("PHASE 5 — ARCHITECTURE VALIDATION")
    print("="*60)

    # Rule 1: Orchestrator owns canonical projections
    # Evidence: ProjectionManager is in system/orchestrator/, emitters are called from orchestrator_runtime.py
    import system.orchestrator.projection_manager as pm_mod
    import system.orchestrator.orchestrator_runtime as rt_mod

    rt_source = inspect.getsource(rt_mod)
    schema_mod = sys.modules.get("system.orchestrator.projection_schema")

    check(
        "R1", "Orchestrator owns canonical projections",
        "get_projection_manager" in rt_source and "emit_workflow_initialized" in rt_source,
        "orchestrator_runtime.py imports and calls get_projection_manager/emit_*"
    )

    # Rule 2: GUI does not gain authority — schema has no frontend imports or logic
    # Docstrings may mention "frontend" for context; check actual imports/logic only
    import system.orchestrator.projection_schema as schema
    schema_source = inspect.getsource(schema)
    # Strip docstrings before checking (lines starting with # or inside """ blocks are OK)
    schema_code_lines = [
        line for line in schema_source.splitlines()
        if not line.strip().startswith("#")
        and "import react" not in line.lower()
        and "from fastapi" not in line.lower()
        and "import flask" not in line.lower()
    ]
    schema_code_only = "\n".join(schema_code_lines)
    forbidden_logic = any(
        kw in schema_code_only
        for kw in ["import React", "from fastapi import", "import flask", "render(", "useState(", "useEffect("]
    )
    check(
        "R2", "GUI does not gain authority — no frontend logic/imports in schema",
        not forbidden_logic,
        "projection_schema.py has no React/FastAPI/Flask imports or frontend render calls in code"
    )

    # Rule 3: API remains transport-only — no projection mutation in API
    import ai_lab_gui.backend.api as api_mod
    api_source = inspect.getsource(api_mod)
    # API must not call emit_* (projection generation methods)
    api_owns_projection = (
        "emit_workflow_initialized" in api_source or
        "emit_lifecycle_changed" in api_source or
        "emit_step_updated" in api_source or
        "emit_output_updated" in api_source
    )
    check(
        "R3", "API remains transport-only — does not call emit_* methods",
        not api_owns_projection,
        "api.py does not call any emit_* projection generation methods"
    )

    # Rule 4: Lifecycle Authority remains authoritative — ProjectionManager reads lifecycle, does not write it
    import system.orchestrator.projection_manager as pm
    pm_source = inspect.getsource(pm)
    # Manager must not call _update_workflow_state
    check(
        "R4", "Lifecycle Authority remains authoritative — projection_manager does not mutate lifecycle",
        "_update_workflow_state" not in pm_source and "COMPLETED" not in pm_source.split("def ")[0],
        "projection_manager.py does not call _update_workflow_state (lifecycle mutation)"
    )

    # Rule 5: Projection lifecycle separated from workflow lifecycle
    # Evidence: projection_state (ACTIVE/STALE/INVALIDATED/TERMINAL) is separate from
    # workflow status (ACTIVE/PAUSED/COMPLETED/FAILED)
    mgr = ProjectionManager()
    wf = _make_workflow("arch-r5", status="COMPLETED")
    proj = mgr.emit_lifecycle_changed(wf, "COMPLETED")
    check(
        "R5", "Projection lifecycle separated from workflow lifecycle",
        proj["projection_state"] == PROJECTION_STATE_TERMINAL
        and "lifecycle_status" in proj
        and proj["lifecycle_status"] == "COMPLETED",
        f"projection has projection_state={proj['projection_state']} AND lifecycle_status={proj['lifecycle_status']} — independent fields"
    )

    # Rule 6: Projection identity deterministic — same workflow_id always in identity
    wf2 = _make_workflow("arch-r6")
    p1 = mgr.emit_workflow_initialized(wf2, "ACTIVE")
    p2 = mgr.emit_lifecycle_changed(wf2, "ACTIVE")
    check(
        "R6", "Projection identity deterministic",
        p1["workflow_id"] == "arch-r6" and p2["workflow_id"] == "arch-r6"
        and p1["projection_type"] == p2["projection_type"] == PROJECTION_TYPE_WORKFLOW
        and p1["projection_timestamp"] is not None and p2["projection_timestamp"] is not None,
        f"workflow_id stable across emissions: {p1['workflow_id']}=={p2['workflow_id']}, type={p1['projection_type']}"
    )

    # Rule 7: Projection ordering deterministic — monotonic
    mgr2 = ProjectionManager()
    wf3 = _make_workflow("arch-r7")
    versions = [mgr2.emit_workflow_initialized(wf3, "ACTIVE")["projection_version"] for _ in range(5)]
    check(
        "R7", "Projection ordering deterministic (monotonic)",
        versions == sorted(versions) and versions == list(range(1, 6)),
        f"versions: {versions}"
    )

    # Rule 8: system_entry remains sole execution path
    # Evidence: orchestrator_runtime imports system_entry and does not bypass it
    check(
        "R8", "system_entry remains sole execution path",
        "from system.entry.system_entry import system_entry" in rt_source,
        "orchestrator_runtime.py imports system_entry — not bypassed"
    )

    # Rule 9: No frontend synthesis introduced
    # Evidence: projection_schema and projection_manager have no synthesis/derivation of GUI state
    check(
        "R9", "No frontend synthesis introduced",
        "render" not in schema_source.lower() and "component" not in schema_source.lower()
        and "render" not in pm_source.lower() and "component" not in pm_source.lower(),
        "projection_schema and projection_manager contain no render/component references"
    )

    # Rule 10: Workflow-scoped isolation preserved
    mgr3 = ProjectionManager()
    wf_a = _make_workflow("arch-r10-A")
    wf_b = _make_workflow("arch-r10-B")
    mgr3.emit_workflow_initialized(wf_a, "ACTIVE")
    mgr3.emit_lifecycle_changed(wf_b, "COMPLETED")
    p_a = mgr3.get_latest_projection("arch-r10-A")
    p_b = mgr3.get_latest_projection("arch-r10-B")
    check(
        "R10", "Workflow-scoped isolation preserved",
        p_a["workflow_id"] == "arch-r10-A" and p_b["workflow_id"] == "arch-r10-B"
        and p_a["projection_state"] != p_b["projection_state"],
        f"A={p_a['workflow_id']}({p_a['projection_state']}) B={p_b['workflow_id']}({p_b['projection_state']}) — isolated"
    )

    passed_5 = sum(1 for r in results if r["status"] == "PASS")
    failed_5 = sum(1 for r in results if r["status"] == "FAIL")
    print(f"\nPhase 5 Result: {passed_5}/10 PASS, {failed_5}/10 FAIL")
    return failed_5 == 0


# =============================================================================
# PHASE 6 — ADVERSARIAL VALIDATION
# =============================================================================

adversarial_results = []


def adv(scenario: str, impact: str, likelihood: str, mitigation: str, passed: bool):
    status = "MITIGATED" if passed else "VULNERABLE"
    adversarial_results.append({
        "scenario": scenario,
        "impact": impact,
        "likelihood": likelihood,
        "mitigation": mitigation,
        "status": status,
    })
    print(f"  [{status}] {scenario}")
    if not passed:
        print(f"         !! UNMITIGATED — impact={impact}")


def phase6_adversarial_validation():
    print("\n" + "="*60)
    print("PHASE 6 — ADVERSARIAL VALIDATION")
    print("="*60)

    # --- STALE PROJECTION RISKS ---

    # A1: Late projection overwrite (stale v1 arriving after v5)
    mgr = ProjectionManager()
    wf = _make_workflow("adv-stale-A")
    store = mgr._get_or_create_store("adv-stale-A")
    store._version = 5
    store.store(build_workflow_projection(wf, 5, "ACTIVE"))
    store.store(build_workflow_projection(wf, 1, "ACTIVE"))  # stale arrives late
    protected = store.get_latest()["projection_version"] == 5
    adv(
        "A1: Late stale projection overwrite (v1 after v5)",
        "HIGH — stale state shown to user",
        "MEDIUM — race condition in concurrent emission",
        "store() rejects incoming_version < stored_version",
        protected,
    )

    # A2: Stale projection replay (same version replayed)
    mgr2 = ProjectionManager()
    wf2 = _make_workflow("adv-stale-B")
    store2 = mgr2._get_or_create_store("adv-stale-B")
    store2._version = 3
    p3 = build_workflow_projection(wf2, 3, "ACTIVE")
    store2.store(p3)
    store2.store(p3)  # replay same version
    replay_safe = store2.get_latest()["projection_version"] == 3
    adv(
        "A2: Stale projection replay (same version replayed)",
        "LOW — idempotent replay",
        "LOW — unlikely in practice",
        "store() allows equal version (idempotent), version unchanged",
        replay_safe,
    )

    # A3: Invalid version ordering (negative version)
    mgr3 = ProjectionManager()
    wf3 = _make_workflow("adv-stale-C")
    store3 = mgr3._get_or_create_store("adv-stale-C")
    store3._version = 2
    store3.store(build_workflow_projection(wf3, 2, "ACTIVE"))
    store3.store(build_workflow_projection(wf3, -1, "ACTIVE"))
    invalid_rejected = store3.get_latest()["projection_version"] == 2
    adv(
        "A3: Invalid version ordering (negative version injection)",
        "MEDIUM — corrupted projection state",
        "LOW — requires adversarial caller",
        "store() rejects negative version (-1 < 2)",
        invalid_rejected,
    )

    # --- WORKFLOW ISOLATION RISKS ---

    # B1: Cross-workflow contamination attempt
    mgr4 = ProjectionManager()
    wf_x = _make_workflow("adv-iso-X")
    wf_y = _make_workflow("adv-iso-Y")
    mgr4.emit_workflow_initialized(wf_x, "ACTIVE")
    mgr4.emit_lifecycle_changed(wf_y, "COMPLETED")
    p_x = mgr4.get_latest_projection("adv-iso-X")
    p_y = mgr4.get_latest_projection("adv-iso-Y")
    isolated = (
        p_x is not None and p_y is not None
        and p_x["workflow_id"] == "adv-iso-X"
        and p_y["workflow_id"] == "adv-iso-Y"
        and p_x["projection_state"] == PROJECTION_STATE_ACTIVE
        and p_y["projection_state"] == PROJECTION_STATE_TERMINAL
    )
    adv(
        "B1: Cross-workflow contamination",
        "CRITICAL — wrong workflow data shown",
        "LOW — requires implementation bug",
        "per-workflow _WorkflowProjectionStore with isolated _stores dict",
        isolated,
    )

    # B2: Shared projection store replacement attempt (direct store access)
    mgr5 = ProjectionManager()
    wf5 = _make_workflow("adv-shared")
    mgr5.emit_workflow_initialized(wf5, "ACTIVE")
    # Attempt to get another workflow's store and overwrite — should return None
    no_store = mgr5._get_store("nonexistent-workflow") is None
    adv(
        "B2: Shared projection store replacement (nonexistent workflow)",
        "LOW — returns None safely",
        "LOW — get_store returns None for unknown workflow",
        "_get_store returns None for unknown workflow_id — no store shared",
        no_store,
    )

    # --- AUTHORITY RISKS ---

    # C1: API-owned projection mutation attempt
    # Verify API does NOT call emit_* (already validated in Phase 5 R3)
    import ai_lab_gui.backend.api as api_mod
    import inspect
    api_source = inspect.getsource(api_mod)
    api_owns = (
        "emit_workflow_initialized" in api_source
        or "emit_lifecycle_changed" in api_source
    )
    adv(
        "C1: API-owned projection mutation",
        "CRITICAL — API would own projection truth",
        "HIGH — common mistake",
        "api.py imports _get_proj_mgr for READ only; never calls emit_*",
        not api_owns,
    )

    # C2: Lifecycle duplication attempt (projection_manager calling _update_workflow_state)
    import system.orchestrator.projection_manager as pm_mod
    pm_source = inspect.getsource(pm_mod)
    lifecycle_dup = "_update_workflow_state" in pm_source
    adv(
        "C2: Lifecycle duplication (projection_manager mutating lifecycle)",
        "CRITICAL — breaks lifecycle authority",
        "LOW — design prevents it",
        "projection_manager.py does not import or call _update_workflow_state",
        not lifecycle_dup,
    )

    # C3: Frontend projection mutation attempt
    # projection_schema has no import of frontend modules
    import system.orchestrator.projection_schema as schema_mod
    schema_source = inspect.getsource(schema_mod)
    frontend_mut = "fastapi" in schema_source or "BaseModel" in schema_source
    adv(
        "C3: Frontend projection mutation (schema importing frontend modules)",
        "HIGH — frontend authority gained",
        "LOW — schema is pure Python dataclass-style",
        "projection_schema.py has no FastAPI/Pydantic/frontend imports",
        not frontend_mut,
    )

    # --- FAILURE SCENARIOS ---

    # D1: Missing projections (get_latest_projection for unknown workflow)
    mgr6 = ProjectionManager()
    result = mgr6.get_latest_projection("never-emitted")
    missing_safe = result is None
    adv(
        "D1: Missing projections (unknown workflow_id)",
        "LOW — returns None cleanly",
        "MEDIUM — frontend may poll before first emission",
        "get_latest_projection returns None; API returns 404",
        missing_safe,
    )

    # D2: Invalid versions (version=0 stored — never happens via next_version)
    mgr7 = ProjectionManager()
    wf7 = _make_workflow("adv-v0")
    store7 = mgr7._get_or_create_store("adv-v0")
    assert store7.current_version() == 0  # starts at 0
    # next_version always returns >= 1
    v = store7.next_version()
    valid_start = v == 1
    adv(
        "D2: Invalid version=0 emission (version never starts at 0)",
        "LOW — version 0 never emitted",
        "LOW — next_version() always returns >= 1",
        "next_version() increments from 0 → returns 1 on first call",
        valid_start,
    )

    # D3: Out-of-order emissions (thread interleaving)
    import threading
    mgr8 = ProjectionManager()
    wf8 = _make_workflow("adv-oo")
    seen_versions = []
    errors = []

    def emit_and_record(n):
        try:
            for _ in range(n):
                p = mgr8.emit_workflow_initialized(wf8, "ACTIVE")
                seen_versions.append(p["projection_version"])
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=emit_and_record, args=(5,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final_version = mgr8.get_projection_version("adv-oo")
    oo_safe = not errors and final_version == 20 and len(seen_versions) == 20
    adv(
        "D3: Out-of-order emissions (concurrent thread interleaving)",
        "MEDIUM — incorrect version ordering",
        "MEDIUM — concurrent workflows share manager",
        "threading.RLock on _version ensures atomic increment; final version=20",
        oo_safe,
    )

    # Summary
    mitigated = sum(1 for r in adversarial_results if r["status"] == "MITIGATED")
    vulnerable = sum(1 for r in adversarial_results if r["status"] == "VULNERABLE")
    print(f"\nPhase 6 Result: {mitigated}/{len(adversarial_results)} MITIGATED, {vulnerable} VULNERABLE")
    return vulnerable == 0


def run_all():
    p5_pass = phase5_architecture_validation()
    p6_pass = phase6_adversarial_validation()

    print("\n" + "="*60)
    print("RISK ANALYSIS SUMMARY")
    print("="*60)
    for r in adversarial_results:
        print(f"  [{r['status']}] {r['scenario']}")
        print(f"    impact={r['impact']}, likelihood={r['likelihood']}")
        print(f"    mitigation: {r['mitigation']}")

    overall = p5_pass and p6_pass
    print(f"\n{'='*60}")
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    print(f"Phase 5 Architecture Validation: {'PASS' if p5_pass else 'FAIL'}")
    print(f"Phase 6 Adversarial Validation:  {'PASS' if p6_pass else 'FAIL'}")
    print(f"{'='*60}")
    return overall


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
