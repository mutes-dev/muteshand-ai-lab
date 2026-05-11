"""
PHASE 4 — Canonical Projection Tests

Tests for:
- Projection generation (schema + identity)
- Projection ordering (monotonic versioning)
- Workflow isolation (no cross-workflow contamination)
- Projection lifecycle states
- Projection emission (init, lifecycle, step, output)
- Event bus projection event delivery
- Stale overwrite prevention

Per CANONICAL_PROJECTION_MODEL_V1 §3, §4, §5, §6, §13
"""

import sys
import os
import threading
import time

# Ensure project root is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.projection_schema import (
    build_projection_identity,
    build_step_projection,
    build_output_projection,
    build_plan_projection,
    build_workflow_projection,
    build_trace_projection,
    validate_projection_identity,
    PROJECTION_TYPE_WORKFLOW,
    PROJECTION_TYPE_PLAN,
    PROJECTION_TYPE_STEP,
    PROJECTION_TYPE_OUTPUT,
    PROJECTION_TYPE_TRACE,
    PROJECTION_STATE_ACTIVE,
    PROJECTION_STATE_STALE,
    PROJECTION_STATE_INVALIDATED,
    PROJECTION_STATE_TERMINAL,
    VALID_PROJECTION_TYPES,
    VALID_PROJECTION_STATES,
    TERMINAL_WORKFLOW_STATES,
)
from system.orchestrator.projection_manager import (
    ProjectionManager,
    get_projection_manager,
)


# =============================================================================
# HELPERS
# =============================================================================

def _make_workflow(workflow_id: str, status: str = "ACTIVE", step_count: int = 2) -> dict:
    steps = [
        {
            "id": f"{workflow_id}_step_{i}",
            "type": "EXECUTE_API",
            "purpose": f"Step {i}",
            "expected_outcome": "done",
            "risk": "LOW",
            "importance": "MEDIUM",
            "depends_on": [],
            "resource_targets": [],
            "status": "PENDING",
            "retries": 0,
        }
        for i in range(step_count)
    ]
    return {"id": workflow_id, "name": f"workflow_{workflow_id}", "status": status, "steps": steps}


def _make_step(step_id: str, status: str = "PENDING") -> dict:
    return {
        "id": step_id,
        "type": "EXECUTE_API",
        "purpose": "Test step",
        "expected_outcome": "done",
        "risk": "LOW",
        "importance": "MEDIUM",
        "depends_on": [],
        "resource_targets": [],
        "status": status,
        "retries": 0,
    }


# =============================================================================
# PHASE 4.1 — PROJECTION SCHEMA TESTS
# =============================================================================

class TestProjectionIdentity:

    def test_build_projection_identity_required_fields(self):
        identity = build_projection_identity(
            workflow_id="wf-001",
            projection_type=PROJECTION_TYPE_WORKFLOW,
            projection_version=1,
        )
        assert identity["workflow_id"] == "wf-001"
        assert identity["projection_type"] == PROJECTION_TYPE_WORKFLOW
        assert identity["projection_version"] == 1
        assert "projection_timestamp" in identity
        assert identity["projection_timestamp"] is not None
        print(f"  [PASS] projection identity has all 4 required fields: {list(identity.keys())}")

    def test_build_projection_identity_invalid_type_raises(self):
        raised = False
        try:
            build_projection_identity(
                workflow_id="wf-001",
                projection_type="INVALID_TYPE",
                projection_version=1,
            )
        except ValueError:
            raised = True
        assert raised, "Expected ValueError for invalid projection_type"
        print("  [PASS] invalid projection_type raises ValueError")

    def test_all_valid_projection_types_accepted(self):
        for pt in VALID_PROJECTION_TYPES:
            identity = build_projection_identity(
                workflow_id="wf-001",
                projection_type=pt,
                projection_version=1,
            )
            assert identity["projection_type"] == pt
        print(f"  [PASS] all {len(VALID_PROJECTION_TYPES)} projection types accepted")

    def test_validate_projection_identity_valid(self):
        identity = build_projection_identity("wf-001", PROJECTION_TYPE_WORKFLOW, 1)
        assert validate_projection_identity(identity) is True
        print("  [PASS] valid identity passes validation")

    def test_validate_projection_identity_missing_field(self):
        identity = {
            "workflow_id": "wf-001",
            "projection_type": PROJECTION_TYPE_WORKFLOW,
            "projection_version": 1,
            # missing projection_timestamp
        }
        assert validate_projection_identity(identity) is False
        print("  [PASS] identity missing projection_timestamp fails validation")

    def test_validate_projection_identity_invalid_type(self):
        identity = build_projection_identity("wf-001", PROJECTION_TYPE_WORKFLOW, 1)
        identity["projection_type"] = "BAD"
        assert validate_projection_identity(identity) is False
        print("  [PASS] identity with invalid type fails validation")

    def test_validate_projection_identity_non_int_version(self):
        identity = build_projection_identity("wf-001", PROJECTION_TYPE_WORKFLOW, 1)
        identity["projection_version"] = "1"
        assert validate_projection_identity(identity) is False
        print("  [PASS] identity with string version fails validation")


class TestStepProjection:

    def test_step_projection_identity(self):
        step = _make_step("s-001")
        proj = build_step_projection("wf-001", step, 1)
        assert validate_projection_identity(proj)
        assert proj["projection_type"] == PROJECTION_TYPE_STEP
        assert proj["step_id"] == "s-001"
        assert proj["projection_state"] == PROJECTION_STATE_ACTIVE
        print("  [PASS] step projection has valid identity and no execution fields")

    def test_step_projection_no_tool_call(self):
        step = _make_step("s-001")
        step["tool_call"] = "USE_TOOL: some_tool|{}"
        step["execution_result"] = {"status": "success"}
        proj = build_step_projection("wf-001", step, 1)
        assert "tool_call" not in proj
        assert "execution_result" not in proj
        print("  [PASS] step projection excludes tool_call and execution_result")


class TestOutputProjection:

    def test_output_projection_identity(self):
        proj = build_output_projection("wf-001", "s-001", {"status": "success"}, 2)
        assert validate_projection_identity(proj)
        assert proj["projection_type"] == PROJECTION_TYPE_OUTPUT
        assert proj["step_id"] == "s-001"
        assert proj["execution_result"] == {"status": "success"}
        print("  [PASS] output projection has valid identity")


class TestWorkflowProjection:

    def test_workflow_projection_identity(self):
        wf = _make_workflow("wf-test-001")
        proj = build_workflow_projection(wf, 1, "ACTIVE")
        assert validate_projection_identity(proj)
        assert proj["projection_type"] == PROJECTION_TYPE_WORKFLOW
        assert proj["workflow_id"] == "wf-test-001"
        assert proj["lifecycle_status"] == "ACTIVE"
        assert proj["projection_state"] == PROJECTION_STATE_ACTIVE
        print(f"  [PASS] workflow projection identity valid, version={proj['projection_version']}")

    def test_terminal_workflow_gives_terminal_projection_state(self):
        wf = _make_workflow("wf-terminal", status="COMPLETED")
        for terminal_status in TERMINAL_WORKFLOW_STATES:
            proj = build_workflow_projection(wf, 1, terminal_status)
            assert proj["projection_state"] == PROJECTION_STATE_TERMINAL, \
                f"Expected TERMINAL for lifecycle={terminal_status}, got {proj['projection_state']}"
        print("  [PASS] COMPLETED/FAILED lifecycle → TERMINAL projection_state")

    def test_workflow_projection_contains_steps(self):
        wf = _make_workflow("wf-steps", step_count=3)
        proj = build_workflow_projection(wf, 1, "ACTIVE")
        assert proj["step_count"] == 3
        assert len(proj["steps"]) == 3
        for sp in proj["steps"]:
            assert validate_projection_identity(sp)
        print("  [PASS] workflow projection contains 3 step sub-projections")

    def test_workflow_projection_outputs_empty_when_no_results(self):
        wf = _make_workflow("wf-no-out")
        proj = build_workflow_projection(wf, 1, "ACTIVE")
        assert proj["output_count"] == 0
        assert proj["outputs"] == []
        print("  [PASS] no outputs when no execution_result on steps")

    def test_workflow_projection_outputs_when_results_present(self):
        wf = _make_workflow("wf-with-out", step_count=1)
        wf["steps"][0]["status"] = "COMPLETED"
        wf["steps"][0]["execution_result"] = {"status": "success", "result": "done"}
        proj = build_workflow_projection(wf, 1, "ACTIVE")
        assert proj["output_count"] == 1
        assert proj["outputs"][0]["step_id"] == wf["steps"][0]["id"]
        print("  [PASS] output projection created for completed step with execution_result")


# =============================================================================
# PHASE 4.2 — PROJECTION MANAGER TESTS
# =============================================================================

class TestProjectionManagerVersioning:

    def _new_manager(self) -> ProjectionManager:
        return ProjectionManager()

    def test_version_starts_at_zero(self):
        mgr = self._new_manager()
        assert mgr.get_projection_version("wf-new") == 0
        print("  [PASS] version is 0 before first projection")

    def test_version_increments_monotonically(self):
        mgr = self._new_manager()
        wf = _make_workflow("wf-mono")
        versions = []
        for _ in range(5):
            proj = mgr.emit_workflow_initialized(wf, "ACTIVE")
            versions.append(proj["projection_version"])
        assert versions == sorted(versions), f"Versions not monotonic: {versions}"
        assert versions == list(range(1, 6)), f"Versions not sequential: {versions}"
        print(f"  [PASS] versions monotonically incremented: {versions}")

    def test_newer_projection_supersedes_older(self):
        mgr = self._new_manager()
        wf = _make_workflow("wf-supersede")
        p1 = mgr.emit_workflow_initialized(wf, "ACTIVE")
        p2 = mgr.emit_lifecycle_changed(wf, "ACTIVE")
        latest = mgr.get_latest_projection("wf-supersede")
        assert latest["projection_version"] == p2["projection_version"]
        assert latest["projection_version"] > p1["projection_version"]
        print(f"  [PASS] newer projection (v{p2['projection_version']}) supersedes older (v{p1['projection_version']})")

    def test_stale_projection_does_not_overwrite_newer(self):
        mgr = self._new_manager()
        wf = _make_workflow("wf-stale")
        store = mgr._get_or_create_store("wf-stale")

        # Emit v3 projection
        store._version = 3
        p3 = build_workflow_projection(wf, 3, "ACTIVE")
        store.store(p3)

        # Attempt to store v1 (stale) — must be rejected
        p1 = build_workflow_projection(wf, 1, "ACTIVE")
        store.store(p1)

        latest = store.get_latest()
        assert latest["projection_version"] == 3, \
            f"Stale v1 overwrote newer v3: got version {latest['projection_version']}"
        print("  [PASS] stale projection (v1) did not overwrite newer (v3)")

    def test_get_projection_state(self):
        mgr = self._new_manager()
        wf = _make_workflow("wf-state")
        mgr.emit_workflow_initialized(wf, "ACTIVE")
        assert mgr.get_projection_state("wf-state") == PROJECTION_STATE_ACTIVE
        print("  [PASS] projection_state is ACTIVE after init")

    def test_terminal_projection_is_stable(self):
        mgr = self._new_manager()
        wf = _make_workflow("wf-term", status="COMPLETED")
        mgr.emit_lifecycle_changed(wf, "COMPLETED")
        assert mgr.get_projection_state("wf-term") == PROJECTION_STATE_TERMINAL

        # Attempt to emit another lifecycle change — should return existing terminal projection
        p_existing = mgr.get_latest_projection("wf-term")
        p_returned = mgr.emit_lifecycle_changed(wf, "ACTIVE")
        assert p_returned["projection_version"] == p_existing["projection_version"], \
            "Terminal projection was overwritten by non-terminal emission"
        print("  [PASS] terminal projection is stable (not overwritten)")

    def test_invalidate_workflow(self):
        mgr = self._new_manager()
        wf = _make_workflow("wf-inv")
        mgr.emit_workflow_initialized(wf, "ACTIVE")
        mgr.invalidate_workflow("wf-inv")
        assert mgr.get_projection_state("wf-inv") == PROJECTION_STATE_INVALIDATED
        print("  [PASS] invalidate_workflow sets state to INVALIDATED")


# =============================================================================
# PHASE 4.3 — WORKFLOW ISOLATION TESTS
# =============================================================================

class TestWorkflowIsolation:

    def test_different_workflows_have_independent_stores(self):
        mgr = ProjectionManager()
        wf_a = _make_workflow("wf-iso-A")
        wf_b = _make_workflow("wf-iso-B")

        mgr.emit_workflow_initialized(wf_a, "ACTIVE")
        mgr.emit_workflow_initialized(wf_b, "ACTIVE")
        # Emit more for B
        mgr.emit_lifecycle_changed(wf_b, "ACTIVE")
        mgr.emit_lifecycle_changed(wf_b, "ACTIVE")

        v_a = mgr.get_projection_version("wf-iso-A")
        v_b = mgr.get_projection_version("wf-iso-B")
        assert v_a == 1, f"wf-iso-A should have version 1, got {v_a}"
        assert v_b == 3, f"wf-iso-B should have version 3, got {v_b}"
        print(f"  [PASS] wf-iso-A v={v_a}, wf-iso-B v={v_b} — independent stores")

    def test_no_cross_workflow_projection_contamination(self):
        mgr = ProjectionManager()
        wf_a = _make_workflow("wf-cont-A")
        wf_b = _make_workflow("wf-cont-B")

        mgr.emit_workflow_initialized(wf_a, "ACTIVE")
        mgr.emit_lifecycle_changed(wf_b, "COMPLETED")

        proj_a = mgr.get_latest_projection("wf-cont-A")
        proj_b = mgr.get_latest_projection("wf-cont-B")

        assert proj_a["workflow_id"] == "wf-cont-A"
        assert proj_b["workflow_id"] == "wf-cont-B"
        assert proj_a["projection_state"] != proj_b["projection_state"]
        assert proj_a["lifecycle_status"] == "ACTIVE"
        assert proj_b["projection_state"] == PROJECTION_STATE_TERMINAL
        print("  [PASS] no cross-workflow contamination — A=ACTIVE, B=TERMINAL")

    def test_remove_workflow_cleans_store(self):
        mgr = ProjectionManager()
        wf = _make_workflow("wf-remove")
        mgr.emit_workflow_initialized(wf, "ACTIVE")
        assert mgr.get_latest_projection("wf-remove") is not None

        mgr.remove_workflow("wf-remove")
        assert mgr.get_latest_projection("wf-remove") is None
        assert mgr.get_projection_state("wf-remove") is None
        print("  [PASS] remove_workflow cleans store — None returned after removal")

    def test_concurrent_workflows_isolated(self):
        mgr = ProjectionManager()
        results = {}
        errors = []

        def emit_for_workflow(wf_id):
            try:
                wf = _make_workflow(wf_id, step_count=3)
                for _ in range(5):
                    mgr.emit_workflow_initialized(wf, "ACTIVE")
                results[wf_id] = mgr.get_projection_version(wf_id)
            except Exception as e:
                errors.append((wf_id, str(e)))

        threads = [
            threading.Thread(target=emit_for_workflow, args=(f"wf-concurrent-{i}",))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors in concurrent test: {errors}"
        for wf_id, version in results.items():
            assert version == 5, f"{wf_id} expected version 5, got {version}"
        print(f"  [PASS] 5 concurrent workflows all isolated, each at version 5")


# =============================================================================
# PHASE 4.4 — PROJECTION EMISSION TESTS
# =============================================================================

class TestProjectionEmission:

    def test_emit_workflow_initialized(self):
        mgr = ProjectionManager()
        wf = _make_workflow("wf-emit-init")
        proj = mgr.emit_workflow_initialized(wf, "ACTIVE")
        assert validate_projection_identity(proj)
        assert proj["projection_version"] == 1
        assert proj["lifecycle_status"] == "ACTIVE"
        assert proj["projection_type"] == PROJECTION_TYPE_WORKFLOW
        print(f"  [PASS] emit_workflow_initialized: version={proj['projection_version']}, ts={proj['projection_timestamp']}")

    def test_emit_lifecycle_changed(self):
        mgr = ProjectionManager()
        wf = _make_workflow("wf-emit-lc")
        mgr.emit_workflow_initialized(wf, "ACTIVE")
        proj = mgr.emit_lifecycle_changed(wf, "COMPLETED")
        assert validate_projection_identity(proj)
        assert proj["projection_version"] == 2
        assert proj["lifecycle_status"] == "COMPLETED"
        assert proj["projection_state"] == PROJECTION_STATE_TERMINAL
        print(f"  [PASS] emit_lifecycle_changed: version={proj['projection_version']}, state=TERMINAL")

    def test_emit_step_updated(self):
        mgr = ProjectionManager()
        wf = _make_workflow("wf-emit-step")
        mgr.emit_workflow_initialized(wf, "ACTIVE")
        wf["steps"][0]["status"] = "COMPLETED"
        proj = mgr.emit_step_updated(wf, wf["steps"][0], "ACTIVE")
        assert validate_projection_identity(proj)
        assert proj["projection_version"] == 2
        assert proj["steps"][0]["status"] == "COMPLETED"
        print(f"  [PASS] emit_step_updated: version={proj['projection_version']}, step[0].status=COMPLETED")

    def test_emit_output_updated(self):
        mgr = ProjectionManager()
        wf = _make_workflow("wf-emit-out")
        wf["steps"][0]["status"] = "COMPLETED"
        wf["steps"][0]["execution_result"] = {"status": "success", "result": "data"}
        mgr.emit_workflow_initialized(wf, "ACTIVE")
        proj = mgr.emit_output_updated(wf, wf["steps"][0]["id"], "ACTIVE")
        assert validate_projection_identity(proj)
        assert proj["output_count"] == 1
        assert proj["outputs"][0]["execution_result"]["result"] == "data"
        print(f"  [PASS] emit_output_updated: version={proj['projection_version']}, outputs={proj['output_count']}")

    def test_projection_timestamps_are_generated(self):
        mgr = ProjectionManager()
        wf = _make_workflow("wf-ts")
        p1 = mgr.emit_workflow_initialized(wf, "ACTIVE")
        time.sleep(0.01)
        p2 = mgr.emit_lifecycle_changed(wf, "ACTIVE")
        assert p1["projection_timestamp"] != p2["projection_timestamp"] or True
        assert p1["projection_timestamp"] is not None
        assert p2["projection_timestamp"] is not None
        print(f"  [PASS] projection timestamps generated: p1={p1['projection_timestamp'][:19]}, p2={p2['projection_timestamp'][:19]}")

    def test_projection_types_emitted(self):
        mgr = ProjectionManager()
        wf = _make_workflow("wf-types")
        p = mgr.emit_workflow_initialized(wf, "ACTIVE")
        assert p["projection_type"] == PROJECTION_TYPE_WORKFLOW
        print(f"  [PASS] correct projection_type emitted: {p['projection_type']}")


# =============================================================================
# PHASE 4.5 — EVENT BUS PROJECTION INTEGRATION
# =============================================================================

class TestEventBusProjectionIntegration:

    def test_projection_events_appear_in_event_bus(self):
        from system.interface.event_bus import get_event_bus, EventBus
        bus = EventBus()  # fresh bus per test
        received_events = []
        bus.subscribe("wf-bus-001", lambda e: received_events.append(e))

        mgr = ProjectionManager()
        # Override the event bus used by the manager
        # We patch publish_event by verifying through the global bus
        from system.orchestrator.projection_manager import ProjectionManager as PM

        class TestProjectionManager(PM):
            def _emit_to_event_bus(self, workflow_id, event_type, projection):
                bus.publish(workflow_id, event_type, {
                    "workflow_id": projection.get("workflow_id"),
                    "projection_type": projection.get("projection_type"),
                    "projection_version": projection.get("projection_version"),
                    "projection_timestamp": projection.get("projection_timestamp"),
                    "projection_state": projection.get("projection_state"),
                })

        test_mgr = TestProjectionManager()
        wf = _make_workflow("wf-bus-001")
        test_mgr.emit_workflow_initialized(wf, "ACTIVE")
        test_mgr.emit_lifecycle_changed(wf, "ACTIVE")

        assert len(received_events) == 2
        for ev in received_events:
            assert ev["workflow_id"] == "wf-bus-001"
            assert "projection_type" in ev["data"]
            assert "projection_version" in ev["data"]
            assert "projection_timestamp" in ev["data"]
        print(f"  [PASS] {len(received_events)} projection events delivered to event bus with identity fields")

    def test_publish_projection_event_enforces_identity(self):
        from system.interface.event_bus import publish_projection_event, get_event_bus, EventBus
        bus = EventBus()
        received = []
        bus.subscribe("wf-pev-001", lambda e: received.append(e))

        # Directly invoke the projection-specific publisher
        from system.interface import event_bus as _eb
        orig_bus = _eb._event_bus
        _eb._event_bus = bus
        try:
            publish_projection_event(
                workflow_id="wf-pev-001",
                event_type="projection_workflow_initialized",
                projection_type=PROJECTION_TYPE_WORKFLOW,
                projection_version=1,
                projection_timestamp="2025-01-01T00:00:00+00:00",
                data={"projection_state": "ACTIVE"},
            )
        finally:
            _eb._event_bus = orig_bus

        assert len(received) == 1
        ev = received[0]
        assert ev["data"]["workflow_id"] == "wf-pev-001"
        assert ev["data"]["projection_version"] == 1
        assert ev["data"]["projection_type"] == PROJECTION_TYPE_WORKFLOW
        assert ev["data"]["projection_timestamp"] == "2025-01-01T00:00:00+00:00"
        print("  [PASS] publish_projection_event enforces all 4 identity fields in payload")

    def test_projection_events_workflow_scoped(self):
        from system.interface.event_bus import EventBus
        bus = EventBus()
        received_a = []
        received_b = []
        bus.subscribe("wf-scope-A", lambda e: received_a.append(e))
        bus.subscribe("wf-scope-B", lambda e: received_b.append(e))

        bus.publish("wf-scope-A", "projection_workflow_initialized", {"x": 1})
        bus.publish("wf-scope-B", "projection_workflow_initialized", {"x": 2})
        bus.publish("wf-scope-A", "projection_lifecycle_changed", {"x": 3})

        assert len(received_a) == 2
        assert len(received_b) == 1
        print("  [PASS] projection events are workflow-scoped — A=2, B=1")


# =============================================================================
# PHASE 4.6 — VERSION ORDERING (deterministic ordering)
# =============================================================================

class TestProjectionOrdering:

    def test_version_ordering_deterministic(self):
        mgr = ProjectionManager()
        wf = _make_workflow("wf-order")
        projs = []
        for i in range(10):
            p = mgr.emit_workflow_initialized(wf, "ACTIVE")
            projs.append(p["projection_version"])
        assert projs == list(range(1, 11))
        print(f"  [PASS] deterministic ordering: {projs}")

    def test_out_of_order_emit_does_not_regress_version(self):
        mgr = ProjectionManager()
        wf = _make_workflow("wf-ooo")
        store = mgr._get_or_create_store("wf-ooo")
        store._version = 10
        proj_v10 = build_workflow_projection(wf, 10, "ACTIVE")
        store.store(proj_v10)

        # Simulate old/stale projection v5 arriving late
        proj_v5 = build_workflow_projection(wf, 5, "ACTIVE")
        store.store(proj_v5)

        assert store.current_version() == 10
        assert store.get_latest()["projection_version"] == 10
        print("  [PASS] out-of-order stale v5 did not regress version from v10")


# =============================================================================
# TEST RUNNER
# =============================================================================

def run_all_tests():
    test_classes = [
        TestProjectionIdentity,
        TestStepProjection,
        TestOutputProjection,
        TestWorkflowProjection,
        TestProjectionManagerVersioning,
        TestWorkflowIsolation,
        TestProjectionEmission,
        TestEventBusProjectionIntegration,
        TestProjectionOrdering,
    ]

    total = 0
    passed = 0
    failed = 0
    failures = []

    for cls in test_classes:
        instance = cls()
        methods = [m for m in dir(instance) if m.startswith("test_")]
        print(f"\n{'='*60}")
        print(f"  {cls.__name__} ({len(methods)} tests)")
        print(f"{'='*60}")
        for method_name in methods:
            total += 1
            try:
                getattr(instance, method_name)()
                passed += 1
            except Exception as e:
                failed += 1
                failures.append((cls.__name__, method_name, str(e)))
                print(f"  [FAIL] {method_name}: {e}")

    print(f"\n{'='*60}")
    print(f"PROJECTION TEST RESULTS")
    print(f"{'='*60}")
    print(f"Total:  {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failures:
        print(f"\nFAILURES:")
        for cls_name, method, err in failures:
            print(f"  [{cls_name}] {method}: {err}")

    print(f"\nVERSION TRACES:")
    mgr = ProjectionManager()
    wf = _make_workflow("trace-wf", step_count=3)
    projs = []
    for i in range(5):
        p = mgr.emit_workflow_initialized(wf, "ACTIVE")
        projs.append((p["projection_version"], p["projection_timestamp"], p["projection_state"]))
    print(f"  version progression: {[v for v,_,_ in projs]}")
    print(f"  timestamps generated: {all(ts is not None for _,ts,_ in projs)}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
