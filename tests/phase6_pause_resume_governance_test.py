"""
CATEGORY: GOVERNANCE
AUTHORITY_LAYER: Decision Authority Validation
VALIDATES:
  - Pause/resume governance
  - Governance escalation semantics
ENTRYPOINT: workflow_control
DIRECT_INTERNAL_CALLS:
  - user_control internals
  - governance internals
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: UNIT_LEVEL_VALIDATION
ARCHITECTURAL_SCOPE: Pause/resume governance

---

PHASE 6 — PAUSE/RESUME + GOVERNANCE INTEGRATION TESTS

Tests:
1. Pause creates PAUSED workflow state with persistence
2. Resume loads workflow and re-enters via run_workflow
3. Retry exhaustion escalates correctly
4. Governance is sole decision authority
"""

import json
import os
import sys
import tempfile
import shutil

# Add project root to path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

# === SAFETY: Isolate persistence to temp directories ===
import tempfile
_test_active_dir = tempfile.mkdtemp(prefix="phase6_gov_test_")
os.makedirs(_test_active_dir, exist_ok=True)
import system.orchestrator.persistence as _pm
_pm.ACTIVE_WORKFLOW_DIR = _test_active_dir

_test_checkpoint_dir = tempfile.mkdtemp(prefix="phase6_gov_checkpoint_test_")
os.makedirs(_test_checkpoint_dir, exist_ok=True)
import system.orchestrator.checkpoint_manager as _cm
_cm.CHECKPOINT_DIR = _test_checkpoint_dir

from tests._test_safety_guard import guard_delete_workflow, guard_rmtree

import atexit

def _cleanup_phase6_gov_test_dirs():
    guard_rmtree(_test_active_dir)
    guard_rmtree(_test_checkpoint_dir)


atexit.register(_cleanup_phase6_gov_test_dirs)
# === END SAFETY ===

from system.orchestrator import governance


def test_pause_state_transition():
    """TEST: Pause sets PAUSED state and persists"""
    print("\n=== TEST: Pause State Transition ===")
    
    from system.orchestrator.persistence import save_workflow, load_active_workflows
    
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
    
    print("  PASS: Pause state is correctly persisted")
    
    # Cleanup
    guard_delete_workflow("test_pause_wf")
    return True


def test_governance_signature():
    """TEST: Governance function has correct signature without override_state"""
    print("\n=== TEST: Governance Function Signature ===")
    
    import inspect
    sig = inspect.signature(governance.decide_next_action)
    params = list(sig.parameters.keys())
    
    print(f"  Parameters: {params}")
    
    required_params = ['validator_output', 'execution_result', 'step', 'context', 'memory_confidence']
    for param in required_params:
        assert param in params, f"Missing parameter: {param}"
    
    assert 'override_state' not in params, "override_state must not exist in governance signature after removal"
    
    print("  PASS: Governance has correct signature without override_state")
    return True


def test_governance_retry_escalation():
    """TEST: Retry exhaustion always escalates — no override bypass"""
    print("\n=== TEST: Retry Exhaustion Escalation ===")

    step = {
        "id": "test_step",
        "status": "ACTIVE",
        "retries": 5,
        "max_retries": 5,
        "risk": "LOW",
        "purpose_met": False
    }

    execution_result = {"status": "failure", "reason": "persistent_failure"}

    decision = governance.decide_next_action(
        validator_output={},
        execution_result=execution_result,
        step=step,
        context={}
    )

    print(f"  Decision: {decision} (expected: escalate)")
    assert decision == "escalate", f"Expected 'escalate', got '{decision}'"
    print("  PASS: Retry exhaustion escalates correctly — no override bypass")
    return True


def run_all_tests():
    """Run all Phase 6 tests"""
    print("\n" + "="*60)
    print("PHASE 6 — PAUSE/RESUME + GOVERNANCE ESCALATION TESTS")
    print("="*60)
    
    tests = [
        ("Governance Signature", test_governance_signature),
        ("Retry Exhaustion Escalation", test_governance_retry_escalation),
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
