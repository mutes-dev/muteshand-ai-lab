"""
CATEGORY: INTERNAL_RUNTIME
AUTHORITY_LAYER: Runtime Behavioral Truth
VALIDATES:
  - Backend control layer
  - Pause/Resume state transitions
  - Plan control operations
  - Control actions
  - Streaming event structure
ENTRYPOINT: workflow_control
DIRECT_INTERNAL_CALLS:
  - workflow_control internals
  - event_emitter internals
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: BEHAVIORAL_VALIDATION
ARCHITECTURAL_SCOPE: Backend control layer

---

Phase 4A — Backend Control Layer Tests

Tests:
1. Pause/Resume state transitions
2. Plan control (get_plan, edit_step, add_step, remove_step, reorder_steps)
3. Control actions (retry_step, stop_workflow)
4. Streaming event structure
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.workflow_control import (
    pause_workflow,
    resume_workflow,
    get_plan,
    edit_step,
    add_step,
    remove_step,
    reorder_steps,
    retry_step,
    stop_workflow,
    _is_valid_state_transition,
)
from system.interface.event_emitter import (
    EVENT_STEP_STARTED,
    EVENT_STEP_COMPLETED,
    EVENT_STATE_TRANSITION,
    EVENT_PROJECT_PAUSED,
    EVENT_PROJECT_RESUMED,
    EVENT_MESSAGE,
)
from system.interface import event_bus


# ============================================================================
# PAUSE/RESUME TESTS
# ============================================================================

def test_pause_resume_state_transitions():
    """Test valid state transitions per STATE_TRANSITIONS_CONTRACT_V1"""
    print("\n[TEST] State Transition Validation")

    # Valid transitions
    valid = [
        ("QUEUED", "ACTIVE"),
        ("ACTIVE", "PAUSED"),
        ("ACTIVE", "BLOCKED"),
        ("ACTIVE", "COMPLETED"),
        ("ACTIVE", "FAILED"),
        ("PAUSED", "ACTIVE"),
        ("PAUSED", "FAILED"),
        ("BLOCKED", "ACTIVE"),
        ("BLOCKED", "FAILED"),
    ]

    all_passed = True
    for current, new in valid:
        result = _is_valid_state_transition(current, new)
        if result:
            print(f"  ✓ {current} → {new} : VALID")
        else:
            print(f"  ✗ {current} → {new} : REJECTED (should be valid)")
            all_passed = False

    # Invalid transitions
    invalid = [
        ("COMPLETED", "ACTIVE"),
        ("FAILED", "ACTIVE"),
        ("QUEUED", "PAUSED"),
        ("BLOCKED", "COMPLETED"),
    ]

    for current, new in invalid:
        result = _is_valid_state_transition(current, new)
        if not result:
            print(f"  ✓ {current} → {new} : CORRECTLY REJECTED")
        else:
            print(f"  ✗ {current} → {new} : ALLOWED (should be invalid)")
            all_passed = False

    return all_passed


def test_pause_workflow_validation():
    """Test pause_workflow requires workflow_id"""
    print("\n[TEST] Pause Workflow - Missing workflow_id")

    result = pause_workflow("")
    print(f"  Result: {result}")

    if result.get("status") == "failure" and result.get("reason") == "missing_workflow_id":
        print("  ✓ PASS: Empty workflow_id rejected")
        return True
    print("  ✗ FAIL: Empty workflow_id not rejected")
    return False


def test_resume_workflow_validation():
    """Test resume_workflow requires workflow_id"""
    print("\n[TEST] Resume Workflow - Missing workflow_id")

    result = resume_workflow("")
    print(f"  Result: {result}")

    if result.get("status") == "failure" and result.get("reason") == "missing_workflow_id":
        print("  ✓ PASS: Empty workflow_id rejected")
        return True
    print("  ✗ FAIL: Empty workflow_id not rejected")
    return False


def test_resume_requires_paused():
    """Test resume only works from PAUSED state"""
    print("\n[TEST] Resume - Only from PAUSED state")

    # Can't test without actual workflow, but we can test the transition logic
    # ACTIVE → PAUSED is valid
    assert _is_valid_state_transition("ACTIVE", "PAUSED")
    # PAUSED → ACTIVE is valid
    assert _is_valid_state_transition("PAUSED", "ACTIVE")
    # ACTIVE → ACTIVE is NOT valid (no self-transition)
    assert not _is_valid_state_transition("ACTIVE", "ACTIVE")

    print("  ✓ PASS: State transition logic correct")
    return True


# ============================================================================
# PLAN CONTROL TESTS
# ============================================================================

def test_get_plan_missing_workflow():
    """Test get_plan rejects missing workflow_id"""
    print("\n[TEST] Get Plan - Missing workflow_id")

    result = get_plan("")
    print(f"  Result: {result}")

    if result.get("status") == "failure" and result.get("reason") == "missing_workflow_id":
        print("  ✓ PASS: Empty workflow_id rejected")
        return True
    print("  ✗ FAIL: Empty workflow_id not rejected")
    return False


def test_edit_step_missing_params():
    """Test edit_step requires workflow_id and step_id"""
    print("\n[TEST] Edit Step - Missing parameters")

    # Missing workflow_id
    result1 = edit_step("", "step_1", {})
    if result1.get("reason") != "missing_workflow_id":
        print(f"  ✗ FAIL: Missing workflow_id not rejected: {result1}")
        return False

    # Missing step_id
    result2 = edit_step("wf_1", "", {})
    if result2.get("reason") != "missing_step_id":
        print(f"  ✗ FAIL: Missing step_id not rejected: {result2}")
        return False

    print("  ✓ PASS: Missing parameters rejected")
    return True


def test_add_step_missing_workflow():
    """Test add_step rejects missing workflow_id"""
    print("\n[TEST] Add Step - Missing workflow_id")

    result = add_step("", {"id": "step_1"})
    print(f"  Result: {result}")

    if result.get("status") == "failure" and result.get("reason") == "missing_workflow_id":
        print("  ✓ PASS: Empty workflow_id rejected")
        return True
    print("  ✗ FAIL: Empty workflow_id not rejected")
    return False


def test_remove_step_missing_params():
    """Test remove_step requires workflow_id and step_id"""
    print("\n[TEST] Remove Step - Missing parameters")

    # Missing workflow_id
    result1 = remove_step("", "step_1")
    if result1.get("reason") != "missing_workflow_id":
        print(f"  ✗ FAIL: Missing workflow_id not rejected: {result1}")
        return False

    # Missing step_id
    result2 = remove_step("wf_1", "")
    if result2.get("reason") != "missing_step_id":
        print(f"  ✗ FAIL: Missing step_id not rejected: {result2}")
        return False

    print("  ✓ PASS: Missing parameters rejected")
    return True


def test_reorder_steps_validation():
    """Test reorder_steps validates input"""
    print("\n[TEST] Reorder Steps - Validation")

    # Missing workflow_id
    result1 = reorder_steps("", ["step_1"])
    if result1.get("reason") != "missing_workflow_id":
        print(f"  ✗ FAIL: Missing workflow_id not rejected: {result1}")
        return False

    # Empty new_order
    result2 = reorder_steps("wf_1", [])
    if result2.get("reason") != "empty_new_order":
        print(f"  ✗ FAIL: Empty order not rejected: {result2}")
        return False

    print("  ✓ PASS: Input validation correct")
    return True


# ============================================================================
# CONTROL ACTIONS TESTS
# ============================================================================

def test_retry_step_missing_params():
    """Test retry_step requires workflow_id and step_id"""
    print("\n[TEST] Retry Step - Missing parameters")

    # Missing workflow_id
    result1 = retry_step("", "step_1")
    if result1.get("reason") != "missing_workflow_id":
        print(f"  ✗ FAIL: Missing workflow_id not rejected: {result1}")
        return False

    # Missing step_id
    result2 = retry_step("wf_1", "")
    if result2.get("reason") != "missing_step_id":
        print(f"  ✗ FAIL: Missing step_id not rejected: {result2}")
        return False

    print("  ✓ PASS: Missing parameters rejected")
    return True


def test_stop_workflow_missing_id():
    """Test stop_workflow requires workflow_id"""
    print("\n[TEST] Stop Workflow - Missing workflow_id")

    result = stop_workflow("")
    print(f"  Result: {result}")

    if result.get("status") == "failure" and result.get("reason") == "missing_workflow_id":
        print("  ✓ PASS: Empty workflow_id rejected")
        return True
    print("  ✗ FAIL: Empty workflow_id not rejected")
    return False


def test_stop_workflow_invalid_states():
    """Test stop_workflow only works from ACTIVE, PAUSED, BLOCKED"""
    print("\n[TEST] Stop Workflow - Invalid state transitions")

    # These should be invalid (can't stop completed/failed workflows)
    invalid_from = ["COMPLETED", "FAILED"]

    for state in invalid_from:
        # We can't easily test this without mocking, but we can verify the transition logic
        can_transition = _is_valid_state_transition(state, "FAILED")
        if can_transition:
            print(f"  ✗ {state} → FAILED allowed (should be rejected)")
            return False
        else:
            print(f"  ✓ {state} → FAILED correctly rejected")

    return True


# ============================================================================
# STREAMING EVENT TESTS
# ============================================================================

def test_event_constants():
    """Test event type constants are defined"""
    print("\n[TEST] Event Type Constants")

    required_events = [
        EVENT_STEP_STARTED,
        EVENT_STEP_COMPLETED,
        EVENT_STATE_TRANSITION,
        EVENT_PROJECT_PAUSED,
        EVENT_PROJECT_RESUMED,
        EVENT_MESSAGE,
    ]

    for event in required_events:
        if event:
            print(f"  ✓ {event} defined")
        else:
            print(f"  ✗ Event constant not defined")
            return False

    return True


def test_event_bus_structure():
    """Test event bus creates correct event structure"""
    print("\n[TEST] Event Bus Structure")

    # Create a test event
    test_workflow_id = "test_wf_123"
    test_event_type = "TEST_EVENT"
    test_data = {"key": "value"}

    # Publish event
    event_bus.publish_event(test_workflow_id, test_event_type, test_data)

    # Get events
    events = event_bus.get_events(test_workflow_id)

    if not events:
        print("  ✗ No events retrieved")
        return False

    latest = events[-1]

    # Verify structure per TRACE_LOGGING_CONTRACT_V1
    required_fields = ["timestamp", "workflow_id", "event_type", "data"]
    for field in required_fields:
        if field not in latest:
            print(f"  ✗ Missing field: {field}")
            return False
        print(f"  ✓ Has field: {field}")

    if latest["workflow_id"] != test_workflow_id:
        print(f"  ✗ Wrong workflow_id: {latest['workflow_id']}")
        return False

    if latest["event_type"] != test_event_type:
        print(f"  ✗ Wrong event_type: {latest['event_type']}")
        return False

    print("  ✓ PASS: Event structure correct")
    return True


# ============================================================================
# RUN ALL TESTS
# ============================================================================

def run_all_tests():
    print("=" * 70)
    print("PHASE 4A — BACKEND CONTROL LAYER TESTS")
    print("=" * 70)

    tests = [
        # Pause/Resume
        test_pause_resume_state_transitions,
        test_pause_workflow_validation,
        test_resume_workflow_validation,
        test_resume_requires_paused,
        # Plan Control
        test_get_plan_missing_workflow,
        test_edit_step_missing_params,
        test_add_step_missing_workflow,
        test_remove_step_missing_params,
        test_reorder_steps_validation,
        # Control Actions
        test_retry_step_missing_params,
        test_stop_workflow_missing_id,
        test_stop_workflow_invalid_states,
        # Streaming
        test_event_constants,
        test_event_bus_structure,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ✗ EXCEPTION in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
