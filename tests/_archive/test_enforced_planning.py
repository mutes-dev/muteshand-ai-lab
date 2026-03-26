"""
Test script for enforced multi-step plan generation.

Tests the planner's ability to:
1. Generate valid linear multi-step plans
2. Reject invalid non-linear plans
3. Handle single-step plans correctly
"""

import sys
import os
import json

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.planner import generate_structured_plan

# Mock tool names for testing
tool_names = [
    "add_numbers",
    "subtract_numbers",
    "multiply_numbers",
    "divide_numbers",
    "square_number"
]

print("="*80)
print("ENFORCED MULTI-STEP PLAN GENERATION TESTS")
print("="*80)

# Test cases
test_cases = [
    {
        "name": "VALID: Linear multi-step with 'then'",
        "input": "add 3 and 5 then square the result",
        "should_succeed": True,
        "expected_steps": 2,
        "expected_structure": [
            {"has_previous_result": False},
            {"has_previous_result": True}
        ]
    },
    {
        "name": "INVALID: Independent operations (no reference)",
        "input": "add 2 and 3 and add 4 and 5",
        "should_succeed": False,
        "reason": "Second operation doesn't reference previous result"
    },
    {
        "name": "INVALID: Multi-source (appears sequential but isn't)",
        "input": "add 2 and 3 then add 4 and 5",
        "should_succeed": False,
        "reason": "Second operation doesn't reference previous result"
    },
    {
        "name": "VALID: Single step (unchanged behavior)",
        "input": "add 3 and 5",
        "should_succeed": True,
        "expected_steps": 1,
        "expected_structure": [
            {"has_previous_result": False}
        ]
    },
    {
        "name": "VALID: Linear multi-step with 'after that'",
        "input": "multiply 2 and 3 after that square the result",
        "should_succeed": True,
        "expected_steps": 2,
        "expected_structure": [
            {"has_previous_result": False},
            {"has_previous_result": True}
        ]
    }
]

print("\nRunning tests...\n")

passed = 0
failed = 0

for idx, test in enumerate(test_cases, 1):
    print(f"Test {idx}: {test['name']}")
    print(f"  Input: {test['input']}")
    print()
    
    try:
        result = generate_structured_plan(test['input'], tool_names)
        
        if test['should_succeed']:
            if result is None:
                print(f"  Status: ✗ FAIL - Expected success but got None")
                failed += 1
            else:
                # Validate structure
                if len(result) != test['expected_steps']:
                    print(f"  Status: ✗ FAIL - Expected {test['expected_steps']} steps, got {len(result)}")
                    failed += 1
                else:
                    # Check PREVIOUS_RESULT usage
                    structure_valid = True
                    for step_idx, step in enumerate(result):
                        expected = test['expected_structure'][step_idx]
                        has_prev = "PREVIOUS_RESULT" in step.get("args", [])
                        
                        if has_prev != expected['has_previous_result']:
                            print(f"  Status: ✗ FAIL - Step {step_idx + 1} PREVIOUS_RESULT mismatch")
                            structure_valid = False
                            break
                    
                    if structure_valid:
                        print(f"  Status: ✓ PASS")
                        print(f"  Generated plan:")
                        for step_idx, step in enumerate(result):
                            print(f"    Step {step_idx + 1}: {step['name']} - args: {step['args']}")
                        passed += 1
                    else:
                        failed += 1
        else:
            if result is None:
                print(f"  Status: ✓ PASS - Correctly rejected")
                print(f"  Reason: {test['reason']}")
                passed += 1
            else:
                print(f"  Status: ✗ FAIL - Should have been rejected but succeeded")
                print(f"  Generated plan: {json.dumps(result, indent=2)}")
                failed += 1
    
    except Exception as e:
        if test['should_succeed']:
            print(f"  Status: ✗ FAIL - Unexpected exception: {e}")
            failed += 1
        else:
            print(f"  Status: ✓ PASS - Correctly raised exception")
            print(f"  Exception: {e}")
            passed += 1
    
    print()

print("="*80)
print(f"RESULTS: {passed} passed, {failed} failed")
print("="*80)
