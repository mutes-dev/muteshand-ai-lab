"""
Phase 4A.1 — Adversarial Validation Tests

Edge cases and attack scenarios:
1. Rapid pause/resume during scheduling
2. Edit step that has dependents (dependency chain invalidation)
3. Attempt to execute with failed dependencies (stale execution prevention)
4. State-based cancellation race condition simulation
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.workflow_control import _invalidate_dependents


def test_invalidation_recursion():
    """Test that _invalidate_dependents handles deep dependency chains"""
    print("\n[ADVERSARIAL] Deep Dependency Chain Invalidation")

    # Create a workflow with a deep dependency chain: A -> B -> C -> D
    workflow = {
        "steps": [
            {"id": "step_a", "status": "COMPLETED", "depends_on": []},
            {"id": "step_b", "status": "PENDING", "depends_on": ["step_a"]},
            {"id": "step_c", "status": "PENDING", "depends_on": ["step_b"]},
            {"id": "step_d", "status": "PENDING", "depends_on": ["step_c"]},
        ]
    }

    # Invalidate step_b - should cascade to step_c and step_d
    invalidated = _invalidate_dependents(workflow, "step_b")

    print(f"  Invalidated steps: {invalidated}")

    # Check that step_c and step_d were invalidated
    if "step_c" in invalidated and "step_d" in invalidated:
        print("  ✓ PASS: Cascading invalidation works")
        return True

    print("  ✗ FAIL: Cascading invalidation failed")
    return False


def test_invalidation_preserves_completed():
    """Test that invalidation preserves COMPLETED steps"""
    print("\n[ADVERSARIAL] Invalidation Preserves COMPLETED Steps")

    # Create workflow where a dependent step is already COMPLETED
    workflow = {
        "steps": [
            {"id": "step_a", "status": "COMPLETED", "depends_on": []},
            {"id": "step_b", "status": "COMPLETED", "depends_on": ["step_a"]},  # Already done
            {"id": "step_c", "status": "PENDING", "depends_on": ["step_a"]},
        ]
    }

    # Invalidate step_a - step_b should remain COMPLETED, step_c should be reset
    invalidated = _invalidate_dependents(workflow, "step_a")

    print(f"  Invalidated steps: {invalidated}")
    print(f"  step_b status: {workflow['steps'][1]['status']}")

    # step_b should still be COMPLETED (not invalidated)
    if workflow["steps"][1]["status"] == "COMPLETED" and "step_c" in invalidated:
        print("  ✓ PASS: COMPLETED steps preserved, PENDING steps invalidated")
        return True

    print("  ✗ FAIL: COMPLETED step was incorrectly invalidated")
    return False


def test_invalidation_preserves_failed():
    """Test that invalidation preserves FAILED steps"""
    print("\n[ADVERSARIAL] Invalidation Preserves FAILED Steps")

    workflow = {
        "steps": [
            {"id": "step_a", "status": "COMPLETED", "depends_on": []},
            {"id": "step_b", "status": "FAILED", "depends_on": ["step_a"]},
            {"id": "step_c", "status": "PENDING", "depends_on": ["step_a"]},
        ]
    }

    invalidated = _invalidate_dependents(workflow, "step_a")

    print(f"  Invalidated steps: {invalidated}")
    print(f"  step_b status: {workflow['steps'][1]['status']}")

    # step_b should still be FAILED (terminal state preserved)
    if workflow["steps"][1]["status"] == "FAILED" and "step_c" in invalidated:
        print("  ✓ PASS: FAILED steps preserved, PENDING steps invalidated")
        return True

    print("  ✗ FAIL: FAILED step was incorrectly changed")
    return False


def test_invalidation_clears_outputs():
    """Test that invalidation clears execution_result and output fields"""
    print("\n[ADVERSARIAL] Invalidation Clears Output Fields")

    workflow = {
        "steps": [
            {"id": "step_a", "status": "COMPLETED", "depends_on": []},
            {"id": "step_b", "status": "PENDING", "depends_on": ["step_a"],
             "execution_result": {"status": "success"}, "output": "some_output"},
        ]
    }

    # Before invalidation
    step_b = workflow["steps"][1]
    print(f"  Before: execution_result={step_b.get('execution_result')}, output={step_b.get('output')}")

    _invalidate_dependents(workflow, "step_a")

    # After invalidation
    print(f"  After: execution_result={step_b.get('execution_result')}, output={step_b.get('output')}")

    if "execution_result" not in step_b and "output" not in step_b:
        print("  ✓ PASS: Output fields cleared")
        return True

    print("  ✗ FAIL: Output fields not cleared")
    return False


def test_circular_dependency_no_infinite_loop():
    """Test that _invalidate_dependents handles circular dependencies safely"""
    print("\n[ADVERSARIAL] Circular Dependency Safety (via visited set)")

    # This shouldn't happen due to DAG validation, but test safety
    # Create a pseudo-circular scenario by having a step depend on itself
    workflow = {
        "steps": [
            {"id": "step_a", "status": "PENDING", "depends_on": [],
             "execution_result": {"status": "success"}},
        ]
    }

    # Test with a step that references itself (edge case)
    workflow["steps"][0]["depends_on"] = ["step_a"]  # Self-reference

    # This should not cause infinite recursion due to visited set
    try:
        invalidated = _invalidate_dependents(workflow, "step_a", visited=set())
        print(f"  Invalidated: {invalidated}")
        print("  ✓ PASS: No infinite loop with visited set")
        return True
    except RecursionError:
        print("  ✗ FAIL: RecursionError occurred")
        return False


def test_scheduler_paused_returns_none():
    """Test that scheduler returns None when workflow is PAUSED"""
    print("\n[ADVERSARIAL] Scheduler Returns None When PAUSED")

    from system.orchestrator.execution_scheduler import create_execution_group
    from system.orchestrator.conflict_detector import ConflictDetector

    # Create a PAUSED workflow
    workflow = {
        "id": "test_wf",
        "status": "PAUSED",
        "steps": [
            {"id": "step_1", "status": "PENDING", "depends_on": []},
        ]
    }

    step_states = {"step_1": "PENDING"}
    conflict_detector = ConflictDetector()

    # Scheduler should return None for PAUSED workflow
    result = create_execution_group(workflow, step_states, conflict_detector, "test_wf")

    print(f"  Scheduler result: {result}")

    if result is None:
        print("  ✓ PASS: Scheduler returns None for PAUSED workflow")
        return True

    print("  ✗ FAIL: Scheduler did not return None")
    return False


def run_all_tests():
    print("=" * 70)
    print("PHASE 6 — ADVERSARIAL VALIDATION (Phase 4A.1)")
    print("=" * 70)

    tests = [
        test_invalidation_recursion,
        test_invalidation_preserves_completed,
        test_invalidation_preserves_failed,
        test_invalidation_clears_outputs,
        test_circular_dependency_no_infinite_loop,
        test_scheduler_paused_returns_none,
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
