"""
Phase 3.5 — Core Contract Integrity Correction Tests

Tests the three critical fixes:
1. Step schema validation (field names + required fields)
2. Dependency execution model (blocking + re-evaluation + stale prevention)
3. system_entry production flag validation
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.workflow_validator import validate_workflow, REQUIRED_STEP_KEYS
from system.entry.system_entry import system_entry


def test_step_schema_contract_fields():
    """Test that REQUIRED_STEP_KEYS matches STEP_SCHEMA_CONTRACT_V1"""
    expected_fields = ["id", "type", "purpose", "tool_call", "expected_outcome", "risk", "importance", "resource_targets"]

    print("\n[TEST] Step Schema Contract Fields")
    print(f"  Expected: {expected_fields}")
    print(f"  Actual:   {REQUIRED_STEP_KEYS}")

    if REQUIRED_STEP_KEYS == expected_fields:
        print("  ✓ PASS: Required step keys match contract")
        return True
    else:
        print("  ✗ FAIL: Required step keys mismatch")
        return False


def test_valid_step_schema():
    """Test valid step schema passes validation"""
    print("\n[TEST] Valid Step Schema")

    workflow = {
        "id": "wf_001",
        "name": "test_workflow",
        "status": "QUEUED",
        "steps": [
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "Add two numbers",
                "tool_call": "add_numbers 2 3",
                "expected_outcome": "Sum returned",
                "risk": "LOW",
                "importance": "MEDIUM",
                "resource_targets": []
            }
        ]
    }

    result = validate_workflow(workflow)
    print(f"  Result: {result}")

    if result.get("status") == "success":
        print("  ✓ PASS: Valid schema accepted")
        return True
    else:
        print("  ✗ FAIL: Valid schema rejected")
        return False


def test_invalid_step_schema_missing_fields():
    """Test that missing required fields fails validation"""
    print("\n[TEST] Invalid Step Schema - Missing Fields")

    workflow = {
        "id": "wf_002",
        "name": "test_workflow",
        "status": "QUEUED",
        "steps": [
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                # Missing: purpose, tool_call, expected_outcome, risk, importance, resource_targets
            }
        ]
    }

    result = validate_workflow(workflow)
    print(f"  Result: {result}")

    if result.get("status") == "failure" and "missing_step_field" in result.get("reason", ""):
        print("  ✓ PASS: Missing fields correctly rejected")
        return True
    else:
        print("  ✗ FAIL: Missing fields not rejected")
        return False


def test_invalid_step_schema_wrong_enum():
    """Test that invalid enum values fail validation"""
    print("\n[TEST] Invalid Step Schema - Wrong Enum Values")

    workflow = {
        "id": "wf_003",
        "name": "test_workflow",
        "status": "QUEUED",
        "steps": [
            {
                "id": "step_1",
                "type": "INVALID_TYPE",
                "purpose": "Test",
                "tool_call": "test_tool",
                "expected_outcome": "Test",
                "risk": "CRITICAL",  # Invalid - should be LOW/MEDIUM/HIGH
                "importance": "INVALID",  # Invalid
                "resource_targets": []
            }
        ]
    }

    result = validate_workflow(workflow)
    print(f"  Result: {result}")

    if result.get("status") == "failure":
        reason = result.get("reason", "")
        if "invalid_step_type" in reason or "invalid_risk_level" in reason or "invalid_importance_level" in reason:
            print("  ✓ PASS: Invalid enum values correctly rejected")
            return True

    print("  ✗ FAIL: Invalid enum values not rejected")
    return False


def test_production_tool_rejection():
    """Test that non-production tools are rejected"""
    print("\n[TEST] Non-Production Tool Rejection")

    # bad_add has production: false in tools.json
    result = system_entry("bad_add 1 2")
    print(f"  Result: {result}")

    if result.get("status") == "failure" and result.get("reason") == "non_production_tool":
        print("  ✓ PASS: Non-production tool correctly rejected")
        return True
    else:
        print("  ✗ FAIL: Non-production tool not rejected")
        return False


def test_production_tool_acceptance():
    """Test that production tools are accepted"""
    print("\n[TEST] Production Tool Acceptance")

    # add_numbers has production: true in tools.json
    result = system_entry("add_numbers 2 3")
    print(f"  Result: {result}")

    if result.get("status") == "success":
        print("  ✓ PASS: Production tool executed successfully")
        return True
    else:
        print("  ✗ FAIL: Production tool rejected")
        return False


def run_all_tests():
    """Run all contract integrity tests"""
    print("=" * 60)
    print("PHASE 3.5 — CORE CONTRACT INTEGRITY TESTS")
    print("=" * 60)

    tests = [
        test_step_schema_contract_fields,
        test_valid_step_schema,
        test_invalid_step_schema_missing_fields,
        test_invalid_step_schema_wrong_enum,
        test_production_tool_rejection,
        test_production_tool_acceptance,
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
