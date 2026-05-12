"""
CATEGORY: PROJECTION + ADVERSARIAL
AUTHORITY_LAYER: Projection Synchronization Validation
VALIDATES:
  - Projection continuity architecture
  - Architecture validation against contracts
  - Adversarial scenarios targeting continuity
  - Hydration continuity
  - Terminal stability
  - Stream ordering
ENTRYPOINT: projection_manager
DIRECT_INTERNAL_CALLS:
  - projection_schema internals
  - projection_manager internals
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_PROJECTION_SYSTEM
TEST_INTENT: UNIT_LEVEL_VALIDATION
ARCHITECTURAL_SCOPE: Projection continuity architecture

---

PHASE 5 + PHASE 6 — Projection Continuity Architecture & Adversarial Validation (Phase 4A.1)

Phase 5: Architecture validation against PROJECTION_CONTINUITY_CONTRACT_V1 and CANONICAL_PROJECTION_MODEL_V1
Phase 6: Adversarial scenarios targeting continuity, hydration, terminal stability, stream ordering

Per PROJECTION_CONTINUITY_CONTRACT_V1 §1-14
Per CANONICAL_PROJECTION_MODEL_V1 §3,§4,§6,§9,§13,§14
"""

import sys
import os
import inspect
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

results_p5 = []
results_p6 = []


def check(phase_list, id_, label, condition, evidence):
    status = "PASS" if condition else "FAIL"
    phase_list.append({"id": id_, "label": label, "status": status, "evidence": evidence})
    icon = "[PASS]" if condition else "[FAIL]"
    print(f"  {icon} {id_}: {label}")
    if not condition:
        print(f"    EVIDENCE FAIL: {evidence}")


def mitigated(label, condition, impact, likelihood, mitigation):
    status = "MITIGATED" if condition else "VULNERABLE"
    results_p6.append({
        "label": label, "status": status,
        "impact": impact, "likelihood": likelihood, "mitigation": mitigation
    })
    icon = "[MITIGATED]" if condition else "[VULNERABLE]"
    print(f"  {icon} {label}")


# =============================================================================
# PHASE 5 — ARCHITECTURE VALIDATION
# =============================================================================

print("\n" + "=" * 60)
print("PHASE 5 — CONTINUITY ARCHITECTURE VALIDATION")
print("=" * 60)

import system.orchestrator.projection_manager as pm_mod
import system.orchestrator.projection_schema as schema_mod
import system.interface.event_bus as bus_mod

pm_src = inspect.getsource(pm_mod)
schema_src = inspect.getsource(schema_mod)
bus_src = inspect.getsource(bus_mod)

import ai_lab_gui.backend.api as api_mod
api_src = inspect.getsource(api_mod)

# R1: Continuity remains separate from lifecycle authority
# projection_manager does not own or mutate workflow lifecycle state
check(results_p5, "R1", "Continuity separate from lifecycle authority",
    "_update_workflow_state" not in pm_src and "_workflow_state_registry" not in pm_src,
    "projection_manager.py does not import/call _update_workflow_state or _workflow_state_registry")

# R2: Continuity remains separate from projection ownership
# continuity methods (validate_hydration_projection, get_continuity_summary) do NOT emit projections autonomously
check(results_p5, "R2", "Continuity validation is read-only (no autonomous emission)",
    "validate_hydration_projection" in pm_src and
    "next_version()" not in inspect.getsource(pm_mod.ProjectionManager.validate_hydration_projection),
    "validate_hydration_projection does not call next_version() — read-only, no autonomous emission")

# R3: GUI remains projection-render-only (no lifecycle synthesis in WorkflowPanel)
import os
wp_path = os.path.join(os.path.dirname(__file__), "..", "ai_lab_gui", "frontend", "src", "components", "WorkflowPanel.jsx")
with open(wp_path, encoding="utf-8") as f:
    wp_src = f.read()
# WorkflowPanel must not call emit_* or directly write lifecycle state
gui_no_emit = "emit_workflow_initialized" not in wp_src and "emit_lifecycle_changed" not in wp_src
# WorkflowPanel must not synthesize lifecycle — we check it reads from `result` prop only
gui_no_synth = "_update_workflow_state" not in wp_src and "lifecycle_status =" not in wp_src
check(results_p5, "R3", "GUI remains projection-render-only",
    gui_no_emit and gui_no_synth,
    "WorkflowPanel.jsx has no emit_* calls and no lifecycle synthesis")

# R4: API remains transport-only (new continuity endpoint does not mutate)
api_no_mutation = (
    "emit_workflow_initialized" not in api_src and
    "emit_lifecycle_changed" not in api_src and
    "emit_step_updated" not in api_src and
    "emit_output_updated" not in api_src
)
api_has_continuity = "get_projection_continuity" in api_src or "/continuity" in api_src
check(results_p5, "R4", "API transport-only with continuity diagnostics endpoint",
    api_no_mutation and api_has_continuity,
    "api.py: no emit_* calls; /continuity endpoint exists as read-only transport")

# R5: Orchestrator remains projection owner
orch_path = os.path.join(os.path.dirname(__file__), "..", "system", "orchestrator", "orchestrator_runtime.py")
with open(orch_path, encoding="utf-8") as f:
    orch_src = f.read()
check(results_p5, "R5", "Orchestrator remains projection owner",
    "get_projection_manager" in orch_src and "emit_workflow_initialized" in orch_src,
    "orchestrator_runtime.py uses get_projection_manager and emits projections")

# R6: Terminal projections remain stable
from system.orchestrator.projection_manager import ProjectionManager
from system.orchestrator.projection_schema import (
    PROJECTION_STATE_TERMINAL, PROJECTION_STATE_ACTIVE, build_workflow_projection
)

def _wf(wf_id, status="COMPLETED"):
    return {
        "id": wf_id, "name": "test", "status": status,
        "steps": [{"id": "s1", "type": "EXECUTE_API", "purpose": "p", "expected_outcome": "ok",
                   "risk": "LOW", "importance": "MEDIUM", "depends_on": [], "resource_targets": [],
                   "status": "PENDING", "retries": 0}]
    }

mgr_test = ProjectionManager()
wf_term = _wf("arch-term-test")
mgr_test.emit_lifecycle_changed(wf_term, "COMPLETED")
term_v = mgr_test.get_projection_version("arch-term-test")
# Try ACTIVE overwrite
result_after = mgr_test.emit_lifecycle_changed(_wf("arch-term-test", "ACTIVE"), "ACTIVE")
still_terminal = result_after["projection_state"] == PROJECTION_STATE_TERMINAL
still_same_version = mgr_test.get_projection_version("arch-term-test") == term_v
check(results_p5, "R6", "Terminal projections remain stable after COMPLETED",
    still_terminal and still_same_version,
    f"COMPLETED projection at v{term_v} unchanged after ACTIVE overwrite attempt")

# R7: Stale projections rejected deterministically
from system.orchestrator.projection_manager import _WorkflowProjectionStore
store_det = _WorkflowProjectionStore("arch-stale-det")
store_det._version = 5
p5 = build_workflow_projection(_wf("arch-stale-det"), 5, "ACTIVE")
store_det.store(p5)
p2 = build_workflow_projection(_wf("arch-stale-det"), 2, "ACTIVE")
rejected = not store_det.store(p2)
check(results_p5, "R7", "Stale projections rejected deterministically",
    rejected and store_det.get_stale_rejection_count() == 1,
    f"v2 rejected after v5 stored; rejection_count={store_det.get_stale_rejection_count()}")

# R8: Workflow-scoped synchronization preserved (no cross-contamination)
mgr_iso = ProjectionManager()
wf_a = _wf("arch-iso-A", "ACTIVE")
wf_b = _wf("arch-iso-B", "COMPLETED")
mgr_iso.emit_workflow_initialized(wf_a, "ACTIVE")
mgr_iso.emit_lifecycle_changed(wf_b, "COMPLETED")
a_state = mgr_iso.get_projection_state("arch-iso-A")
b_state = mgr_iso.get_projection_state("arch-iso-B")
check(results_p5, "R8", "Workflow-scoped synchronization preserved",
    a_state == PROJECTION_STATE_ACTIVE and b_state == PROJECTION_STATE_TERMINAL,
    f"A={a_state}, B={b_state} — isolated projection stores")

# R9: No local lifecycle synthesis in frontend api.js
api_js_path = os.path.join(os.path.dirname(__file__), "..", "ai_lab_gui", "frontend", "src", "api.js")
with open(api_js_path, encoding="utf-8") as f:
    api_js_src = f.read()
has_projection_api = "getProjection" in api_js_src and "getProjectionContinuity" in api_js_src
no_local_synth = "lifecycle_status" not in api_js_src and "_update_workflow" not in api_js_src
check(results_p5, "R9", "No local lifecycle synthesis in frontend api.js",
    has_projection_api and no_local_synth,
    "api.js has getProjection/getProjectionContinuity; no lifecycle synthesis")

# R10: bus_sequence_id is observational only (does not influence execution)
bus_seq_in_event = "bus_sequence_id" in bus_src
bus_seq_not_in_orch = "bus_sequence_id" not in orch_src
check(results_p5, "R10", "bus_sequence_id is observational only (not in execution path)",
    bus_seq_in_event and bus_seq_not_in_orch,
    "bus_sequence_id exists in event_bus.py but not in orchestrator_runtime.py execution logic")

p5_pass = sum(1 for r in results_p5 if r["status"] == "PASS")
p5_fail = sum(1 for r in results_p5 if r["status"] == "FAIL")
print(f"\nPhase 5 Result: {p5_pass}/{len(results_p5)} PASS, {p5_fail}/{len(results_p5)} FAIL")


# =============================================================================
# PHASE 6 — ADVERSARIAL VALIDATION
# =============================================================================

print("\n" + "=" * 60)
print("PHASE 6 — CONTINUITY ADVERSARIAL VALIDATION")
print("=" * 60)

from system.orchestrator.projection_manager import ProjectionManager, _WorkflowProjectionStore
from system.orchestrator.projection_schema import (
    PROJECTION_STATE_ACTIVE, PROJECTION_STATE_TERMINAL, PROJECTION_STATE_STALE,
    build_workflow_projection, validate_projection_identity
)
from system.interface.event_bus import EventBus, get_latest_sequence


def mk_wf(wf_id, status="ACTIVE"):
    return {
        "id": wf_id, "name": "adv", "status": status,
        "steps": [{"id": "s1", "type": "EXECUTE_API", "purpose": "p", "expected_outcome": "ok",
                   "risk": "LOW", "importance": "MEDIUM", "depends_on": [], "resource_targets": [],
                   "status": "PENDING", "retries": 0}]
    }

def mk_proj(wf_id, version, state=PROJECTION_STATE_ACTIVE):
    p = build_workflow_projection(mk_wf(wf_id), version, "ACTIVE")
    p["projection_state"] = state
    return p


# --- Stale Risks ---

# A1: Stale replay — old version replayed after newer stored
mgr_a1 = ProjectionManager()
wf = mk_wf("adv-A1")
for _ in range(5):
    mgr_a1.emit_workflow_initialized(wf, "ACTIVE")
store_a1 = mgr_a1._get_or_create_store("adv-A1")
store_a1.store(mk_proj("adv-A1", 1))  # stale replay
mitigated("A1: Stale projection replay (v1 replayed after v5)",
    store_a1.get_stale_rejection_count() == 1 and mgr_a1.get_projection_version("adv-A1") == 5,
    "HIGH", "MEDIUM",
    "store() rejects v1 < v5; rejection_count=1; version stays at 5")

# A2: Delayed stream replay — multiple old versions injected
mgr_a2 = ProjectionManager()
wf = mk_wf("adv-A2")
for _ in range(10):
    mgr_a2.emit_workflow_initialized(wf, "ACTIVE")
store_a2 = mgr_a2._get_or_create_store("adv-A2")
rejected_count = 0
for v in [1, 3, 5, 7]:  # all stale (current is v10)
    stored = store_a2.store(mk_proj("adv-A2", v))
    if not stored:
        rejected_count += 1
mitigated("A2: Delayed stream replay (multiple stale versions injected)",
    rejected_count == 4 and mgr_a2.get_projection_version("adv-A2") == 10,
    "HIGH", "MEDIUM",
    f"store() rejected {rejected_count}/4 stale versions; final version=10")

# A3: Reconnect replay corruption — stale projection on reconnect
mgr_a3 = ProjectionManager()
wf = mk_wf("adv-A3")
for _ in range(3):
    mgr_a3.emit_workflow_initialized(wf, "ACTIVE")
stale_reconnect = mk_proj("adv-A3", 1)
hyd = mgr_a3.validate_hydration_projection("adv-A3", stale_reconnect)
mitigated("A3: Reconnect replay corruption (stale hydration on reconnect)",
    hyd["valid"] is False and hyd["stale"] is True,
    "CRITICAL", "MEDIUM",
    f"validate_hydration_projection rejected stale reconnect: reason={hyd['reason']}")


# --- Hydration Risks ---

# B1: Stale hydration — invalid projection passed for hydration
mgr_b1 = ProjectionManager()
wf = mk_wf("adv-B1")
mgr_b1.emit_workflow_initialized(wf, "ACTIVE")
mgr_b1.emit_workflow_initialized(wf, "ACTIVE")  # v2
stale_hyd = mk_proj("adv-B1", 1)
result_b1 = mgr_b1.validate_hydration_projection("adv-B1", stale_hyd)
mitigated("B1: Stale hydration (old projection used for reload)",
    result_b1["valid"] is False and result_b1["stale"] is True,
    "HIGH", "MEDIUM",
    f"validate_hydration_projection rejected v1 as stale (current=v2): {result_b1['reason']}")

# B2: Invalid workflow restoration — mismatched workflow_id in hydration
mgr_b2 = ProjectionManager()
wf = mk_wf("adv-B2-correct")
mgr_b2.emit_workflow_initialized(wf, "ACTIVE")
proj_wrong = mgr_b2.get_latest_projection("adv-B2-correct")
result_b2 = mgr_b2.validate_hydration_projection("adv-B2-WRONG", proj_wrong)
mitigated("B2: Invalid workflow restoration (workflow_id mismatch in hydration)",
    result_b2["valid"] is False and result_b2["reason"] == "workflow_id_mismatch",
    "CRITICAL", "LOW",
    f"validate_hydration_projection rejected cross-workflow hydration: {result_b2['reason']}")

# B3: Missing projection recovery — unknown workflow_id returns safe None
mgr_b3 = ProjectionManager()
missing = mgr_b3.get_latest_projection("nonexistent-wf")
summary_b3 = mgr_b3.get_continuity_summary("nonexistent-wf")
mitigated("B3: Missing projection recovery (unknown workflow_id)",
    missing is None and summary_b3["has_projection"] is False,
    "LOW", "MEDIUM",
    "get_latest_projection returns None; continuity_summary returns has_projection=False")


# --- Terminal Risks ---

# C1: Terminal regression — ACTIVE overwrite after COMPLETED
mgr_c1 = ProjectionManager()
wf = mk_wf("adv-C1", "COMPLETED")
mgr_c1.emit_lifecycle_changed(wf, "COMPLETED")
v_term = mgr_c1.get_projection_version("adv-C1")
mgr_c1.emit_lifecycle_changed(mk_wf("adv-C1", "ACTIVE"), "ACTIVE")
still_term = mgr_c1.get_projection_state("adv-C1") == PROJECTION_STATE_TERMINAL
still_v = mgr_c1.get_projection_version("adv-C1") == v_term
mitigated("C1: Terminal regression (ACTIVE overwrite after COMPLETED)",
    still_term and still_v,
    "CRITICAL", "MEDIUM",
    f"emit_lifecycle_changed returns existing terminal projection unchanged at v{v_term}")

# C2: Stale ACTIVE overwrite of COMPLETED (direct store injection)
store_c2 = _WorkflowProjectionStore("adv-C2")
p_term = mk_proj("adv-C2", 5, PROJECTION_STATE_TERMINAL)
store_c2._version = 5
store_c2.store(p_term)
p_active_6 = mk_proj("adv-C2", 6, PROJECTION_STATE_ACTIVE)
stored_c2 = store_c2.store(p_active_6)
mitigated("C2: ACTIVE overwrite of TERMINAL via direct store (v6 ACTIVE vs v5 TERMINAL)",
    stored_c2 is False and store_c2.get_stale_rejection_count() == 1,
    "CRITICAL", "LOW",
    "store() rejects v6 ACTIVE when store is TERMINAL; terminal_conflict guard active")

# C3: Stale FAILED replacement — late ACTIVE after FAILED
mgr_c3 = ProjectionManager()
wf = mk_wf("adv-C3", "FAILED")
mgr_c3.emit_lifecycle_changed(wf, "FAILED")
returned_c3 = mgr_c3.emit_lifecycle_changed(mk_wf("adv-C3", "ACTIVE"), "ACTIVE")
mitigated("C3: Stale FAILED replacement (ACTIVE after FAILED)",
    returned_c3["projection_state"] == PROJECTION_STATE_TERMINAL,
    "HIGH", "LOW",
    "emit_lifecycle_changed returns existing terminal FAILED projection unchanged")


# --- Workflow Isolation Risks ---

# D1: Cross-workflow synchronization (wrong workflow events bleeding)
mgr_d1 = ProjectionManager()
wf_d1a = mk_wf("adv-D1-A")
wf_d1b = mk_wf("adv-D1-B", "COMPLETED")
for _ in range(5):
    mgr_d1.emit_workflow_initialized(wf_d1a, "ACTIVE")
mgr_d1.emit_lifecycle_changed(wf_d1b, "COMPLETED")
a_v = mgr_d1.get_projection_version("adv-D1-A")
b_v = mgr_d1.get_projection_version("adv-D1-B")
a_state = mgr_d1.get_projection_state("adv-D1-A")
b_state = mgr_d1.get_projection_state("adv-D1-B")
mitigated("D1: Cross-workflow synchronization contamination",
    a_v == 5 and b_v == 1 and a_state == PROJECTION_STATE_ACTIVE and b_state == PROJECTION_STATE_TERMINAL,
    "CRITICAL", "LOW",
    f"A=ACTIVE v{a_v}, B=TERMINAL v{b_v} — completely isolated stores")

# D2: Workflow switching corruption — bus sequences isolated
bus_d2 = EventBus()
for _ in range(7):
    bus_d2.publish("adv-D2-X", "ev", {})
for _ in range(3):
    bus_d2.publish("adv-D2-Y", "ev", {})
seq_x = bus_d2.get_latest_sequence("adv-D2-X")
seq_y = bus_d2.get_latest_sequence("adv-D2-Y")
seq_z = bus_d2.get_latest_sequence("adv-D2-Z")
mitigated("D2: Workflow switching bus sequence corruption",
    seq_x == 7 and seq_y == 3 and seq_z == 0,
    "MEDIUM", "LOW",
    f"bus_sequences isolated: X={seq_x}, Y={seq_y}, Z(unknown)={seq_z}")

# D3: Continuity summary isolation (no shared state between workflows)
mgr_d3 = ProjectionManager()
for _ in range(4):
    mgr_d3.emit_workflow_initialized(mk_wf("adv-D3-A"), "ACTIVE")
mgr_d3.emit_lifecycle_changed(mk_wf("adv-D3-B", "FAILED"), "FAILED")
sum_a = mgr_d3.get_continuity_summary("adv-D3-A")
sum_b = mgr_d3.get_continuity_summary("adv-D3-B")
sum_c = mgr_d3.get_continuity_summary("adv-D3-C-unknown")
mitigated("D3: Continuity summary isolation across workflows",
    sum_a["projection_version"] == 4 and sum_b["is_terminal"] is True and sum_c["has_projection"] is False,
    "HIGH", "LOW",
    f"A=v{sum_a['projection_version']} ACTIVE, B=TERMINAL, C=no_projection — fully isolated")


# =============================================================================
# RISK ANALYSIS SUMMARY
# =============================================================================

print("\n" + "=" * 60)
print("RISK ANALYSIS SUMMARY")
print("=" * 60)

risk_details = {
    "A1: Stale projection replay (v1 replayed after v5)":
        ("HIGH", "MEDIUM", "store() rejects incoming_version < stored_version; rejection tracked"),
    "A2: Delayed stream replay (multiple stale versions)":
        ("HIGH", "MEDIUM", "store() rejects all stale versions; final_version protected"),
    "A3: Reconnect replay corruption (stale hydration)":
        ("CRITICAL", "MEDIUM", "validate_hydration_projection rejects stale on reconnect"),
    "B1: Stale hydration (old projection for reload)":
        ("HIGH", "MEDIUM", "validate_hydration_projection: stale=True, valid=False"),
    "B2: Invalid workflow restoration (workflow_id mismatch)":
        ("CRITICAL", "LOW", "validate_hydration_projection: workflow_id_mismatch rejected"),
    "B3: Missing projection recovery (unknown workflow_id)":
        ("LOW", "MEDIUM", "get_latest_projection=None; continuity_summary has_projection=False"),
    "C1: Terminal regression (ACTIVE after COMPLETED)":
        ("CRITICAL", "MEDIUM", "emit_lifecycle_changed returns existing TERMINAL unchanged"),
    "C2: ACTIVE overwrite of TERMINAL (direct store injection)":
        ("CRITICAL", "LOW", "store() terminal_conflict guard: non-terminal rejected"),
    "C3: Stale FAILED replacement (ACTIVE after FAILED)":
        ("HIGH", "LOW", "emit_lifecycle_changed returns existing TERMINAL FAILED unchanged"),
    "D1: Cross-workflow contamination":
        ("CRITICAL", "LOW", "per-workflow _WorkflowProjectionStore; isolated _stores dict"),
    "D2: Workflow switching bus sequence corruption":
        ("MEDIUM", "LOW", "per-workflow _sequence_counters in EventBus"),
    "D3: Continuity summary isolation":
        ("HIGH", "LOW", "get_continuity_summary reads from isolated per-workflow store"),
}

for scenario, (impact, likelihood, mit) in risk_details.items():
    r = next((x for x in results_p6 if scenario.split(":")[0] in x["label"]), None)
    status = r["status"] if r else "UNKNOWN"
    icon = "[MITIGATED]" if status == "MITIGATED" else "[VULNERABLE]"
    print(f"  {icon} {scenario}")
    print(f"    impact={impact}, likelihood={likelihood}")
    print(f"    mitigation: {mit}")


# =============================================================================
# OVERALL RESULT
# =============================================================================

print("\n" + "=" * 60)
p6_mit = sum(1 for r in results_p6 if r["status"] == "MITIGATED")
p6_vuln = sum(1 for r in results_p6 if r["status"] == "VULNERABLE")
overall_pass = p5_fail == 0 and p6_vuln == 0
print("OVERALL:", "PASS" if overall_pass else "FAIL")
print(f"Phase 5 Architecture Validation: {'PASS' if p5_fail == 0 else 'FAIL'}")
print(f"Phase 6 Adversarial Validation:  {'PASS' if p6_vuln == 0 else 'FAIL'} ({p6_mit}/{len(results_p6)} MITIGATED)")
print("=" * 60)

sys.exit(0 if overall_pass else 1)
