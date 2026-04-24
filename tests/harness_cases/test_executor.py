"""
Execution Harness — Phase 1 Validation

Validates executor behavior using real execution.
NO mocks. NO simulations. REAL execution only.
"""

import sys
import os
import json

# Add parent directory to path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, str(PROJECT_ROOT))

from system.execution.executor import execute


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


# Local execution registry for test tools
execution_registry = {
    "add": lambda a, b: a + b,
    "multiply": lambda a, b: a * b
}


def test_determinism():
    """TEST 1 — DETERMINISM: Run same plan 3 times, verify identical outputs."""
    print("=" * 60)
    print("TEST 1 — DETERMINISM (3 runs)")
    print("=" * 60)
    
    plan = [
        {"tool": "add", "args": [2, 3]},
        {"tool": "multiply", "args": ["PREVIOUS_RESULT", 4]}
    ]
    
    outputs = []
    for i in range(3):
        result = execute(plan, execution_registry)
        outputs.append(result)
        print(f"\nRun {i+1}:")
        print(json.dumps(result, indent=2))
    
    # Verify all match
    all_match = all(
        o['status'] == outputs[0]['status'] and
        o['result'] == outputs[0]['result'] and
        len(o.get('steps', [])) == len(outputs[0].get('steps', []))
        for o in outputs
    )
    
    print(f"\n[{'PASS' if all_match else 'FAIL'}] Determinism: {'VERIFIED' if all_match else 'FAILED'}")
    return all_match


def test_contract():
    """TEST 2 — CONTRACT: Verify output structure matches contract."""
    print("\n" + "=" * 60)
    print("TEST 2 — CONTRACT VALIDATION")
    print("=" * 60)
    
    plan = [
        {"tool": "add", "args": [2, 3]},
        {"tool": "multiply", "args": ["PREVIOUS_RESULT", 4]}
    ]
    
    result = execute(plan, execution_registry)
    print("\nRaw output:")
    print(json.dumps(result, indent=2))
    
    # Verify top-level fields
    has_status = 'status' in result
    has_result = 'result' in result
    has_steps = 'steps' in result and isinstance(result['steps'], list)
    
    print(f"\nField checks:")
    print(f"  - status exists: {has_status} [{'✓' if has_status else '✗'}]")
    print(f"  - result exists: {has_result} [{'✓' if has_result else '✗'}]")
    print(f"  - steps is list: {has_steps} [{'✓' if has_steps else '✗'}]")
    
    # Verify step structure
    steps_valid = True
    if has_steps:
        for i, step in enumerate(result['steps']):
            has_tool = 'tool' in step
            has_args = 'args' in step
            has_output = 'output' in step
            step_valid = has_tool and has_args and has_output
            steps_valid = steps_valid and step_valid
            print(f"  - step {i}: tool={has_tool}, args={has_args}, output={has_output} [{'✓' if step_valid else '✗'}]")
    
    passed = has_status and has_result and has_steps and steps_valid
    print(f"\n[{'PASS' if passed else 'FAIL'}] Contract validation")
    return passed


def test_execution_correctness():
    """TEST 3 — EXECUTION CORRECTNESS: Verify correct computation."""
    print("\n" + "=" * 60)
    print("TEST 3 — EXECUTION CORRECTNESS")
    print("=" * 60)
    
    plan = [
        {"tool": "add", "args": [5, 5]},
        {"tool": "multiply", "args": ["PREVIOUS_RESULT", 3]}
    ]
    
    result = execute(plan, execution_registry)
    print("\nInput: add(5,5) then multiply(PREVIOUS_RESULT, 3)")
    print(f"Expected: 30")
    print("\nRaw output:")
    print(json.dumps(result, indent=2))
    
    correct = result.get('result') == 30 and result.get('status') == 'success'
    print(f"\n[{'PASS' if correct else 'FAIL'}] Execution correctness: {result.get('result')} == 30")
    return correct


def test_failure_cases():
    """TEST 4 — FAILURE CASES: Verify proper failure handling."""
    print("\n" + "=" * 60)
    print("TEST 4 — FAILURE CASES")
    print("=" * 60)
    
    all_passed = True
    
    # 4a: Missing PREVIOUS_RESULT
    print("\n4a) Missing PREVIOUS_RESULT:")
    plan_a = [{"tool": "multiply", "args": ["PREVIOUS_RESULT", 5]}]
    result_a = execute(plan_a, execution_registry)
    print(json.dumps(result_a, indent=2))
    
    # STRICT CONTRACT ASSERTIONS
    assert result_a["status"] == "failure", f"Expected status 'failure', got '{result_a.get('status')}'"
    assert "reason" in result_a, "Missing 'reason' field"
    assert isinstance(result_a["reason"], str), f"'reason' must be string, got {type(result_a['reason'])}"
    assert result_a["reason"].strip() != "", "'reason' must not be empty"
    
    passed_a = result_a.get('status') == 'failure'
    all_passed = all_passed and passed_a
    print(f"[{'PASS' if passed_a else 'FAIL'}] Status is 'failure': {result_a.get('status')}")
    
    # 4b: Multiple PREVIOUS_RESULT
    print("\n4b) Multiple PREVIOUS_RESULT:")
    plan_b = [{"tool": "add", "args": ["PREVIOUS_RESULT", "PREVIOUS_RESULT"]}]
    result_b = execute(plan_b, execution_registry)
    print(json.dumps(result_b, indent=2))
    
    # STRICT CONTRACT ASSERTIONS
    assert result_b["status"] == "failure", f"Expected status 'failure', got '{result_b.get('status')}'"
    assert "reason" in result_b, "Missing 'reason' field"
    assert isinstance(result_b["reason"], str), f"'reason' must be string, got {type(result_b['reason'])}"
    assert result_b["reason"].strip() != "", "'reason' must not be empty"
    
    passed_b = result_b.get('status') == 'failure'
    all_passed = all_passed and passed_b
    print(f"[{'PASS' if passed_b else 'FAIL'}] Status is 'failure': {result_b.get('status')}")
    
    # 4c: Invalid tool
    print("\n4c) Invalid tool:")
    plan_c = [{"tool": "nonexistent", "args": [1, 2]}]
    result_c = execute(plan_c, execution_registry)
    print(json.dumps(result_c, indent=2))
    
    # STRICT CONTRACT ASSERTIONS
    assert result_c["status"] == "failure", f"Expected status 'failure', got '{result_c.get('status')}'"
    assert "reason" in result_c, "Missing 'reason' field"
    assert isinstance(result_c["reason"], str), f"'reason' must be string, got {type(result_c['reason'])}"
    assert result_c["reason"].strip() != "", "'reason' must not be empty"
    
    passed_c = result_c.get('status') == 'failure'
    all_passed = all_passed and passed_c
    print(f"[{'PASS' if passed_c else 'FAIL'}] Status is 'failure': {result_c.get('status')}")
    
    print(f"\n[{'PASS' if all_passed else 'FAIL'}] All failure cases")
    return all_passed


def main():
    """Run all tests and report results."""
    print("\n" + "=" * 60)
    print("EXECUTION HARNESS — PHASE 1 VALIDATION")
    print("=" * 60)
    
    results = {
        "determinism": test_determinism(),
        "contract": test_contract(),
        "execution": test_execution_correctness(),
        "failure_cases": test_failure_cases()
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
