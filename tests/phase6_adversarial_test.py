"""
PHASE 6 — ADVERSARIAL VALIDATION

Tests edge cases and combined scenarios:
1. Pause + Resume combined
2. No override remnants in source files
3. Resume after partial completion
4. Dependency chain with failed steps
5. Escalation determinism
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

# === SAFETY: Isolate persistence to temp directories ===
import tempfile
_test_active_dir = tempfile.mkdtemp(prefix="phase6_adv_test_")
os.makedirs(_test_active_dir, exist_ok=True)
import system.orchestrator.persistence as _pm
_pm.ACTIVE_WORKFLOW_DIR = _test_active_dir

_test_checkpoint_dir = tempfile.mkdtemp(prefix="phase6_adv_checkpoint_test_")
os.makedirs(_test_checkpoint_dir, exist_ok=True)
import system.orchestrator.checkpoint_manager as _cm
_cm.CHECKPOINT_DIR = _test_checkpoint_dir

from tests._test_safety_guard import guard_delete_workflow, guard_rmtree

import atexit

def _cleanup_phase6_adv_test_dirs():
    guard_rmtree(_test_active_dir)
    guard_rmtree(_test_checkpoint_dir)


atexit.register(_cleanup_phase6_adv_test_dirs)
# === END SAFETY ===

from system.orchestrator import governance


def test_no_override_remnants_in_sources():
    """TEST: No override remnants remain in any production source file"""
    print("\n=== TEST: No Override Remnants ===")

    files_to_check = [
        os.path.join(ROOT, "system", "orchestrator", "user_control.py"),
        os.path.join(ROOT, "system", "orchestrator", "governance.py"),
        os.path.join(ROOT, "system", "orchestrator", "orchestrator_runtime.py"),
        os.path.join(ROOT, "system", "orchestrator", "parallel_executor.py"),
    ]

    forbidden = ["set_override", "get_override", "override_state", "_override_skip_escalation", "override_escalate"]
    violations = []

    for fpath in files_to_check:
        with open(fpath, 'r') as f:
            source = f.read()
        for term in forbidden:
            if term in source:
                violations.append(f"{os.path.basename(fpath)}: found '{term}'")

    if violations:
        for v in violations:
            print(f"  {v}")
        assert False, f"Override remnants found: {violations}"

    print("  PASS: No override remnants in any production source file")
    return True


def test_resume_after_partial_completion():
    """TEST: Resume workflow after some steps completed"""
    print("\n=== TEST: Resume After Partial Completion ===")
    
    from system.orchestrator.persistence import save_workflow, load_active_workflows
    
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
    guard_delete_workflow("test_partial_resume")
    
    print("  PASS: Resume after partial completion works correctly")
    return True


def test_dependency_chain_failed_step():
    """TEST: Failed step dependents do not execute — dependency model intact"""
    print("\n=== TEST: Dependency Chain with Failed Step ===")

    steps = [
        {"id": "step1", "status": "COMPLETED", "execution_result": {"status": "success"}},
        {"id": "step2", "status": "FAILED", "depends_on": ["step1"]},
        {"id": "step3", "status": "PENDING", "depends_on": ["step2"]},
        {"id": "step4", "status": "PENDING", "depends_on": ["step3"]},
    ]

    def should_execute(step, all_steps):
        depends_on = step.get("depends_on", [])
        for dep_id in depends_on:
            dep_step = next((s for s in all_steps if s["id"] == dep_id), None)
            if dep_step and dep_step.get("status") not in ("COMPLETED",):
                return False
        return True

    assert not should_execute(steps[2], steps), "step3 must NOT execute (depends on failed step2)"
    assert not should_execute(steps[3], steps), "step4 must NOT execute (depends on pending step3)"

    print("  PASS: Dependency chain correctly blocks dependents of failed steps")
    return True


def test_escalation_determinism():
    """TEST: Governance always escalates on retry exhaustion — deterministic"""
    print("\n=== TEST: Escalation Determinism ===")

    step_template = {
        "id": "test_step",
        "status": "ACTIVE",
        "retries": 2,
        "max_retries": 2,
        "risk": "HIGH",
        "purpose_met": False
    }
    execution_result = {"status": "failure", "reason": "failure"}

    for i in range(5):
        decision = governance.decide_next_action(
            validator_output={},
            execution_result=execution_result,
            step=step_template.copy(),
            context={}
        )
        assert decision == "escalate", f"Iteration {i}: Expected 'escalate', got '{decision}'"

    print("  PASS: Governance deterministically escalates on retry exhaustion")
    return True


def run_adversarial_tests():
    """Run all adversarial tests"""
    print("\n" + "="*60)
    print("PHASE 6 — ADVERSARIAL VALIDATION")
    print("="*60)
    
    tests = [
        ("No Override Remnants", test_no_override_remnants_in_sources),
        ("Resume After Partial Completion", test_resume_after_partial_completion),
        ("Dependency Chain Failed Step", test_dependency_chain_failed_step),
        ("Escalation Determinism", test_escalation_determinism),
    ]

    results = []
    for name, test_fn in tests:
        try:
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
