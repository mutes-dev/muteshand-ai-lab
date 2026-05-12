"""
CATEGORY: PROJECTION
AUTHORITY_LAYER: Projection Synchronization Validation
VALIDATES:
  - Canonical projection rendering pipeline
  - Read-only plan projection rendering
  - Dependency visualization correctness
  - Projection-based workflow switching
  - Projection rendering stability
ENTRYPOINT: projection_manager
DIRECT_INTERNAL_CALLS:
  - projection_schema internals
  - projection_manager internals
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_PROJECTION_SYSTEM
TEST_INTENT: UNIT_LEVEL_VALIDATION
ARCHITECTURAL_SCOPE: Projection rendering layer

---

PHASE 4 — Canonical Plan Rendering Tests (Phase 4B.0)

Tests:
- Canonical projection rendering pipeline (projection data shapes for GUI consumption)
- Read-only plan projection rendering (step list, order, dependencies, lifecycle visibility)
- Dependency visualization correctness (depends_on from canonical projection only)
- Projection-based workflow switching (isolation, no stale carryover)
- Projection rendering stability (stale render rejection, terminal stability)

Per CANONICAL_PROJECTION_MODEL_V1 §2, §3, §8
Per PROJECTION_CONTINUITY_CONTRACT_V1 §6, §9, §11, §12
Per GUI_ARCHITECTURE.txt (projection-render-only)
Per PLAN_CONTROL_CONTRACT_V1 (plan visibility, read-only display)
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.projection_schema import (
    build_workflow_projection,
    build_plan_projection,
    build_step_projection,
    build_projection_identity,
    validate_projection_identity,
    PROJECTION_TYPE_WORKFLOW,
    PROJECTION_TYPE_PLAN,
    PROJECTION_TYPE_STEP,
    PROJECTION_STATE_ACTIVE,
    PROJECTION_STATE_TERMINAL,
    PROJECTION_STATE_STALE,
    PROJECTION_STATE_INVALIDATED,
)
from system.orchestrator.projection_manager import ProjectionManager


def _mk_step(step_id, purpose, status="PENDING", risk="LOW", depends_on=None,
             resources=None, importance="MEDIUM", retries=0, blocked_reason=None,
             exec_result=None):
    s = {
        "id": step_id,
        "type": "EXECUTE_API",
        "purpose": purpose,
        "expected_outcome": f"outcome of {step_id}",
        "risk": risk,
        "importance": importance,
        "depends_on": depends_on or [],
        "resource_targets": resources or [],
        "status": status,
        "retries": retries,
    }
    if blocked_reason:
        s["blocked_reason"] = blocked_reason
    if exec_result:
        s["execution_result"] = exec_result
    return s


def _mk_workflow(wf_id, status="ACTIVE", steps=None):
    return {
        "id": wf_id,
        "name": f"workflow_{wf_id}",
        "status": status,
        "steps": steps or [],
    }


def _log_trace(label, data):
    print(f"  [TRACE:{label}]", data)


# =============================================================================
# SUB-PHASE 3A — Canonical Projection Rendering Pipeline
# =============================================================================

class TestProjectionRenderingPipeline:

    def test_workflow_projection_has_all_render_fields(self):
        """Verify WorkflowProjection contains all fields required by GUI renderer."""
        steps = [_mk_step("s1", "Fetch data"), _mk_step("s2", "Process data")]
        wf = _mk_workflow("wf-render-1", steps=steps)
        p = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")

        # Identity fields required by GUI projection renderer
        assert p["workflow_id"] == "wf-render-1"
        assert p["projection_type"] == PROJECTION_TYPE_WORKFLOW
        assert p["projection_version"] == 1
        assert "projection_timestamp" in p
        assert p["projection_state"] == PROJECTION_STATE_ACTIVE

        # Render fields
        assert p["lifecycle_status"] == "ACTIVE"
        assert p["workflow_name"] == "workflow_wf-render-1"
        assert "steps" in p
        assert "outputs" in p
        assert p["step_count"] == 2

        _log_trace("RENDER_PIPELINE", {
            "workflow_id": p["workflow_id"],
            "projection_version": p["projection_version"],
            "projection_state": p["projection_state"],
            "lifecycle_status": p["lifecycle_status"],
            "step_count": p["step_count"],
        })
        print("  [PASS] workflow projection has all required render fields")

    def test_rendering_originates_from_projection_version(self):
        """Rendering uses projection_version for deterministic ordering."""
        mgr = ProjectionManager()
        wf = _mk_workflow("wf-render-v")
        projections = []
        for _ in range(5):
            p = mgr.emit_workflow_initialized(wf, "ACTIVE")
            projections.append(p["projection_version"])

        # Versions must be monotonically increasing
        assert projections == list(range(1, 6))
        _log_trace("VERSION_PROGRESSION", {"versions": projections})
        print(f"  [PASS] projection version progression deterministic: {projections}")

    def test_no_execution_fields_in_step_projection(self):
        """Step projections MUST NOT expose execution internals (tool_call, raw execution_result)."""
        step = _mk_step("s1", "Do thing", exec_result={"result": "ok"})
        wf = _mk_workflow("wf-render-2", steps=[step])
        p = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")

        step_proj = p["steps"][0]
        # Execution internals MUST NOT be in step projection
        assert "tool_call" not in step_proj
        assert "execution_result" not in step_proj

        # Output is separate from step projection
        assert len(p["outputs"]) == 1
        output = p["outputs"][0]
        assert output["step_id"] == "s1"
        assert "execution_result" in output
        assert "tool_call" not in output

        print("  [PASS] step projection excludes execution internals; output projection is separate")

    def test_workflow_projection_version_increments_on_update(self):
        """Each emission increments projection_version — rendering detects updates via version."""
        mgr = ProjectionManager()
        wf = _mk_workflow("wf-render-incr")
        p1 = mgr.emit_workflow_initialized(wf, "ACTIVE")
        p2 = mgr.emit_step_updated(wf, wf["steps"][0] if wf["steps"] else _mk_step("s1", "x"), "ACTIVE")
        p3 = mgr.emit_lifecycle_changed(wf, "COMPLETED")

        versions = [p1["projection_version"], p2["projection_version"], p3["projection_version"]]
        assert versions[0] < versions[1] < versions[2]
        _log_trace("VERSION_INCREMENT", {"versions": versions})
        print(f"  [PASS] projection_version increments on each update: {versions}")

    def test_projection_identity_stable_across_emissions(self):
        """workflow_id in projection must be stable across all emissions."""
        mgr = ProjectionManager()
        wf = _mk_workflow("wf-stable-id")
        identities = []
        for _ in range(4):
            p = mgr.emit_workflow_initialized(wf, "ACTIVE")
            identities.append(p["workflow_id"])

        assert all(wf_id == "wf-stable-id" for wf_id in identities)
        print("  [PASS] projection workflow_id stable across 4 emissions")


# =============================================================================
# SUB-PHASE 3B — Read-Only Plan View
# =============================================================================

class TestReadOnlyPlanRendering:

    def test_plan_projection_has_steps_in_canonical_order(self):
        """Plan projection preserves original step order — no local reordering."""
        steps = [
            _mk_step("s1", "First step"),
            _mk_step("s2", "Second step"),
            _mk_step("s3", "Third step"),
        ]
        wf = _mk_workflow("wf-plan-1", steps=steps)
        p = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")

        rendered_ids = [s["step_id"] for s in p["steps"]]
        assert rendered_ids == ["s1", "s2", "s3"]
        _log_trace("PLAN_STEP_ORDER", {"step_ids": rendered_ids})
        print(f"  [PASS] plan step order canonical: {rendered_ids}")

    def test_plan_projection_displays_lifecycle_visibility_per_step(self):
        """Each step projection includes lifecycle-visible fields: status, purpose, retries."""
        steps = [
            _mk_step("s1", "Process A", status="COMPLETED", retries=1),
            _mk_step("s2", "Process B", status="ACTIVE"),
            _mk_step("s3", "Process C", status="PENDING"),
        ]
        wf = _mk_workflow("wf-plan-2", steps=steps)
        p = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")

        s1 = p["steps"][0]
        s2 = p["steps"][1]
        s3 = p["steps"][2]

        assert s1["status"] == "COMPLETED"
        assert s1["retries"] == 1
        assert s2["status"] == "ACTIVE"
        assert s3["status"] == "PENDING"
        assert all("purpose" in s for s in p["steps"])
        assert all("expected_outcome" in s for s in p["steps"])

        _log_trace("LIFECYCLE_VISIBILITY", {
            "steps": [(s["step_id"], s["status"]) for s in p["steps"]]
        })
        print("  [PASS] plan step lifecycle visibility correct: COMPLETED, ACTIVE, PENDING")

    def test_plan_projection_displays_projection_metadata(self):
        """Step projections include projection identity metadata for version tracking."""
        steps = [_mk_step("s1", "Step")]
        wf = _mk_workflow("wf-plan-3", steps=steps)
        p = build_workflow_projection(wf, projection_version=7, lifecycle_status="ACTIVE")

        step = p["steps"][0]
        assert step["projection_version"] == 7
        assert "projection_timestamp" in step
        assert step["projection_type"] == PROJECTION_TYPE_STEP
        assert step["workflow_id"] == "wf-plan-3"
        print("  [PASS] step projection includes projection metadata (v7, type=step, wf_id)")

    def test_plan_projection_no_mutation_fields(self):
        """Plan projection must not contain any edit/mutation controls."""
        steps = [_mk_step("s1", "Test step")]
        wf = _mk_workflow("wf-plan-4", steps=steps)
        p = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")

        # These mutation/control fields MUST NOT be present
        forbidden = [
            "editable", "can_edit", "edit_handler", "mutation_token",
            "reorder_allowed", "can_retry", "can_pause",
            "on_click", "on_change", "handler",
        ]
        for field in forbidden:
            assert field not in p, f"Forbidden field '{field}' found in projection root"
            for step in p["steps"]:
                assert field not in step, f"Forbidden field '{field}' in step projection"

        print("  [PASS] plan projection has no mutation/control fields")

    def test_plan_projection_state_updates_deterministically(self):
        """Projection state updates deterministically from orchestrator — no local synthesis."""
        mgr = ProjectionManager()
        wf = _mk_workflow("wf-plan-det")
        p_init = mgr.emit_workflow_initialized(wf, "ACTIVE")
        assert p_init["projection_state"] == PROJECTION_STATE_ACTIVE

        p_term = mgr.emit_lifecycle_changed(wf, "COMPLETED")
        assert p_term["projection_state"] == PROJECTION_STATE_TERMINAL

        # State progression logged for render trace
        _log_trace("PLAN_STATE_PROGRESSION", {
            "init": p_init["projection_state"],
            "terminal": p_term["projection_state"],
            "versions": [p_init["projection_version"], p_term["projection_version"]],
        })
        print("  [PASS] plan projection state deterministic: ACTIVE -> TERMINAL")

    def test_blocked_step_shows_blocked_reason(self):
        """BLOCKED steps include blocked_reason for display."""
        step = _mk_step("s1", "Blocked step", status="BLOCKED",
                        blocked_reason="Waiting for approval")
        wf = _mk_workflow("wf-blocked", steps=[step])
        p = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")

        s = p["steps"][0]
        assert s["status"] == "BLOCKED"
        assert s.get("blocked_reason") == "Waiting for approval"
        print("  [PASS] blocked step includes blocked_reason for display")


# =============================================================================
# SUB-PHASE 3C — Dependency Visualization
# =============================================================================

class TestDependencyVisualization:

    def test_depends_on_passes_through_canonical_projection(self):
        """depends_on from canonical step projection — not derived locally."""
        steps = [
            _mk_step("s1", "Fetch"),
            _mk_step("s2", "Process", depends_on=["s1"]),
            _mk_step("s3", "Store", depends_on=["s2"]),
        ]
        wf = _mk_workflow("wf-dep-1", steps=steps)
        p = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")

        dep_map = {s["step_id"]: s["depends_on"] for s in p["steps"]}
        assert dep_map["s1"] == []
        assert dep_map["s2"] == ["s1"]
        assert dep_map["s3"] == ["s2"]

        _log_trace("DEPENDENCY_MAP", {"dep_map": dep_map})
        print(f"  [PASS] depends_on passes through projection correctly: {dep_map}")

    def test_multi_dependency_preserved(self):
        """Multiple dependencies per step preserved from canonical projection."""
        steps = [
            _mk_step("s1", "A"),
            _mk_step("s2", "B"),
            _mk_step("s3", "C", depends_on=["s1", "s2"]),
        ]
        wf = _mk_workflow("wf-dep-2", steps=steps)
        p = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")

        s3 = next(s for s in p["steps"] if s["step_id"] == "s3")
        assert set(s3["depends_on"]) == {"s1", "s2"}
        print(f"  [PASS] multi-dependency preserved: s3.depends_on={s3['depends_on']}")

    def test_no_hidden_dependency_synthesis(self):
        """Projection schema MUST NOT add implicit dependencies not in source step."""
        steps = [
            _mk_step("s1", "A"),
            _mk_step("s2", "B"),  # no depends_on — independent
        ]
        wf = _mk_workflow("wf-dep-3", steps=steps)
        p = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")

        s2 = next(s for s in p["steps"] if s["step_id"] == "s2")
        # MUST NOT infer sequential dependency
        assert s2["depends_on"] == []
        print("  [PASS] no hidden dependencies synthesized; s2.depends_on=[]")

    def test_dependency_ordering_deterministic(self):
        """depends_on order preserved from canonical source."""
        steps = [
            _mk_step("s1", "A"),
            _mk_step("s2", "B"),
            _mk_step("s3", "C"),
            _mk_step("s4", "D", depends_on=["s1", "s2", "s3"]),
        ]
        wf = _mk_workflow("wf-dep-4", steps=steps)
        p = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")

        s4 = next(s for s in p["steps"] if s["step_id"] == "s4")
        assert s4["depends_on"] == ["s1", "s2", "s3"]
        print(f"  [PASS] dependency ordering deterministic: {s4['depends_on']}")

    def test_dependency_workflow_scoped(self):
        """Dependencies isolated per workflow — no cross-workflow dep contamination."""
        steps_a = [_mk_step("s1", "A1"), _mk_step("s2", "A2", depends_on=["s1"])]
        steps_b = [_mk_step("s1", "B1"), _mk_step("s2", "B2")]  # B has no deps

        wf_a = _mk_workflow("wf-dep-A", steps=steps_a)
        wf_b = _mk_workflow("wf-dep-B", steps=steps_b)

        p_a = build_workflow_projection(wf_a, projection_version=1, lifecycle_status="ACTIVE")
        p_b = build_workflow_projection(wf_b, projection_version=1, lifecycle_status="ACTIVE")

        a_deps = {s["step_id"]: s["depends_on"] for s in p_a["steps"]}
        b_deps = {s["step_id"]: s["depends_on"] for s in p_b["steps"]}

        assert a_deps["s2"] == ["s1"]
        assert b_deps["s2"] == []
        assert p_a["workflow_id"] != p_b["workflow_id"]

        _log_trace("WORKFLOW_SCOPED_DEPS", {
            "wf_a_deps": a_deps,
            "wf_b_deps": b_deps
        })
        print(f"  [PASS] dependency visualization workflow-scoped: A.s2={a_deps['s2']}, B.s2={b_deps['s2']}")

    def test_resource_targets_in_step_projection(self):
        """resource_targets passes through from canonical step projection."""
        step = _mk_step("s1", "Write file", resources=["disk", "network"])
        wf = _mk_workflow("wf-dep-res", steps=[step])
        p = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")

        s = p["steps"][0]
        assert s["resource_targets"] == ["disk", "network"]
        print(f"  [PASS] resource_targets in step projection: {s['resource_targets']}")


# =============================================================================
# SUB-PHASE 3D — Projection-Based Workflow Switching
# =============================================================================

class TestProjectionWorkflowSwitching:

    def test_workflow_switch_clears_prior_projection(self):
        """Switching workflows must not carry stale projection from prior workflow."""
        mgr = ProjectionManager()

        wf_a = _mk_workflow("wf-switch-A")
        wf_b = _mk_workflow("wf-switch-B")

        for _ in range(5):
            mgr.emit_workflow_initialized(wf_a, "ACTIVE")
        for _ in range(2):
            mgr.emit_workflow_initialized(wf_b, "ACTIVE")

        p_a = mgr.get_latest_projection("wf-switch-A")
        p_b = mgr.get_latest_projection("wf-switch-B")

        # Each workflow has its own projection — no carryover
        assert p_a["workflow_id"] == "wf-switch-A"
        assert p_b["workflow_id"] == "wf-switch-B"
        assert p_a["projection_version"] == 5
        assert p_b["projection_version"] == 2

        _log_trace("WORKFLOW_SWITCH", {
            "wf_a_version": p_a["projection_version"],
            "wf_b_version": p_b["projection_version"],
        })
        print(f"  [PASS] workflow switch preserves isolation: A=v5, B=v2, no carryover")

    def test_workflow_switch_no_cross_contamination(self):
        """Step data from workflow A MUST NOT appear in workflow B projection."""
        steps_a = [_mk_step("s1", "A task A", status="COMPLETED")]
        steps_b = [_mk_step("s1", "B task B", status="PENDING")]

        wf_a = _mk_workflow("wf-iso-switch-A", steps=steps_a)
        wf_b = _mk_workflow("wf-iso-switch-B", steps=steps_b)

        p_a = build_workflow_projection(wf_a, projection_version=1, lifecycle_status="COMPLETED")
        p_b = build_workflow_projection(wf_b, projection_version=1, lifecycle_status="ACTIVE")

        a_purposes = {s["purpose"] for s in p_a["steps"]}
        b_purposes = {s["purpose"] for s in p_b["steps"]}

        assert "A task A" in a_purposes
        assert "A task A" not in b_purposes
        assert "B task B" in b_purposes
        assert "B task B" not in a_purposes
        print("  [PASS] no cross-workflow step contamination in projection switch")

    def test_stale_workflow_projection_rejected_on_switch(self):
        """After workflow switch, stale projection from old workflow is rejected."""
        mgr = ProjectionManager()
        wf_a = _mk_workflow("wf-sw-stale-A")
        wf_b = _mk_workflow("wf-sw-stale-B")

        for _ in range(3):
            mgr.emit_workflow_initialized(wf_a, "ACTIVE")
        mgr.emit_workflow_initialized(wf_b, "ACTIVE")

        # Simulate: stale wf_a projection tries to update after switch
        stale_a_proj = build_workflow_projection(wf_a, projection_version=1, lifecycle_status="ACTIVE")
        hyd_result = mgr.validate_hydration_projection("wf-sw-stale-B", stale_a_proj)
        assert hyd_result["valid"] is False
        assert hyd_result["reason"] == "workflow_id_mismatch"

        _log_trace("STALE_SWITCH_REJECTION", {
            "stale_wf_id": stale_a_proj["workflow_id"],
            "active_wf_id": "wf-sw-stale-B",
            "reason": hyd_result["reason"],
        })
        print(f"  [PASS] stale workflow projection rejected on switch: {hyd_result['reason']}")

    def test_switching_preserves_continuity_anchor(self):
        """Continuity anchor is independent per workflow — switch does not corrupt anchor."""
        mgr = ProjectionManager()
        wf_a = _mk_workflow("wf-cont-A")
        wf_b = _mk_workflow("wf-cont-B")

        for _ in range(4):
            mgr.emit_workflow_initialized(wf_a, "ACTIVE")
        for _ in range(2):
            mgr.emit_workflow_initialized(wf_b, "ACTIVE")

        anchor_a = mgr.get_continuity_anchor("wf-cont-A")
        anchor_b = mgr.get_continuity_anchor("wf-cont-B")
        anchor_unknown = mgr.get_continuity_anchor("wf-unknown")

        assert anchor_a == 4
        assert anchor_b == 2
        assert anchor_unknown == 0

        _log_trace("CONTINUITY_ANCHORS", {
            "wf_a": anchor_a, "wf_b": anchor_b, "unknown": anchor_unknown
        })
        print(f"  [PASS] continuity anchors isolated: A={anchor_a}, B={anchor_b}, unknown={anchor_unknown}")

    def test_projections_do_not_merge_across_workflows(self):
        """Projections from different workflows MUST NOT be merged locally."""
        mgr = ProjectionManager()
        wf_a = _mk_workflow("wf-merge-A")
        wf_b = _mk_workflow("wf-merge-B")

        for _ in range(3):
            mgr.emit_workflow_initialized(wf_a, "ACTIVE")
        mgr.emit_lifecycle_changed(wf_b, "COMPLETED")

        sum_a = mgr.get_continuity_summary("wf-merge-A")
        sum_b = mgr.get_continuity_summary("wf-merge-B")

        assert sum_a["is_terminal"] is False
        assert sum_b["is_terminal"] is True
        assert sum_a["projection_version"] != sum_b["projection_version"]
        print(f"  [PASS] projections not merged: A(active,v{sum_a['projection_version']}), B(terminal,v{sum_b['projection_version']})")


# =============================================================================
# SUB-PHASE 3E — Projection Rendering Stability
# =============================================================================

class TestProjectionRenderingStability:

    def test_stale_render_rejection(self):
        """Stale projection (older version) must be rejected — not applied to render."""
        mgr = ProjectionManager()
        wf = _mk_workflow("wf-stale-render")
        for _ in range(5):
            mgr.emit_workflow_initialized(wf, "ACTIVE")
        current_v = mgr.get_projection_version("wf-stale-render")

        stale = build_workflow_projection(wf, projection_version=2, lifecycle_status="ACTIVE")
        is_stale = mgr.is_version_stale("wf-stale-render", 2)
        assert is_stale is True
        assert current_v == 5

        _log_trace("STALE_RENDER_REJECTION", {
            "candidate_version": 2,
            "current_version": current_v,
            "stale": is_stale,
        })
        print(f"  [PASS] stale render rejected: v2 is stale when current=v{current_v}")

    def test_terminal_render_stability(self):
        """TERMINAL projection render remains stable — non-terminal cannot overwrite."""
        mgr = ProjectionManager()
        wf = _mk_workflow("wf-term-render", status="COMPLETED")
        mgr.emit_lifecycle_changed(wf, "COMPLETED")
        term_v = mgr.get_projection_version("wf-term-render")
        term_proj = mgr.get_latest_projection("wf-term-render")

        # Simulate render update attempt with ACTIVE projection
        result = mgr.emit_lifecycle_changed(_mk_workflow("wf-term-render", "ACTIVE"), "ACTIVE")
        assert result["projection_state"] == PROJECTION_STATE_TERMINAL
        assert mgr.get_projection_version("wf-term-render") == term_v

        _log_trace("TERMINAL_STABILITY", {
            "terminal_version": term_v,
            "after_overwrite_attempt_version": mgr.get_projection_version("wf-term-render"),
            "projection_state": result["projection_state"],
        })
        print(f"  [PASS] terminal render stable at v{term_v}: ACTIVE overwrite rejected")

    def test_reconnect_render_hydration_safe(self):
        """Reconnect hydration uses latest valid projection — no stale restoration."""
        mgr = ProjectionManager()
        wf = _mk_workflow("wf-reconnect-render")
        for _ in range(3):
            mgr.emit_workflow_initialized(wf, "ACTIVE")
        current = mgr.get_latest_projection("wf-reconnect-render")

        # Validate current projection for safe hydration
        hyd = mgr.validate_hydration_projection("wf-reconnect-render", current)
        assert hyd["valid"] is True

        # Stale hydration must be rejected
        stale = build_workflow_projection(wf, projection_version=1, lifecycle_status="ACTIVE")
        stale_hyd = mgr.validate_hydration_projection("wf-reconnect-render", stale)
        assert stale_hyd["valid"] is False
        assert stale_hyd["stale"] is True

        _log_trace("RECONNECT_RENDER_HYDRATION", {
            "current_valid": hyd["valid"],
            "stale_valid": stale_hyd["valid"],
            "stale_reason": stale_hyd["reason"],
        })
        print(f"  [PASS] reconnect hydration: current=valid, stale=rejected ({stale_hyd['reason']})")

    def test_continuity_safe_rerendering(self):
        """Re-rendering with same version is idempotent — no stale rejection counted."""
        mgr = ProjectionManager()
        wf = _mk_workflow("wf-idempotent-render")
        mgr.emit_workflow_initialized(wf, "ACTIVE")  # v1
        proj = mgr.get_latest_projection("wf-idempotent-render")

        # Re-applying v1 is idempotent (same version, not stale)
        is_stale = mgr.is_version_stale("wf-idempotent-render", 1)
        assert is_stale is False  # same version is not stale
        assert mgr.get_stale_rejection_count("wf-idempotent-render") == 0
        print("  [PASS] same-version re-render is idempotent; not stale")

    def test_invalid_projection_swap_rejected(self):
        """Invalid projection (wrong workflow_id) is rejected for render hydration."""
        mgr = ProjectionManager()
        wf_a = _mk_workflow("wf-swap-A")
        wf_b = _mk_workflow("wf-swap-B")
        mgr.emit_workflow_initialized(wf_a, "ACTIVE")
        mgr.emit_workflow_initialized(wf_b, "ACTIVE")

        # Get wf_a's projection and try to render it as wf_b
        p_a = mgr.get_latest_projection("wf-swap-A")
        result = mgr.validate_hydration_projection("wf-swap-B", p_a)
        assert result["valid"] is False
        assert result["reason"] == "workflow_id_mismatch"
        print(f"  [PASS] invalid projection swap rejected: {result['reason']}")

    def test_projection_render_version_traces(self):
        """Capture full projection render trace for verification."""
        mgr = ProjectionManager()
        steps = [
            _mk_step("s1", "Fetch data", status="PENDING"),
            _mk_step("s2", "Analyse", depends_on=["s1"], status="PENDING"),
            _mk_step("s3", "Store result", depends_on=["s2"], status="PENDING"),
        ]
        wf = _mk_workflow("wf-render-trace", steps=steps)
        render_trace = []

        p = mgr.emit_workflow_initialized(wf, "ACTIVE")
        render_trace.append({"event": "init", "v": p["projection_version"], "state": p["projection_state"]})

        wf["steps"][0]["status"] = "ACTIVE"
        p = mgr.emit_step_updated(wf, wf["steps"][0], "ACTIVE")
        render_trace.append({"event": "s1_active", "v": p["projection_version"], "state": p["projection_state"]})

        wf["steps"][0]["status"] = "COMPLETED"
        wf["steps"][0]["execution_result"] = {"result": "fetched"}
        p = mgr.emit_step_updated(wf, wf["steps"][0], "ACTIVE")
        render_trace.append({"event": "s1_done", "v": p["projection_version"], "state": p["projection_state"]})

        wf["steps"][1]["status"] = "ACTIVE"
        p = mgr.emit_step_updated(wf, wf["steps"][1], "ACTIVE")
        render_trace.append({"event": "s2_active", "v": p["projection_version"], "state": p["projection_state"]})

        wf["status"] = "COMPLETED"
        p = mgr.emit_lifecycle_changed(wf, "COMPLETED")
        render_trace.append({"event": "terminal", "v": p["projection_version"], "state": p["projection_state"]})

        print(f"\n  RENDER TRACE:")
        for entry in render_trace:
            print(f"    {entry}")

        versions = [e["v"] for e in render_trace]
        assert versions == sorted(versions)
        assert render_trace[-1]["state"] == PROJECTION_STATE_TERMINAL
        print("  [PASS] render trace: monotonic versions, terminal at end")


# =============================================================================
# WORKFLOW SWITCH TRACES (Raw)
# =============================================================================

class TestWorkflowSwitchTraces:

    def test_full_workflow_switch_trace(self):
        """End-to-end workflow switching trace with continuity verification."""
        mgr = ProjectionManager()
        trace = []

        # Workflow A lifecycle
        wf_a = _mk_workflow("wf-trace-A")
        for i in range(3):
            p = mgr.emit_workflow_initialized(wf_a, "ACTIVE")
            trace.append({
                "workflow": "A",
                "event": f"emit_{i+1}",
                "v": p["projection_version"],
                "state": p["projection_state"],
                "wf_id": p["workflow_id"],
            })
        p_term_a = mgr.emit_lifecycle_changed(wf_a, "COMPLETED")
        trace.append({
            "workflow": "A",
            "event": "terminal",
            "v": p_term_a["projection_version"],
            "state": p_term_a["projection_state"],
        })

        # Switch to workflow B
        wf_b = _mk_workflow("wf-trace-B")
        for i in range(2):
            p = mgr.emit_workflow_initialized(wf_b, "ACTIVE")
            trace.append({
                "workflow": "B",
                "event": f"emit_{i+1}",
                "v": p["projection_version"],
                "state": p["projection_state"],
                "wf_id": p["workflow_id"],
            })

        print(f"\n  WORKFLOW SWITCH TRACE:")
        for entry in trace:
            print(f"    {entry}")

        # Verify A's terminal state unchanged after B's emissions
        final_a = mgr.get_latest_projection("wf-trace-A")
        final_b = mgr.get_latest_projection("wf-trace-B")

        assert final_a["projection_state"] == PROJECTION_STATE_TERMINAL
        assert final_b["projection_state"] == PROJECTION_STATE_ACTIVE
        assert final_a["workflow_id"] != final_b["workflow_id"]
        assert final_a["projection_version"] == 4  # 3 init + 1 terminal
        assert final_b["projection_version"] == 2

        print("  [PASS] workflow switch trace: A=TERMINAL v4, B=ACTIVE v2; isolated")

    def test_stale_workflow_switch_trace(self):
        """Stale workflow switch trace — verifies stale render rejection."""
        mgr = ProjectionManager()
        wf = _mk_workflow("wf-stale-switch")
        for _ in range(5):
            mgr.emit_workflow_initialized(wf, "ACTIVE")

        rejection_trace = []
        for stale_v in [1, 2, 3, 4]:
            is_stale = mgr.is_version_stale("wf-stale-switch", stale_v)
            hyd = mgr.validate_hydration_projection(
                "wf-stale-switch",
                build_workflow_projection(wf, projection_version=stale_v, lifecycle_status="ACTIVE")
            )
            rejection_trace.append({
                "candidate_v": stale_v,
                "current_v": 5,
                "is_stale": is_stale,
                "hydration_valid": hyd["valid"],
                "reason": hyd.get("reason"),
            })

        print(f"\n  STALE SWITCH REJECTION TRACE:")
        for entry in rejection_trace:
            print(f"    {entry}")

        assert all(e["is_stale"] for e in rejection_trace)
        assert all(not e["hydration_valid"] for e in rejection_trace)
        print("  [PASS] all stale switch versions rejected: v1-v4 stale when current=v5")


# =============================================================================
# TEST RUNNER
# =============================================================================

def run_all():
    classes = [
        TestProjectionRenderingPipeline,
        TestReadOnlyPlanRendering,
        TestDependencyVisualization,
        TestProjectionWorkflowSwitching,
        TestProjectionRenderingStability,
        TestWorkflowSwitchTraces,
    ]
    total = passed = failed = 0
    failures = []

    for cls in classes:
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        print(f"\n{'='*60}")
        print(f"  {cls.__name__} ({len(methods)} tests)")
        print(f"{'='*60}")
        for m in methods:
            total += 1
            try:
                getattr(instance, m)()
                passed += 1
            except Exception as e:
                failed += 1
                failures.append((cls.__name__, m, str(e)))
                print(f"  [FAIL] {m}: {e}")

    print(f"\n{'='*60}")
    print(f"PLAN RENDERING TEST RESULTS")
    print(f"{'='*60}")
    print(f"Total:  {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    if failures:
        print("\nFAILURES:")
        for cls_name, m, err in failures:
            print(f"  [{cls_name}] {m}: {err}")
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
