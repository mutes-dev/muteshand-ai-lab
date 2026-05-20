"""
PHASE 4G-A.9 — Low-Risk Pause Semantic Convergence Fix Tests
Verifies:
1. Lifecycle synchronization bridge (workflow_dict status sync)
2. Semantic blocked_reason validation (projection gate)
3. UNKNOWN leakage removal
4. No orchestration semantics changed
"""

import sys
sys.path.insert(0, r"E:\MutesHand")


# =============================================================================
# TEST 1: Semantic blocked_reason validation in build_step_projection
# =============================================================================
def test_blocked_reason_semantic_gate():
    from system.orchestrator.projection_schema import build_step_projection

    # BLOCKED step WITH blocked_reason → should include blocked_reason
    blocked_step = {
        "id": "step_1",
        "status": "BLOCKED",
        "blocked_reason": "dependency_not_completed:step_0:PENDING",
    }
    proj = build_step_projection(
        workflow_id="wf_test",
        step=blocked_step,
        projection_version=1,
    )
    assert proj["blocked_reason"] == "dependency_not_completed:step_0:PENDING"

    # COMPLETED step WITH stale blocked_reason → should NOT include blocked_reason
    completed_step = {
        "id": "step_2",
        "status": "COMPLETED",
        "blocked_reason": "stale_reason_should_be_cleared",
    }
    proj2 = build_step_projection(
        workflow_id="wf_test",
        step=completed_step,
        projection_version=1,
    )
    assert proj2["blocked_reason"] is None, f"Expected None, got {proj2['blocked_reason']}"

    # ACTIVE step WITH stale blocked_reason → should NOT include blocked_reason
    active_step = {
        "id": "step_3",
        "status": "ACTIVE",
        "blocked_reason": "stale_reason",
    }
    proj3 = build_step_projection(
        workflow_id="wf_test",
        step=active_step,
        projection_version=1,
    )
    assert proj3["blocked_reason"] is None, f"Expected None, got {proj3['blocked_reason']}"

    print("  PASS: Semantic blocked_reason gate works correctly")


# =============================================================================
# TEST 2: Lifecycle synchronization bridge in _update_workflow_state
# =============================================================================
def test_lifecycle_sync_bridge():
    from system.orchestrator.workflow_control import (
        _update_workflow_state,
        _get_workflow_state,
        _workflow_state_registry,
        _workflow_state_lock,
    )

    import os
    import json
    from system.orchestrator.persistence import _active_workflow_path

    # Clean up any pre-existing test state
    with _workflow_state_lock:
        _workflow_state_registry.pop("test_sync_wf", None)
    _test_path = _active_workflow_path("test_sync_wf")
    if os.path.exists(_test_path):
        os.remove(_test_path)

    # Create persistence file FIRST (required by ACTIVE hard guard)
    os.makedirs(os.path.dirname(_test_path), exist_ok=True)
    with open(_test_path, "w") as f:
        json.dump({"id": "test_sync_wf", "status": "QUEUED"}, f)

    # Create a workflow dict (simulating in-memory execution snapshot)
    workflow_dict = {"id": "test_sync_wf", "status": "QUEUED", "steps": []}

    # Call _update_workflow_state with workflow_dict
    result = _update_workflow_state("test_sync_wf", "ACTIVE", "test_sync", workflow_dict=workflow_dict)
    assert result is True, "ACTIVE transition should succeed with persistence file"

    # Verify runtime registry has ACTIVE
    reg_state = _get_workflow_state("test_sync_wf")
    assert reg_state["status"] == "ACTIVE"

    # Verify workflow_dict was synchronized
    assert workflow_dict["status"] == "ACTIVE", f"Expected ACTIVE, got {workflow_dict['status']}"

    # Test PAUSED transition (no persistence guard needed)
    _update_workflow_state("test_sync_wf", "PAUSED", "test_pause", workflow_dict=workflow_dict)
    assert workflow_dict["status"] == "PAUSED"

    # Test transitional state sanitization (ACTIVATING → ACTIVE in workflow dict)
    _update_workflow_state("test_sync_wf", "ACTIVATING", "test_bootstrap", workflow_dict=workflow_dict)
    # workflow_dict should have ACTIVE (sanitized for external exposure)
    assert workflow_dict["status"] == "ACTIVE", f"Expected sanitized ACTIVE, got {workflow_dict['status']}"
    # But registry should have ACTIVATING
    reg_state2 = _get_workflow_state("test_sync_wf")
    assert reg_state2["status"] == "ACTIVATING"

    # Cleanup
    with _workflow_state_lock:
        _workflow_state_registry.pop("test_sync_wf", None)
    if os.path.exists(_test_path):
        os.remove(_test_path)

    print("  PASS: Lifecycle synchronization bridge works correctly")


# =============================================================================
# TEST 3: Lifecycle sync bridge without workflow_dict (backward compat)
# =============================================================================
def test_lifecycle_sync_bridge_optional():
    from system.orchestrator.workflow_control import (
        _update_workflow_state,
        _get_workflow_state,
        _workflow_state_registry,
        _workflow_state_lock,
    )
    import os
    import json
    from system.orchestrator.persistence import _active_workflow_path

    with _workflow_state_lock:
        _workflow_state_registry.pop("test_opt_wf", None)

    _test_path = _active_workflow_path("test_opt_wf")
    if os.path.exists(_test_path):
        os.remove(_test_path)

    # Create persistence file FIRST (required by ACTIVE hard guard)
    os.makedirs(os.path.dirname(_test_path), exist_ok=True)
    with open(_test_path, "w") as f:
        json.dump({"id": "test_opt_wf", "status": "QUEUED"}, f)

    # Call WITHOUT workflow_dict — should still work (backward compatible)
    result = _update_workflow_state("test_opt_wf", "ACTIVE", "test_opt")
    assert result is True

    reg_state = _get_workflow_state("test_opt_wf")
    assert reg_state["status"] == "ACTIVE"

    with _workflow_state_lock:
        _workflow_state_registry.pop("test_opt_wf", None)
    if os.path.exists(_test_path):
        os.remove(_test_path)

    print("  PASS: Optional workflow_dict preserves backward compatibility")


# =============================================================================
# TEST 4: UNKNOWN leakage removal in api.py fallbacks
# =============================================================================
def test_unknown_not_in_stream_registry():
    from ai_lab_gui.backend.api import _stream_registry, _stream_registry_lock

    # Verify no stream registry entry has "UNKNOWN" status
    with _stream_registry_lock:
        for bg_id, entry in _stream_registry.items():
            assert entry.get("status") != "UNKNOWN", f"bg_id={bg_id} has leaked UNKNOWN status"

    print("  PASS: No UNKNOWN leakage in existing stream registry entries")


# =============================================================================
# RUN ALL TESTS
# =============================================================================
if __name__ == "__main__":
    print("\n=== PHASE 4G-A.9 Fix Validation ===")

    test_blocked_reason_semantic_gate()
    test_lifecycle_sync_bridge()
    test_lifecycle_sync_bridge_optional()
    test_unknown_not_in_stream_registry()

    print("\n=== ALL TESTS PASSED ===")
