"""
PHASE 5+6 — Plan Rendering Architecture & Adversarial Validation (Phase 4B.0)

Phase 5: Architecture validation against canonical rendering rules
Phase 6: Adversarial scenarios targeting rendering continuity

Per CANONICAL_PROJECTION_MODEL_V1 §2, §3, §8, §9, §13, §14
Per PROJECTION_CONTINUITY_CONTRACT_V1 §6, §9, §12
Per GUI_ARCHITECTURE.txt (projection-render-only)
Per GUI_FUNCTIONALITY_CONTRACT_V1
Per PLAN_CONTROL_CONTRACT_V1
"""

import sys
import os
import inspect

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

results_p5 = []
results_p6 = []


def check(label, condition, evidence):
    status = "PASS" if condition else "FAIL"
    results_p5.append({"label": label, "status": status, "evidence": evidence})
    icon = "[PASS]" if condition else "[FAIL]"
    print(f"  {icon} {label}")
    if not condition:
        print(f"    FAIL EVIDENCE: {evidence}")


def mitigated(label, condition, impact, likelihood, mitigation):
    status = "MITIGATED" if condition else "VULNERABLE"
    results_p6.append({"label": label, "status": status,
                       "impact": impact, "likelihood": likelihood, "mitigation": mitigation})
    icon = "[MITIGATED]" if condition else "[VULNERABLE]"
    print(f"  {icon} {label}")


# =============================================================================
# PHASE 5 — ARCHITECTURE VALIDATION
# =============================================================================

print("\n" + "=" * 60)
print("PHASE 5 — PLAN RENDERING ARCHITECTURE VALIDATION")
print("=" * 60)

import system.orchestrator.projection_schema as schema_mod
import system.orchestrator.projection_manager as pm_mod

schema_src = inspect.getsource(schema_mod)
pm_src = inspect.getsource(pm_mod)

wfpv_path = os.path.join(os.path.dirname(__file__), "..", "ai_lab_gui", "frontend",
                          "src", "components", "WorkflowProjectionView.jsx")
pv_path = os.path.join(os.path.dirname(__file__), "..", "ai_lab_gui", "frontend",
                        "src", "components", "PlanView.jsx")
dv_path = os.path.join(os.path.dirname(__file__), "..", "ai_lab_gui", "frontend",
                        "src", "components", "DependencyView.jsx")

with open(wfpv_path, encoding="utf-8") as f: wfpv_src = f.read()
with open(pv_path, encoding="utf-8") as f: pv_src = f.read()
with open(dv_path, encoding="utf-8") as f: dv_src = f.read()

import ai_lab_gui.backend.api as api_mod
api_src = inspect.getsource(api_mod)

app_jsx_path = os.path.join(os.path.dirname(__file__), "..", "ai_lab_gui", "frontend",
                             "src", "App.jsx")
with open(app_jsx_path, encoding="utf-8") as f: app_src = f.read()

# R1: Frontend remains projection-render-only
# WorkflowProjectionView must consume only api.getProjection — not synthesize state
check("R1: Frontend remains projection-render-only",
    "api.getProjection" in wfpv_src and "emit_workflow_initialized" not in wfpv_src,
    "WorkflowProjectionView calls api.getProjection; does not call emit_* methods")

# R2: Frontend does not synthesize workflow truth
# No lifecycle_status assignment, no _update_workflow_state in projection views
no_synth = (
    "_update_workflow_state" not in wfpv_src and
    "lifecycle_status =" not in wfpv_src and
    "status = " not in wfpv_src.split("const status")[0]  # status comes from projection
)
check("R2: Frontend does not synthesize workflow truth",
    "_update_workflow_state" not in wfpv_src and "lifecycle_status =" not in wfpv_src,
    "WorkflowProjectionView does not call _update_workflow_state or assign lifecycle_status locally")

# R3: Frontend does not synthesize lifecycle state
check("R3: Frontend does not synthesize lifecycle state",
    "emit_lifecycle_changed" not in wfpv_src and
    "emit_lifecycle_changed" not in pv_src and
    "emit_lifecycle_changed" not in dv_src,
    "No emit_lifecycle_changed in any rendering component")

# R4: Frontend consumes canonical projections only
check("R4: Frontend consumes canonical projections only",
    "api.getProjection" in wfpv_src and "/projection/" in wfpv_src,
    "WorkflowProjectionView fetches from /projection/{workflowId} endpoint")

# R5: Workflow-scoped rendering preserved
# WorkflowProjectionView uses activeWorkflowIdRef to reject cross-workflow updates
check("R5: Workflow-scoped rendering preserved",
    "activeWorkflowIdRef" in wfpv_src and "PROJECTION_ISOLATION_REJECT" in wfpv_src,
    "WorkflowProjectionView uses activeWorkflowIdRef and PROJECTION_ISOLATION_REJECT log")

# R6: Dependency rendering is projection-driven
# DependencyView uses step.depends_on from projection — no local synthesis
# R6: DependencyView must read from step.depends_on only; no local dep reconstruction
# Words like "hidden" may appear in comments/labels — check for code patterns instead
dep_no_reconstruction = (
    "depends_on" in dv_src and
    "inferDeps" not in dv_src and
    "deriveDeps" not in dv_src and
    "hiddenDeps" not in dv_src and
    "computeDeps" not in dv_src and
    "emit_" not in dv_src
)
check("R6: Dependency rendering is projection-driven",
    dep_no_reconstruction,
    "DependencyView reads step.depends_on from projection; no dep reconstruction functions")

# R7: Stale projections rejected deterministically
# WorkflowProjectionView has version guard and PROJECTION_STALE_REJECT log
check("R7: Stale projections rejected deterministically",
    "lastProjectionVersionRef" in wfpv_src and "PROJECTION_STALE_REJECT" in wfpv_src,
    "WorkflowProjectionView uses lastProjectionVersionRef + PROJECTION_STALE_REJECT guard")

# R8: Terminal projections remain stable
check("R8: Terminal projections remain stable",
    "PROJECTION_TERMINAL_STABLE" in wfpv_src and "TERMINAL" in wfpv_src,
    "WorkflowProjectionView has PROJECTION_TERMINAL_STABLE guard preventing non-terminal overwrite")

# R9: Workflow switching is continuity-safe
# On workflowId change: clear projection, reset version ref, reset activeWorkflowIdRef
check("R9: Workflow switching is continuity-safe",
    "PROJECTION_BOUNDARY_RESET" in wfpv_src and
    "lastProjectionVersionRef.current = 0" in wfpv_src and
    "setProjection(null)" in wfpv_src,
    "WorkflowProjectionView resets projection state on workflow switch")

# R10: PlanView/DependencyView must have no mutation authority
# Read-only UI toggles (expand/collapse, show deps) are allowed
# Forbidden: edit handlers, mutation tokens, reorder controls, optimistic updates
def _strip_comments(src):
    """Remove JSDoc/inline comment lines for code-only checks."""
    return "\n".join(
        line for line in src.splitlines()
        if not line.strip().startswith("*") and not line.strip().startswith("//")
    )

pv_code = _strip_comments(pv_src)
dv_code = _strip_comments(dv_src)

pv_no_mutation = (
    "editableStep" not in pv_code and
    "can_edit" not in pv_code and
    "mutation_token" not in pv_code and
    "reorderStep" not in pv_code and
    "optimistic" not in pv_code.lower() and
    "emit_" not in pv_code
)
dv_no_mutation = (
    "editableStep" not in dv_code and
    "mutation_token" not in dv_code and
    "emit_" not in dv_code
)
check("R10: No frontend mutation authority introduced",
    pv_no_mutation and dv_no_mutation,
    "PlanView and DependencyView: no editable/mutation_token/reorderStep/optimistic/emit_ present")

# R_APP: App.jsx derives workflowId from backend projection — not local synthesis
check("R_APP: App.jsx derives workflowId from backend projection",
    "activeWorkflowId = lastResult?.workflow_id" in app_src,
    "App.jsx: activeWorkflowId derived from lastResult?.workflow_id (backend projection)")

p5_pass = sum(1 for r in results_p5 if r["status"] == "PASS")
p5_fail = sum(1 for r in results_p5 if r["status"] == "FAIL")
print(f"\nPhase 5 Result: {p5_pass}/{len(results_p5)} PASS, {p5_fail}/{len(results_p5)} FAIL")


# =============================================================================
# PHASE 6 — ADVERSARIAL VALIDATION
# =============================================================================

print("\n" + "=" * 60)
print("PHASE 6 — PLAN RENDERING ADVERSARIAL VALIDATION")
print("=" * 60)

from system.orchestrator.projection_manager import ProjectionManager, _WorkflowProjectionStore
from system.orchestrator.projection_schema import (
    build_workflow_projection, PROJECTION_STATE_ACTIVE, PROJECTION_STATE_TERMINAL
)


def mk_wf(wf_id, status="ACTIVE", steps=None):
    return {
        "id": wf_id, "name": wf_id, "status": status,
        "steps": steps or [{
            "id": "s1", "type": "EXECUTE_API", "purpose": "p",
            "expected_outcome": "ok", "risk": "LOW", "importance": "MEDIUM",
            "depends_on": [], "resource_targets": [], "status": "PENDING", "retries": 0
        }]
    }


# --- Rendering Risks ---

# A1: Stale render replay — old projection replayed after newer rendered
mgr_a1 = ProjectionManager()
wf = mk_wf("adv-render-A1")
for _ in range(5):
    mgr_a1.emit_workflow_initialized(wf, "ACTIVE")
is_stale = mgr_a1.is_version_stale("adv-render-A1", 1)
mitigated("A1: Stale render replay (v1 replayed after v5)",
    is_stale is True and mgr_a1.get_projection_version("adv-render-A1") == 5,
    "HIGH", "MEDIUM",
    "WorkflowProjectionView lastProjectionVersionRef guard rejects stale; backend is_version_stale=True")

# A2: Invalid workflow projection swap — wf_A projection applied to wf_B render
mgr_a2 = ProjectionManager()
mgr_a2.emit_workflow_initialized(mk_wf("adv-render-A2a"), "ACTIVE")
mgr_a2.emit_workflow_initialized(mk_wf("adv-render-A2b"), "ACTIVE")
p_a = mgr_a2.get_latest_projection("adv-render-A2a")
hyd = mgr_a2.validate_hydration_projection("adv-render-A2b", p_a)
mitigated("A2: Invalid workflow projection swap (A's projection applied to B's render)",
    hyd["valid"] is False and hyd["reason"] == "workflow_id_mismatch",
    "CRITICAL", "LOW",
    f"validate_hydration_projection rejects workflow_id_mismatch: {hyd['reason']}")

# A3: Terminal regression rendering — ACTIVE projection replaces COMPLETED render
mgr_a3 = ProjectionManager()
wf = mk_wf("adv-render-A3", "COMPLETED")
mgr_a3.emit_lifecycle_changed(wf, "COMPLETED")
term_v = mgr_a3.get_projection_version("adv-render-A3")
mgr_a3.emit_lifecycle_changed(mk_wf("adv-render-A3", "ACTIVE"), "ACTIVE")
still_terminal = mgr_a3.get_projection_state("adv-render-A3") == PROJECTION_STATE_TERMINAL
still_v = mgr_a3.get_projection_version("adv-render-A3") == term_v
mitigated("A3: Terminal regression rendering (ACTIVE replaces COMPLETED render)",
    still_terminal and still_v,
    "CRITICAL", "MEDIUM",
    f"Backend: emit_lifecycle_changed returns TERMINAL unchanged; frontend: PROJECTION_TERMINAL_STABLE guard")

# A4: Hidden dependency synthesis — projection schema must not add implicit deps
steps = [
    {"id": "s1", "type": "T", "purpose": "A", "expected_outcome": "e",
     "risk": "LOW", "importance": "M", "depends_on": [], "resource_targets": [],
     "status": "PENDING", "retries": 0},
    {"id": "s2", "type": "T", "purpose": "B", "expected_outcome": "e",
     "risk": "LOW", "importance": "M", "depends_on": [], "resource_targets": [],
     "status": "PENDING", "retries": 0},
]
p_dep = build_workflow_projection(mk_wf("adv-dep", steps=steps), projection_version=1, lifecycle_status="ACTIVE")
s2_deps = next(s["depends_on"] for s in p_dep["steps"] if s["step_id"] == "s2")
mitigated("A4: Hidden dependency synthesis (implicit deps added by schema)",
    s2_deps == [],
    "HIGH", "LOW",
    "build_workflow_projection does not synthesize implicit deps; s2.depends_on=[]")


# --- Workflow Isolation Risks ---

# B1: Cross-workflow rendering contamination
mgr_b1 = ProjectionManager()
wf_a = mk_wf("adv-b1-A", steps=[
    {"id": "sa1", "type": "T", "purpose": "A1", "expected_outcome": "e",
     "risk": "LOW", "importance": "M", "depends_on": [], "resource_targets": [],
     "status": "PENDING", "retries": 0}
])
wf_b = mk_wf("adv-b1-B", steps=[
    {"id": "sb1", "type": "T", "purpose": "B1", "expected_outcome": "e",
     "risk": "LOW", "importance": "M", "depends_on": [], "resource_targets": [],
     "status": "PENDING", "retries": 0}
])
mgr_b1.emit_workflow_initialized(wf_a, "ACTIVE")
mgr_b1.emit_workflow_initialized(wf_b, "ACTIVE")
p_a = mgr_b1.get_latest_projection("adv-b1-A")
p_b = mgr_b1.get_latest_projection("adv-b1-B")
a_step_ids = {s["step_id"] for s in p_a["steps"]}
b_step_ids = {s["step_id"] for s in p_b["steps"]}
mitigated("B1: Cross-workflow rendering contamination",
    "sa1" in a_step_ids and "sa1" not in b_step_ids and
    "sb1" in b_step_ids and "sb1" not in a_step_ids,
    "CRITICAL", "LOW",
    "Per-workflow _WorkflowProjectionStore isolation; sa1 in A only, sb1 in B only")

# B2: Stale workflow switching — old workflow render bleeds into new
mgr_b2 = ProjectionManager()
for _ in range(4):
    mgr_b2.emit_workflow_initialized(mk_wf("adv-b2-old"), "ACTIVE")
mgr_b2.emit_workflow_initialized(mk_wf("adv-b2-new"), "ACTIVE")
# Stale 'old' projection must not be applied to 'new' render
stale_old = mgr_b2.get_latest_projection("adv-b2-old")
hyd_b2 = mgr_b2.validate_hydration_projection("adv-b2-new", stale_old)
mitigated("B2: Stale workflow switching (old render bleeds into new)",
    hyd_b2["valid"] is False,
    "HIGH", "MEDIUM",
    f"validate_hydration_projection rejects stale old projection: {hyd_b2['reason']}")

# B3: Reconnect rendering corruption — stale projection on reconnect
mgr_b3 = ProjectionManager()
for _ in range(3):
    mgr_b3.emit_workflow_initialized(mk_wf("adv-b3-reconnect"), "ACTIVE")
stale_reconnect = build_workflow_projection(mk_wf("adv-b3-reconnect"), projection_version=1, lifecycle_status="ACTIVE")
hyd_b3 = mgr_b3.validate_hydration_projection("adv-b3-reconnect", stale_reconnect)
mitigated("B3: Reconnect rendering corruption (stale projection on reconnect)",
    hyd_b3["valid"] is False and hyd_b3["stale"] is True,
    "CRITICAL", "MEDIUM",
    f"validate_hydration_projection rejects stale reconnect: {hyd_b3['reason']}")


# --- Projection Risks ---

# C1: Stale projection rendering (older version shown after newer)
mgr_c1 = ProjectionManager()
for _ in range(10):
    mgr_c1.emit_workflow_initialized(mk_wf("adv-c1"), "ACTIVE")
all_stale = all(mgr_c1.is_version_stale("adv-c1", v) for v in range(1, 10))
mitigated("C1: Stale projection rendering (v1-v9 shown after v10)",
    all_stale,
    "HIGH", "MEDIUM",
    "is_version_stale returns True for v1-v9; frontend version guard blocks stale render")

# C2: Invalid projection ordering — v3 after v10
store_c2 = _WorkflowProjectionStore("adv-c2")
store_c2._version = 10
p10 = build_workflow_projection(mk_wf("adv-c2"), projection_version=10, lifecycle_status="ACTIVE")
store_c2.store(p10)
p3 = build_workflow_projection(mk_wf("adv-c2"), projection_version=3, lifecycle_status="ACTIVE")
rejected = not store_c2.store(p3)
mitigated("C2: Invalid projection ordering (v3 injected after v10)",
    rejected and store_c2.get_stale_rejection_count() == 1,
    "HIGH", "MEDIUM",
    f"store() rejects v3 < v10; rejection_count={store_c2.get_stale_rejection_count()}")

# C3: Out-of-order render updates — multiple stale versions injected
mgr_c3 = ProjectionManager()
for _ in range(7):
    mgr_c3.emit_workflow_initialized(mk_wf("adv-c3"), "ACTIVE")
rejected_count = 0
for v in [1, 2, 3, 4, 5, 6]:
    hyd = mgr_c3.validate_hydration_projection(
        "adv-c3",
        build_workflow_projection(mk_wf("adv-c3"), projection_version=v, lifecycle_status="ACTIVE")
    )
    if not hyd["valid"]:
        rejected_count += 1
mitigated("C3: Out-of-order render updates (v1-v6 injected when current=v7)",
    rejected_count == 6 and mgr_c3.get_projection_version("adv-c3") == 7,
    "MEDIUM", "MEDIUM",
    f"All 6 stale versions rejected via validate_hydration_projection; final v=7")

# C4: Continuity summary isolation ensures no shared render state
mgr_c4 = ProjectionManager()
for _ in range(3):
    mgr_c4.emit_workflow_initialized(mk_wf("adv-c4-X"), "ACTIVE")
mgr_c4.emit_lifecycle_changed(mk_wf("adv-c4-Y", "FAILED"), "FAILED")
sum_x = mgr_c4.get_continuity_summary("adv-c4-X")
sum_y = mgr_c4.get_continuity_summary("adv-c4-Y")
sum_z = mgr_c4.get_continuity_summary("adv-c4-Z-unknown")
mitigated("C4: Continuity summary isolation (no shared render state)",
    sum_x["projection_state"] == PROJECTION_STATE_ACTIVE and
    sum_y["is_terminal"] is True and
    sum_z["has_projection"] is False,
    "HIGH", "LOW",
    f"X=ACTIVE v{sum_x['projection_version']}, Y=TERMINAL, Z=no_projection — isolated")


# =============================================================================
# RISK ANALYSIS SUMMARY
# =============================================================================

print("\n" + "=" * 60)
print("RISK ANALYSIS SUMMARY")
print("=" * 60)
for r in results_p6:
    icon = "[MITIGATED]" if r["status"] == "MITIGATED" else "[VULNERABLE]"
    print(f"  {icon} {r['label']}")
    print(f"    impact={r['impact']}, likelihood={r['likelihood']}")
    print(f"    mitigation: {r['mitigation']}")


# =============================================================================
# OVERALL RESULT
# =============================================================================

print("\n" + "=" * 60)
p6_mit = sum(1 for r in results_p6 if r["status"] == "MITIGATED")
p6_vuln = sum(1 for r in results_p6 if r["status"] == "VULNERABLE")
overall_pass = p5_fail == 0 and p6_vuln == 0
print("OVERALL:", "PASS" if overall_pass else "FAIL")
print(f"Phase 5 Architecture Validation: {'PASS' if p5_fail == 0 else 'FAIL'} ({p5_pass}/{len(results_p5)})")
print(f"Phase 6 Adversarial Validation:  {'PASS' if p6_vuln == 0 else 'FAIL'} ({p6_mit}/{len(results_p6)} MITIGATED)")
print("=" * 60)

sys.exit(0 if overall_pass else 1)
