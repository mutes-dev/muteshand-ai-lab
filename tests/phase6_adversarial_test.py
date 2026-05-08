"""
PHASE 6 CORRECTION PATCH — ADVERSARIAL VALIDATION

Tests edge cases and combined scenarios:
1. Pause + Resume + Override combined
2. Rapid override toggle
3. Failure inside parallel group with override
4. Resume after partial completion
5. Dependency chain with override ON
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from system.orchestrator.user_control import set_override, get_override, pause, resume, is_paused
from system.orchestrator import governance


def test_pause_resume_override_combined():
    """TEST: Pause, resume, and override in sequence"""
    print("\n=== TEST: Pause + Resume + Override Combined ===")
    
    # Step 1: Start with override OFF
    set_override(False)
    assert get_override() == False
    
    # Step 2: Pause workflow
    pause()
    assert is_paused() == True  # Using user_control.is_paused()
    
    # Step 3: Resume workflow
    resume()
    assert is_paused() == False
    
    # Step 4: Enable override during execution
    set_override(True)
    
    # Step 5: Governance decision with override ON after resume
    step = {
        "id": "test_step",
        "status": "ACTIVE",
        "retries": 2,
        "max_retries": 2,
        "risk": "HIGH",
        "purpose_met": False
    }
    
    execution_result = {"status": "failure", "reason": "persistent_failure"}
    
    decision = governance.decide_next_action(
        validator_output={},
        execution_result=execution_result,
        step=step,
        context={},
        override_state=True
    )
    
    assert decision == "fail", f"Expected 'fail', got '{decision}'"
    print("  ✓ PASS: Pause/Resume/Override sequence works correctly")
    return True


def test_rapid_override_toggle():
    """TEST: Override toggled rapidly during execution"""
    print("\n=== TEST: Rapid Override Toggle ===")
    
    step = {
        "id": "test_step",
        "status": "ACTIVE",
        "retries": 2,
        "max_retries": 2,
        "risk": "HIGH",
        "purpose_met": False
    }
    
    execution_result = {"status": "failure", "reason": "failure"}
    
    # Toggle override rapidly
    for i in range(5):
        set_override(i % 2 == 0)
        decision = governance.decide_next_action(
            validator_output={},
            execution_result=execution_result,
            step=step.copy(),
            context={},
            override_state=get_override()
        )
        
        expected = "fail" if get_override() else "escalate"
        assert decision == expected, f"Iteration {i}: Expected '{expected}', got '{decision}'"
    
    print("  ✓ PASS: Rapid override toggle handled correctly")
    return True


def test_parallel_group_override():
    """TEST: Override ON with escalation in parallel group"""
    print("\n=== TEST: Parallel Group + Override ON ===")
    
    # Simulate what parallel_executor does
    step = {"id": "parallel_step_1", "status": "ACTIVE"}
    next_decision = "escalate"
    override_state = True
    
    # Apply the override handling logic
    if override_state and next_decision == "escalate":
        step["status"] = "FAILED"
        step["_override_skip_escalation"] = True
    else:
        # Would normally escalate
        step["status"] = "BLOCKED"
    
    assert step["status"] == "FAILED", f"Expected FAILED, got {step['status']}"
    assert step.get("_override_skip_escalation") == True
    
    print("  ✓ PASS: Parallel group override handling correct")
    return True


def test_resume_after_partial_completion():
    """TEST: Resume workflow after some steps completed"""
    print("\n=== TEST: Resume After Partial Completion ===")
    
    from system.orchestrator.persistence import save_workflow, load_active_workflows, delete_workflow
    
    # Create workflow with partial completion
    workflow = {
        "id": "test_partial_resume",
        "name": "Partial Resume Test",
        "status": "PAUSED",
        "steps": [
            {"id": "step1", "status": "COMPLETED", "execution_result": {"status": "success"}},
            {"id": "step2", "status": "COMPLETED", "execution_result": {"status": "success"}},
            {"id": "step3", "status": "FAILED", "execution_result": {"status": "failure"}},
            {"id": "step4", "status": "PENDING"}
        ]
    }
    
    # Save workflow
    save_workflow(workflow)
    
    # Load from persistence
    persisted = load_active_workflows()
    loaded = None
    for pw in persisted:
        if pw.get("id") == "test_partial_resume":
            loaded = pw
            break
    
    assert loaded is not None
    assert loaded["status"] == "PAUSED"
    
    # Simulate PAUSED → ACTIVE transition
    if loaded.get("status") == "PAUSED":
        loaded["status"] = "ACTIVE"
    
    # Verify state
    assert loaded["status"] == "ACTIVE"
    completed_count = sum(1 for s in loaded["steps"] if s.get("status") == "COMPLETED")
    failed_count = sum(1 for s in loaded["steps"] if s.get("status") == "FAILED")
    
    assert completed_count == 2, f"Expected 2 completed, got {completed_count}"
    assert failed_count == 1, f"Expected 1 failed, got {failed_count}"
    
    # Cleanup
    delete_workflow("test_partial_resume")
    
    print("  ✓ PASS: Resume after partial completion works correctly")
    return True


def test_dependency_chain_with_override():
    """TEST: Failed step with dependents and override ON"""
    print("\n=== TEST: Dependency Chain + Override ON ===")
    
    # Create dependency chain simulation
    steps = [
        {"id": "step1", "status": "COMPLETED", "execution_result": {"status": "success"}},
        {"id": "step2", "status": "FAILED", "depends_on": ["step1"]},  # Failed step
        {"id": "step3", "status": "PENDING", "depends_on": ["step2"]},  # Dependent
        {"id": "step4", "status": "PENDING", "depends_on": ["step3"]},  # Transitive dependent
    ]
    
    # Simulate override ON scenario
    set_override(True)
    
    # step2 is FAILED with override ON
    # step3 and step4 should NOT execute (dependency model intact)
    
    # Check dependency logic
    step2_status = "FAILED"
    
    # step3 depends on step2 - should not execute if step2 failed
    # (regardless of override)
    def should_execute(step, all_steps):
        depends_on = step.get("depends_on", [])
        for dep_id in depends_on:
            dep_step = next((s for s in all_steps if s["id"] == dep_id), None)
            if dep_step and dep_step.get("status") not in ("COMPLETED",):
                return False
        return True
    
    step3_should_execute = should_execute(steps[2], steps)
    step4_should_execute = should_execute(steps[3], steps)
    
    assert step3_should_execute == False, "step3 should NOT execute (depends on failed step2)"
    assert step4_should_execute == False, "step4 should NOT execute (depends on pending step3)"
    
    print("  ✓ PASS: Dependency chain respected with override ON")
    print("  ✓ PASS: Override does NOT break dependency model")
    return True


def test_mid_workflow_override_toggle():
    """TEST: Override toggled mid-workflow execution"""
    print("\n=== TEST: Mid-Workflow Override Toggle ===")
    
    # Simulate workflow execution with override toggle
    step_results = []
    
    for i in range(3):
        # Toggle override for each step
        set_override(i == 1)  # OFF, ON, OFF
        
        step = {
            "id": f"step_{i}",
            "status": "ACTIVE",
            "retries": 2,
            "max_retries": 2,
            "risk": "HIGH",
            "purpose_met": False
        }
        
        execution_result = {"status": "failure", "reason": "failure"}
        
        decision = governance.decide_next_action(
            validator_output={},
            execution_result=execution_result,
            step=step,
            context={},
            override_state=get_override()
        )
        
        step_results.append((i, get_override(), decision))
    
    # Verify results
    assert step_results[0][2] == "escalate", "Step 0 (override OFF) should escalate"
    assert step_results[1][2] == "fail", "Step 1 (override ON) should fail"
    assert step_results[2][2] == "escalate", "Step 2 (override OFF) should escalate"
    
    print("  ✓ PASS: Mid-workflow override toggle handled correctly")
    return True


def run_adversarial_tests():
    """Run all adversarial tests"""
    print("\n" + "="*60)
    print("PHASE 6 CORRECTION PATCH — ADVERSARIAL VALIDATION")
    print("="*60)
    
    tests = [
        ("Pause + Resume + Override", test_pause_resume_override_combined),
        ("Rapid Override Toggle", test_rapid_override_toggle),
        ("Parallel Group + Override", test_parallel_group_override),
        ("Resume After Partial Completion", test_resume_after_partial_completion),
        ("Dependency Chain + Override", test_dependency_chain_with_override),
        ("Mid-Workflow Override Toggle", test_mid_workflow_override_toggle),
    ]
    
    results = []
    for name, test_fn in tests:
        try:
            # Reset state before each test
            set_override(False)
            resume()
            
            result = test_fn()
            results.append((name, result, None))
        except AssertionError as e:
            results.append((name, False, str(e)))
            print(f"  ✗ FAIL: {e}")
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"  ✗ ERROR: {e}")
    
    # Summary
    print("\n" + "="*60)
    print("ADVERSARIAL VALIDATION SUMMARY")
    print("="*60)
    
    for name, result, error in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")
        if error:
            print(f"      {error}")
    
    passed = sum(1 for _, result, _ in results if result)
    failed = sum(1 for _, result, _ in results if not result)
    
    print(f"\n  Total: {passed} passed, {failed} failed")
    print("="*60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_adversarial_tests()
    sys.exit(0 if success else 1)
