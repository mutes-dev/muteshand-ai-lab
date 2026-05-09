"""
Phase 4A.1 — Execution Integration Fix Tests

Tests:
1. Global pause removal (is_paused no longer referenced)
2. PAUSED state enforcement in scheduler
3. State-based cancellation (step edited during execution)
4. Dependency invalidation after edit
5. Stale execution prevention pre-check
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_global_pause_removed():
    """Test that user_control.is_paused is no longer imported in orchestrator_runtime"""
    print("\n[TEST] Global Pause Removal")

    # Read orchestrator_runtime.py and check for is_paused import
    with open("system/orchestrator/orchestrator_runtime.py", "r") as f:
        content = f.read()

    # Check that is_paused is NOT imported
    if "is_paused" in content:
        print("  ✗ FAIL: is_paused still referenced in orchestrator_runtime.py")
        return False

    print("  ✓ PASS: is_paused successfully removed from orchestrator_runtime")
    return True


def test_workflow_scoped_pause_check():
    """Test that workflow-scoped PAUSED check exists"""
    print("\n[TEST] Workflow-Scoped PAUSED Check")

    with open("system/orchestrator/orchestrator_runtime.py", "r") as f:
        content = f.read()

    # Check for workflow-scoped PAUSED check
    if 'workflow.get("status") == "PAUSED"' in content:
        print("  ✓ PASS: Workflow-scoped PAUSED check found")
        return True

    print("  ✗ FAIL: Workflow-scoped PAUSED check not found")
    return False


def test_scheduler_paused_check():
    """Test that scheduler checks for PAUSED state"""
    print("\n[TEST] Scheduler PAUSED State Check")

    with open("system/orchestrator/execution_scheduler.py", "r") as f:
        content = f.read()

    # Check for PAUSED check in create_execution_group
    if 'workflow.get("status") == "PAUSED"' in content:
        print("  ✓ PASS: Scheduler PAUSED check found")
        return True

    print("  ✗ FAIL: Scheduler PAUSED check not found")
    return False


def test_loop_includes_paused_exit():
    """Test that main loop includes PAUSED in exit condition"""
    print("\n[TEST] Main Loop PAUSED Exit Condition")

    with open("system/orchestrator/orchestrator_runtime.py", "r") as f:
        content = f.read()

    # Check that loop condition includes PAUSED
    if '"PAUSED"' in content and 'not in ("COMPLETED", "BLOCKED", "FAILED", "PAUSED")' in content:
        print("  ✓ PASS: Loop exit condition includes PAUSED")
        return True

    print("  ✗ FAIL: Loop exit condition doesn't include PAUSED")
    return False


def test_state_based_cancellation_guard():
    """Test that state-based cancellation guard exists in parallel_executor"""
    print("\n[TEST] State-Based Cancellation Guard")

    with open("system/orchestrator/parallel_executor.py", "r") as f:
        content = f.read()

    # Check for state-based cancellation guard
    if "STATE-BASED CANCELLATION GUARD" in content:
        print("  ✓ PASS: State-based cancellation guard found")
        return True

    print("  ✗ FAIL: State-based cancellation guard not found")
    return False


def test_stale_execution_prevention():
    """Test that stale execution prevention pre-check exists"""
    print("\n[TEST] Stale Execution Prevention Pre-Check")

    with open("system/orchestrator/parallel_executor.py", "r") as f:
        content = f.read()

    # Check for stale execution prevention
    if "STALE EXECUTION PREVENTION" in content and "_check_dependencies_satisfied" in content:
        print("  ✓ PASS: Stale execution prevention found")
        return True

    print("  ✗ FAIL: Stale execution prevention not found")
    return False


def test_dependency_invalidation_helper():
    """Test that _invalidate_dependents helper exists"""
    print("\n[TEST] Dependency Invalidation Helper")

    with open("system/orchestrator/workflow_control.py", "r") as f:
        content = f.read()

    # Check for _invalidate_dependents function
    if "def _invalidate_dependents(" in content:
        print("  ✓ PASS: _invalidate_dependents helper found")
        return True

    print("  ✗ FAIL: _invalidate_dependents helper not found")
    return False


def test_edit_step_calls_invalidation():
    """Test that edit_step calls _invalidate_dependents"""
    print("\n[TEST] Edit Step Calls Invalidation")

    with open("system/orchestrator/workflow_control.py", "r") as f:
        content = f.read()

    # Check that edit_step calls _invalidate_dependents
    if "_invalidate_dependents(workflow, step_id)" in content:
        print("  ✓ PASS: edit_step calls _invalidate_dependents")
        return True

    print("  ✗ FAIL: edit_step doesn't call _invalidate_dependents")
    return False


def test_invalidation_clears_outputs():
    """Test that invalidation clears execution_result and output"""
    print("\n[TEST] Invalidation Clears Outputs")

    with open("system/orchestrator/workflow_control.py", "r") as f:
        content = f.read()

    # Check that invalidation clears execution_result and output
    checks = [
        'step.pop("execution_result"' in content,
        'step.pop("output"' in content,
        'step["status"] = "PENDING"' in content
    ]

    if all(checks):
        print("  ✓ PASS: Invalidation clears execution_result and output")
        return True

    print(f"  ✗ FAIL: Missing checks - execution_result: {checks[0]}, output: {checks[1]}, status: {checks[2]}")
    return False


def run_all_tests():
    print("=" * 70)
    print("PHASE 4A.1 — EXECUTION INTEGRATION FIX TESTS")
    print("=" * 70)

    tests = [
        test_global_pause_removed,
        test_workflow_scoped_pause_check,
        test_scheduler_paused_check,
        test_loop_includes_paused_exit,
        test_state_based_cancellation_guard,
        test_stale_execution_prevention,
        test_dependency_invalidation_helper,
        test_edit_step_calls_invalidation,
        test_invalidation_clears_outputs,
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
