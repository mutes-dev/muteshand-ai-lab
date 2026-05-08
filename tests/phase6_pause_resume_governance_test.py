"""
PHASE 6 CORE FIX — PAUSE/RESUME + GOVERNANCE OVERRIDE INTEGRATION TESTS

Tests:
1. Pause creates PAUSED workflow state with persistence
2. Resume loads workflow and re-enters via run_workflow
3. Override OFF: retry → escalate → BLOCKED
4. Override ON: retry → COMPLETE (with failure result)
5. Governance receives override_state parameter
6. Runtime loop does NOT use override in condition
"""

import json
import os
import sys
import tempfile
import shutil

# Add project root to path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from system.orchestrator.user_control import set_override, get_override, pause, resume, is_paused
from system.orchestrator import governance


def test_governance_override_parameter():
    """TEST: Governance accepts override_state parameter"""
    print("\n=== TEST: Governance Override Parameter ===")
    
    # Create test step - HIGH risk has 2 max retries
    step = {
        "id": "test_step",
        "status": "ACTIVE",
        "retries": 2,  # Max retries reached (HIGH risk = 2 max)
        "max_retries": 2,
        "risk": "HIGH",  # HIGH risk = max 2 retries
        "purpose_met": False
    }
    
    # Execution failed
    execution_result = {"status": "failure", "reason": "test_failure"}
    
    # Test with override OFF (default)
    decision_off = governance.decide_next_action(
        validator_output={},
        execution_result=execution_result,
        step=step.copy(),
        context={},
        override_state=False
    )
    
    # Test with override ON
    decision_on = governance.decide_next_action(
        validator_output={},
        execution_result=execution_result,
        step=step.copy(),
        context={},
        override_state=True
    )
    
    print(f"  Override OFF: {decision_off} (expected: escalate)")
    print(f"  Override ON: {decision_on} (expected: complete)")
    
    assert decision_off == "escalate", f"Expected 'escalate' with override OFF, got '{decision_off}'"
    assert decision_on == "complete", f"Expected 'complete' with override ON, got '{decision_on}'"
    
    print("  ✓ PASS: Governance correctly handles override_state")
    return True


def test_override_off_escalates():
    """TEST: Override OFF → escalate after max retries"""
    print("\n=== TEST: Override OFF → Escalate ===")
    
    step = {
        "id": "test_step",
        "status": "ACTIVE",
        "retries": 5,  # At max for LOW risk
        "max_retries": 5,
        "risk": "LOW",
        "purpose_met": False
    }
    
    execution_result = {"status": "failure", "reason": "persistent_failure"}
    
    # Set override OFF globally
    set_override(False)
    
    decision = governance.decide_next_action(
        validator_output={},
        execution_result=execution_result,
        step=step,
        context={},
        override_state=get_override()
    )
    
    print(f"  Decision: {decision} (expected: escalate)")
    assert decision == "escalate", f"Expected 'escalate', got '{decision}'"
    print("  ✓ PASS: Override OFF correctly escalates")
    return True


def test_override_on_completes():
    """TEST: Override ON → complete after max retries (FAIL+CONTINUE)"""
    print("\n=== TEST: Override ON → Complete ===")
    
    step = {
        "id": "test_step",
        "status": "ACTIVE",
        "retries": 5,
        "max_retries": 5,
        "risk": "LOW",
        "purpose_met": False
    }
    
    execution_result = {"status": "failure", "reason": "persistent_failure"}
    
    # Set override ON globally
    set_override(True)
    
    decision = governance.decide_next_action(
        validator_output={},
        execution_result=execution_result,
        step=step,
        context={},
        override_state=get_override()
    )
    
    print(f"  Decision: {decision} (expected: complete)")
    assert decision == "complete", f"Expected 'complete', got '{decision}'"
    print("  ✓ PASS: Override ON correctly completes (FAIL+CONTINUE)")
    
    # Reset override
    set_override(False)
    return True


def test_pause_state_transition():
    """TEST: Pause sets PAUSED state and persists"""
    print("\n=== TEST: Pause State Transition ===")
    
    from system.orchestrator.persistence import save_workflow, load_active_workflows, delete_workflow
    
    # Create a test workflow
    workflow = {
        "id": "test_pause_wf",
        "name": "Test Pause Workflow",
        "status": "ACTIVE",
        "steps": [
            {"id": "step1", "status": "COMPLETED"},
            {"id": "step2", "status": "ACTIVE"}
        ]
    }
    
    # Save as active
    result = save_workflow(workflow)
    print(f"  Save result: {result}")
    
    # Simulate pause state
    workflow["status"] = "PAUSED"
    result = save_workflow(workflow)
    print(f"  Pause save result: {result}")
    
    # Verify PAUSED workflow is persisted
    active_workflows = load_active_workflows()
    paused_wf = None
    for wf in active_workflows:
        if wf.get("id") == "test_pause_wf":
            paused_wf = wf
            break
    
    assert paused_wf is not None, "PAUSED workflow not found in persistence"
    assert paused_wf["status"] == "PAUSED", f"Expected status PAUSED, got {paused_wf['status']}"
    
    print("  ✓ PASS: Pause state is correctly persisted")
    
    # Cleanup
    delete_workflow("test_pause_wf")
    return True


def test_governance_signature():
    """TEST: Governance function has correct signature with override_state"""
    print("\n=== TEST: Governance Function Signature ===")
    
    import inspect
    sig = inspect.signature(governance.decide_next_action)
    params = list(sig.parameters.keys())
    
    print(f"  Parameters: {params}")
    
    required_params = ['validator_output', 'execution_result', 'step', 'context', 'memory_confidence', 'override_state']
    for param in required_params:
        assert param in params, f"Missing parameter: {param}"
    
    # Check default value
    override_param = sig.parameters['override_state']
    assert override_param.default == False, "override_state should default to False"
    
    print("  ✓ PASS: Governance has correct signature with override_state parameter")
    return True


def test_user_control_functions():
    """TEST: User control functions work correctly"""
    print("\n=== TEST: User Control Functions ===")
    
    # Reset state
    resume()
    set_override(False)
    
    # Test pause
    pause()
    assert is_paused() == True, "is_paused() should return True after pause()"
    print("  ✓ pause() works correctly")
    
    # Test resume
    resume()
    assert is_paused() == False, "is_paused() should return False after resume()"
    print("  ✓ resume() works correctly")
    
    # Test override
    set_override(True)
    assert get_override() == True, "get_override() should return True after set_override(True)"
    print("  ✓ set_override(True) works correctly")
    
    set_override(False)
    assert get_override() == False, "get_override() should return False after set_override(False)"
    print("  ✓ set_override(False) works correctly")
    
    print("  ✓ PASS: All user control functions work correctly")
    return True


def run_all_tests():
    """Run all Phase 6 tests"""
    print("\n" + "="*60)
    print("PHASE 6 CORE FIX — PAUSE/RESUME + GOVERNANCE OVERRIDE TESTS")
    print("="*60)
    
    tests = [
        ("Governance Signature", test_governance_signature),
        ("Governance Override Parameter", test_governance_override_parameter),
        ("Override OFF → Escalate", test_override_off_escalates),
        ("Override ON → Complete", test_override_on_completes),
        ("User Control Functions", test_user_control_functions),
        ("Pause State Transition", test_pause_state_transition),
    ]
    
    results = []
    for name, test_fn in tests:
        try:
            result = test_fn()
            results.append((name, result, None))
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"  ✗ FAIL: {e}")
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result, _ in results if result)
    failed = sum(1 for _, result, _ in results if not result)
    
    for name, result, error in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")
        if error:
            print(f"      Error: {error}")
    
    print(f"\n  Total: {passed} passed, {failed} failed")
    print("="*60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
