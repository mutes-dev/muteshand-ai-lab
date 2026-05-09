"""
Phase 3.5 — Adversarial Validation Tests

Tests edge cases and attack scenarios:
1. Malformed step input
2. Dependency failure chains
3. Attempt to execute non-production tool
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.workflow_validator import validate_workflow
from system.orchestrator.execution_scheduler import _check_dependencies_satisfied
from system.entry.system_entry import system_entry


def test_malformed_step_missing_id():
    """Step without id field should fail validation"""
    print("\n[ADVERSARIAL] Step Missing ID")

    workflow = {
        "id": "wf_001",
        "name": "test",
        "status": "QUEUED",
        "steps": [
            {
                # Missing "id"
                "type": "EXECUTE_API",
                "purpose": "Test",
                "tool_call": "test",
                "expected_outcome": "Test",
                "risk": "LOW",
                "importance": "MEDIUM",
                "resource_targets": []
            }
        ]
    }

    result = validate_workflow(workflow)
    print(f"  Result: {result}")

    if result.get("status") == "failure" and "missing_step_field:id" in result.get("reason", ""):
        print("  ✓ PASS: Missing ID rejected")
        return True
    print("  ✗ FAIL: Missing ID not rejected")
    return False


def test_malformed_step_empty_purpose():
    """Step with empty purpose should still pass (field exists)"""
    print("\n[ADVERSARIAL] Step Empty Purpose")

    workflow = {
        "id": "wf_002",
        "name": "test",
        "status": "QUEUED",
        "steps": [
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "",  # Empty but present
                "tool_call": "test",
                "expected_outcome": "Test",
                "risk": "LOW",
                "importance": "MEDIUM",
                "resource_targets": []
            }
        ]
    }

    result = validate_workflow(workflow)
    print(f"  Result: {result}")

    # Empty purpose is still valid (field exists)
    if result.get("status") == "success":
        print("  ✓ PASS: Empty purpose accepted (field present)")
        return True
    print("  ✗ FAIL: Empty purpose rejected unexpectedly")
    return False


def test_dependency_failure_chain():
    """Chain: step_1 FAILED → step_2 depends on step_1 → step_3 depends on step_2"""
    print("\n[ADVERSARIAL] Dependency Failure Chain")

    steps_map = {
        "step_1": {"id": "step_1"},
        "step_2": {"id": "step_2"},
        "step_3": {"id": "step_3"}
    }

    # step_1 FAILED, step_2 and step_3 both depend on previous
    step_states = {
        "step_1": "FAILED",
        "step_2": "PENDING",  # Depends on step_1
        "step_3": "PENDING"   # Depends on step_2
    }

    # Check step_2 (direct dependency on FAILED step_1)
    step_2 = {"id": "step_2", "depends_on": ["step_1"]}
    satisfied_2, reason_2 = _check_dependencies_satisfied(step_2, step_states, steps_map)
    print(f"  step_2 (depends on step_1 FAILED): satisfied={satisfied_2}, reason={reason_2}")

    # Check step_3 (depends on step_2 which is PENDING, but step_1 is FAILED)
    # Note: step_3's immediate dependency is step_2 (PENDING), not step_1
    step_3 = {"id": "step_3", "depends_on": ["step_2"]}
    satisfied_3, reason_3 = _check_dependencies_satisfied(step_3, step_states, steps_map)
    print(f"  step_3 (depends on step_2 PENDING): satisfied={satisfied_3}, reason={reason_3}")

    if not satisfied_2 and "dependency_failed" in reason_2 and not satisfied_3:
        print("  ✓ PASS: Failure chain correctly blocked")
        return True
    print("  ✗ FAIL: Failure chain not blocked")
    return False


def test_circular_dependency_detected():
    """Circular dependency should be detected by DAG validation"""
    print("\n[ADVERSARIAL] Circular Dependency Detection")

    workflow = {
        "id": "wf_003",
        "name": "test",
        "status": "QUEUED",
        "steps": [
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "Step 1",
                "tool_call": "test",
                "expected_outcome": "Test",
                "risk": "LOW",
                "importance": "MEDIUM",
                "resource_targets": [],
                "depends_on": ["step_3"]  # Depends on step_3
            },
            {
                "id": "step_2",
                "type": "EXECUTE_API",
                "purpose": "Step 2",
                "tool_call": "test",
                "expected_outcome": "Test",
                "risk": "LOW",
                "importance": "MEDIUM",
                "resource_targets": [],
                "depends_on": ["step_1"]  # Depends on step_1
            },
            {
                "id": "step_3",
                "type": "EXECUTE_API",
                "purpose": "Step 3",
                "tool_call": "test",
                "expected_outcome": "Test",
                "risk": "LOW",
                "importance": "MEDIUM",
                "resource_targets": [],
                "depends_on": ["step_2"]  # Depends on step_2 (CYCLE!)
            }
        ]
    }

    result = validate_workflow(workflow)
    print(f"  Result: {result}")

    if result.get("status") == "failure" and "circular_dependency" in result.get("reason", ""):
        print("  ✓ PASS: Circular dependency detected")
        return True
    print("  ✗ FAIL: Circular dependency not detected")
    return False


def test_non_production_tool_by_name():
    """Attempt to execute non-production tool by exact name"""
    print("\n[ADVERSARIAL] Non-Production Tool Execution Attempt")

    # Try to execute a non-production tool (bad_add has production: false)
    result = system_entry("bad_add 5 10")
    print(f"  Result: {result}")

    if result.get("status") == "failure" and result.get("reason") == "non_production_tool":
        print("  ✓ PASS: Non-production tool blocked")
        return True
    print("  ✗ FAIL: Non-production tool not blocked")
    return False


def test_unknown_tool():
    """Attempt to execute unknown/non-existent tool"""
    print("\n[ADVERSARIAL] Unknown Tool Execution Attempt")

    result = system_entry("nonexistent_tool_12345 arg1 arg2")
    print(f"  Result: {result}")

    if result.get("status") == "failure" and result.get("reason") == "unknown_tool":
        print("  ✓ PASS: Unknown tool rejected")
        return True
    print("  ✗ FAIL: Unknown tool not rejected properly")
    return False


def test_invalid_risk_high():
    """Test that CRITICAL risk level is rejected (not in LOW/MEDIUM/HIGH)"""
    print("\n[ADVERSARIAL] Invalid Risk Level (CRITICAL)")

    workflow = {
        "id": "wf_004",
        "name": "test",
        "status": "QUEUED",
        "steps": [
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "Test",
                "tool_call": "test",
                "expected_outcome": "Test",
                "risk": "CRITICAL",  # Invalid value
                "importance": "MEDIUM",
                "resource_targets": []
            }
        ]
    }

    result = validate_workflow(workflow)
    print(f"  Result: {result}")

    if result.get("status") == "failure" and "invalid_risk_level" in result.get("reason", ""):
        print("  ✓ PASS: Invalid risk level rejected")
        return True
    print("  ✗ FAIL: Invalid risk level not rejected")
    return False


def run_all_tests():
    print("=" * 60)
    print("PHASE 6 — ADVERSARIAL VALIDATION TESTS")
    print("=" * 60)

    tests = [
        test_malformed_step_missing_id,
        test_malformed_step_empty_purpose,
        test_dependency_failure_chain,
        test_circular_dependency_detected,
        test_non_production_tool_by_name,
        test_unknown_tool,
        test_invalid_risk_high,
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
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
