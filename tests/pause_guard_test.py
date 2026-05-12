"""
CATEGORY: GOVERNANCE
AUTHORITY_LAYER: Decision Authority Validation
VALIDATES:
  - Pause entry guard
  - Explicit resume behavior
  - PAUSED workflow stability
ENTRYPOINT: workflow_control
DIRECT_INTERNAL_CALLS:
  - user_control internals
  - orchestrator_runtime internals
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: UNIT_LEVEL_VALIDATION
ARCHITECTURAL_SCOPE: Pause guard governance

---

Test pause entry guard and explicit resume behavior.
Verifies PAUSED workflows do not auto-resume.
"""
import sys
import os

# Add project root to path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator.user_control import pause, resume


def test_pause_stability():
    """Test that paused workflow returns control state without execution."""
    workflow = {
        "id": "test_pause_workflow",
        "name": "Test Pause Workflow",
        "status": "PAUSED",
        "steps": [
            {
                "id": "step1",
                "name": "Step 1",
                "type": "EXECUTE_API",
                "agent": "test_agent",
                "input": "test input",
                "status": "PENDING"
            }
        ]
    }
    
    result = run_workflow(workflow)
    
    print(f"TEST 1 - Pause Stability:")
    print(f"  Result: {result}")
    print(f"  Expected: {{'status': 'control', 'action': 'paused'}}")
    print(f"  PASS: {result.get('status') == 'control' and result.get('action') == 'paused'}")
    print()
    
    return result.get('status') == 'control' and result.get('action') == 'paused'


def test_auto_resume_protection():
    """Test that run_workflow on paused workflow does not execute."""
    workflow = {
        "id": "test_auto_resume_protection",
        "name": "Test Auto Resume Protection",
        "status": "PAUSED",
        "steps": [
            {
                "id": "step1",
                "name": "Step 1",
                "type": "EXECUTE_API",
                "agent": "test_agent",
                "input": "test input",
                "status": "PENDING"
            }
        ]
    }
    
    # Simulate multiple entry points
    results = []
    for i in range(3):
        result = run_workflow(workflow)
        results.append(result)
    
    print(f"TEST 2 - Auto-Resume Protection:")
    print(f"  Results: {results}")
    print(f"  All returned control state: {all(r.get('status') == 'control' for r in results)}")
    print(f"  PASS: {all(r.get('status') == 'control' and r.get('action') == 'paused' for r in results)}")
    print()
    
    return all(r.get('status') == 'control' and r.get('action') == 'paused' for r in results)


def test_explicit_resume():
    """Test that explicit PAUSED → ACTIVE transition allows execution."""
    workflow = {
        "id": "test_explicit_resume",
        "name": "Test Explicit Resume",
        "status": "PAUSED",
        "steps": [
            {
                "id": "step1",
                "name": "Step 1",
                "type": "EXECUTE_API",
                "agent": "test_agent",
                "input": "test input",
                "status": "PENDING"
            }
        ]
    }
    
    # Explicitly transition to ACTIVE (simulating /resume endpoint)
    workflow["status"] = "ACTIVE"
    
    result = run_workflow(workflow)
    
    print(f"TEST 3 - Explicit Resume:")
    print(f"  Result status: {result.get('status')}")
    print(f"  Workflow status after: {workflow.get('status')}")
    print(f"  Did NOT return control state: {result.get('status') != 'control'}")
    print(f"  PASS: {result.get('status') != 'control'}")
    print()
    
    return result.get('status') != 'control'


if __name__ == "__main__":
    print("=" * 60)
    print("PAUSE GUARD TEST SUITE")
    print("=" * 60)
    print()
    
    test1_pass = test_pause_stability()
    test2_pass = test_auto_resume_protection()
    test3_pass = test_explicit_resume()
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Test 1 (Pause Stability): {'PASS' if test1_pass else 'FAIL'}")
    print(f"Test 2 (Auto-Resume Protection): {'PASS' if test2_pass else 'FAIL'}")
    print(f"Test 3 (Explicit Resume): {'PASS' if test3_pass else 'FAIL'}")
    print()
    print(f"OVERALL: {'ALL TESTS PASSED' if all([test1_pass, test2_pass, test3_pass]) else 'SOME TESTS FAILED'}")
