"""
Validation Layer Test Suite

Tests validation module behavior using real execution.
NO mocks. NO simulations. REAL validation only.
"""

import sys
import os
import json

# Add parent directory to path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, str(PROJECT_ROOT))

from core.validation import validate


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def test_success():
    """TEST 1 — SUCCESS: Valid plan passes validation."""
    print("=" * 60)
    print("TEST 1 — SUCCESS")
    print("=" * 60)
    
    tool_registry = {"add": {"args": 2, "types": [int, int]}}
    plan = [{"tool": "add", "args": [2, 3]}]
    
    result = validate(plan, tool_registry)
    print(f"Input: {json.dumps(plan)}")
    print(f"Output: {json.dumps(result)}")
    
    passed = result == {"status": "success"}
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected success")
    return passed


def test_invalid_plan_type():
    """TEST 2 — INVALID PLAN TYPE: Non-list plan fails."""
    print("\n" + "=" * 60)
    print("TEST 2 — INVALID PLAN TYPE")
    print("=" * 60)
    
    tool_registry = {"add": {"args": 2, "types": [int, int]}}
    plan = "not a list"
    
    result = validate(plan, tool_registry)
    print(f"Input: {repr(plan)}")
    print(f"Output: {json.dumps(result)}")
    
    passed = result.get("reason") == "invalid_plan_type"
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected reason: invalid_plan_type")
    return passed


def test_empty_plan():
    """TEST 3 — EMPTY PLAN: Empty list fails."""
    print("\n" + "=" * 60)
    print("TEST 3 — EMPTY PLAN")
    print("=" * 60)
    
    tool_registry = {"add": {"args": 2, "types": [int, int]}}
    plan = []
    
    result = validate(plan, tool_registry)
    print(f"Input: {json.dumps(plan)}")
    print(f"Output: {json.dumps(result)}")
    
    passed = result.get("reason") == "empty_plan"
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected reason: empty_plan")
    return passed


def test_invalid_step():
    """TEST 4 — INVALID STEP: Non-dict step fails."""
    print("\n" + "=" * 60)
    print("TEST 4 — INVALID STEP")
    print("=" * 60)
    
    tool_registry = {"add": {"args": 2, "types": [int, int]}}
    plan = [123]
    
    result = validate(plan, tool_registry)
    print(f"Input: {json.dumps(plan)}")
    print(f"Output: {json.dumps(result)}")
    
    passed = result.get("reason") == "invalid_step_structure"
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected reason: invalid_step_structure")
    return passed


def test_missing_args_field():
    """TEST — MISSING ARGS FIELD: Step without 'args' fails."""
    print("\n" + "=" * 60)
    print("TEST — MISSING ARGS FIELD")
    print("=" * 60)
    
    tool_registry = {"add": {"args": 2, "types": [int, int]}}
    plan = [{"tool": "add"}]
    
    result = validate(plan, tool_registry)
    print(f"Input: {json.dumps(plan)}")
    print(f"Output: {json.dumps(result)}")
    
    passed = result.get("status") == "failure" and result.get("reason") == "invalid_step_structure"
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected status: failure, reason: invalid_step_structure")
    return passed


def test_tool_not_found():
    """TEST 5 — TOOL NOT FOUND: Unknown tool fails."""
    print("\n" + "=" * 60)
    print("TEST 5 — TOOL NOT FOUND")
    print("=" * 60)
    
    tool_registry = {"add": {"args": 2, "types": [int, int]}}
    plan = [{"tool": "unknown", "args": [1, 2]}]
    
    result = validate(plan, tool_registry)
    print(f"Input: {json.dumps(plan)}")
    print(f"Output: {json.dumps(result)}")
    
    passed = result.get("reason") == "tool_not_found"
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected reason: tool_not_found")
    return passed


def test_argument_count_mismatch():
    """TEST 6 — ARG COUNT MISMATCH: Wrong argument count fails."""
    print("\n" + "=" * 60)
    print("TEST 6 — ARG COUNT MISMATCH")
    print("=" * 60)
    
    tool_registry = {"add": {"args": 2, "types": [int, int]}}
    plan = [{"tool": "add", "args": [1]}]
    
    result = validate(plan, tool_registry)
    print(f"Input: {json.dumps(plan)}")
    print(f"Output: {json.dumps(result)}")
    
    passed = result.get("reason") == "argument_count_mismatch"
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected reason: argument_count_mismatch")
    return passed


def test_argument_type_mismatch():
    """TEST 7 — ARG TYPE MISMATCH: Wrong argument type fails."""
    print("\n" + "=" * 60)
    print("TEST 7 — ARG TYPE MISMATCH")
    print("=" * 60)
    
    tool_registry = {"add": {"args": 2, "types": [int, int]}}
    plan = [{"tool": "add", "args": [1, "x"]}]
    
    result = validate(plan, tool_registry)
    print(f"Input: {json.dumps(plan)}")
    print(f"Output: {json.dumps(result)}")
    
    passed = result.get("reason") == "argument_type_mismatch"
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected reason: argument_type_mismatch")
    return passed


def test_previous_result_skip():
    """TEST 8 — PREVIOUS_RESULT: Placeholder is skipped during type check."""
    print("\n" + "=" * 60)
    print("TEST 8 — PREVIOUS_RESULT (SKIP TYPE CHECK)")
    print("=" * 60)
    
    tool_registry = {"add": {"args": 2, "types": [int, int]}}
    plan = [{"tool": "add", "args": ["PREVIOUS_RESULT", 2]}]
    
    result = validate(plan, tool_registry)
    print(f"Input: {json.dumps(plan)}")
    print(f"Output: {json.dumps(result)}")
    
    passed = result == {"status": "success"}
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected success (PREVIOUS_RESULT ignored)")
    return passed


def main():
    """Run all validation tests."""
    print("\n" + "=" * 60)
    print("VALIDATION LAYER TEST SUITE")
    print("=" * 60)
    
    results = {
        "success": test_success(),
        "invalid_plan_type": test_invalid_plan_type(),
        "empty_plan": test_empty_plan(),
        "invalid_step": test_invalid_step(),
        "missing_args_field": test_missing_args_field(),
        "tool_not_found": test_tool_not_found(),
        "argument_count_mismatch": test_argument_count_mismatch(),
        "argument_type_mismatch": test_argument_type_mismatch(),
        "previous_result_skip": test_previous_result_skip()
    }
    
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test_name}: {status}")
    
    all_passed = all(results.values())
    print("\n" + "=" * 60)
    print(f"OVERALL: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
