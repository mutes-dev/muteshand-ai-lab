"""
Dependency Model Contract Test — FAILED dependencies MUST block dependent steps
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.execution_scheduler import _check_dependencies_satisfied


def test_no_dependencies():
    """Step with no dependencies should be satisfied"""
    print("\n[TEST] No Dependencies")

    step = {"id": "step_1", "depends_on": []}
    step_states = {}
    steps_map = {}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if satisfied and reason == "no_dependencies":
        print("  ✓ PASS")
        return True
    print("  ✗ FAIL")
    return False


def test_all_dependencies_completed():
    """Step with all COMPLETED dependencies should be satisfied"""
    print("\n[TEST] All Dependencies Completed")

    step = {"id": "step_2", "depends_on": ["step_1"]}
    step_states = {"step_1": "COMPLETED"}
    steps_map = {"step_1": {"id": "step_1"}}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if satisfied and reason == "all_dependencies_completed":
        print("  ✓ PASS")
        return True
    print("  ✗ FAIL")
    return False


def test_dependency_failed():
    """Step with FAILED dependency should be blocked — per DEPENDENCY_MODEL_CONTRACT_V1"""
    print("\n[TEST] Dependency Failed — MUST BLOCK")

    step = {"id": "step_2", "depends_on": ["step_1"]}
    step_states = {"step_1": "FAILED"}
    steps_map = {"step_1": {"id": "step_1"}}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if not satisfied and "dependency_failed" in reason:
        print("  ✓ PASS: FAILED dependency correctly blocks step")
        return True
    print("  ✗ FAIL: FAILED dependency did not block step")
    return False


def test_dependency_pending():
    """Step with PENDING dependency should be blocked"""
    print("\n[TEST] Dependency Pending — MUST BLOCK")

    step = {"id": "step_2", "depends_on": ["step_1"]}
    step_states = {"step_1": "PENDING"}
    steps_map = {"step_1": {"id": "step_1"}}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if not satisfied and "dependency_not_completed" in reason:
        print("  ✓ PASS: PENDING dependency correctly blocks step")
        return True
    print("  ✗ FAIL: PENDING dependency did not block step")
    return False


def test_dependency_blocked():
    """Step with BLOCKED dependency should be blocked"""
    print("\n[TEST] Dependency Blocked — MUST BLOCK")

    step = {"id": "step_2", "depends_on": ["step_1"]}
    step_states = {"step_1": "BLOCKED"}
    steps_map = {"step_1": {"id": "step_1"}}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if not satisfied and "dependency_not_completed" in reason:
        print("  ✓ PASS: BLOCKED dependency correctly blocks step")
        return True
    print("  ✗ FAIL: BLOCKED dependency did not block step")
    return False


def test_multiple_dependencies_one_failed():
    """Step with multiple dependencies where one FAILED should be blocked"""
    print("\n[TEST] Multiple Dependencies — One Failed")

    step = {"id": "step_3", "depends_on": ["step_1", "step_2"]}
    step_states = {"step_1": "COMPLETED", "step_2": "FAILED"}
    steps_map = {"step_1": {"id": "step_1"}, "step_2": {"id": "step_2"}}

    satisfied, reason = _check_dependencies_satisfied(step, step_states, steps_map)
    print(f"  Result: satisfied={satisfied}, reason={reason}")

    if not satisfied and "dependency_failed" in reason:
        print("  ✓ PASS: One FAILED dependency correctly blocks step")
        return True
    print("  ✗ FAIL: FAILED dependency did not block step")
    return False


def run_all_tests():
    print("=" * 60)
    print("DEPENDENCY MODEL CONTRACT — BLOCKING TESTS")
    print("=" * 60)

    tests = [
        test_no_dependencies,
        test_all_dependencies_completed,
        test_dependency_failed,
        test_dependency_pending,
        test_dependency_blocked,
        test_multiple_dependencies_one_failed,
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
            print(f"  ✗ EXCEPTION: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
