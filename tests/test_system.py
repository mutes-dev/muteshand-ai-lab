"""
System Integration Test Suite

Tests full pipeline: Entry → Validation → Execution
NO mocks. NO simulations. REAL execution only.
"""

import sys
import os
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.entry import run


def test_valid_plan_full_pipeline():
    """TEST 1 — VALID PLAN: Full pipeline success (entry → validation → execution)."""
    print("=" * 60)
    print("TEST 1 — VALID PLAN FULL PIPELINE")
    print("=" * 60)
    
    tool_registry = {
        "add": {"args": 2, "types": [int, int]},
        "multiply": {"args": 2, "types": [int, int]}
    }
    
    plan = [
        {"tool": "add", "args": [2, 3]},
        {"tool": "multiply", "args": ["PREVIOUS_RESULT", 4]}
    ]
    
    result = run(plan, tool_registry)
    print(f"Input plan: {json.dumps(plan)}")
    print(f"Output: {json.dumps(result, indent=2)}")
    
    passed = (
        result.get("status") == "success" and
        result.get("result") == 20 and
        len(result.get("steps", [])) == 2
    )
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected: success, result=20, 2 steps")
    return passed


def test_invalid_tool_stops_at_validation():
    """TEST 2 — INVALID TOOL: Fails at validation, execution never called."""
    print("\n" + "=" * 60)
    print("TEST 2 — INVALID TOOL STOPS AT VALIDATION")
    print("=" * 60)
    
    tool_registry = {
        "add": {"args": 2, "types": [int, int]},
        "multiply": {"args": 2, "types": [int, int]}
    }
    
    plan = [{"tool": "nonexistent", "args": [1, 2]}]
    
    result = run(plan, tool_registry)
    print(f"Input plan: {json.dumps(plan)}")
    print(f"Output: {json.dumps(result)}")
    
    passed = (
        result.get("status") == "failure" and
        result.get("reason") == "tool_not_found"
    )
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected: failure, reason=tool_not_found")
    return passed


def test_invalid_structure_stops_at_validation():
    """TEST 3 — INVALID STRUCTURE: Fails at validation, execution never called."""
    print("\n" + "=" * 60)
    print("TEST 3 — INVALID STRUCTURE STOPS AT VALIDATION")
    print("=" * 60)
    
    tool_registry = {
        "add": {"args": 2, "types": [int, int]},
        "multiply": {"args": 2, "types": [int, int]}
    }
    
    plan = [{"tool": "add"}]  # Missing "args"
    
    result = run(plan, tool_registry)
    print(f"Input plan: {json.dumps(plan)}")
    print(f"Output: {json.dumps(result)}")
    
    passed = (
        result.get("status") == "failure" and
        result.get("reason") == "invalid_step_structure"
    )
    print(f"\n[{'PASS' if passed else 'FAIL'}] Expected: failure, reason=invalid_step_structure")
    return passed


def main():
    """Run all system integration tests."""
    print("\n" + "=" * 60)
    print("SYSTEM INTEGRATION TEST SUITE")
    print("=" * 60)
    
    results = {
        "test1_valid_plan_full_pipeline": test_valid_plan_full_pipeline(),
        "test2_invalid_tool_stops_at_validation": test_invalid_tool_stops_at_validation(),
        "test3_invalid_structure_stops_at_validation": test_invalid_structure_stops_at_validation()
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
