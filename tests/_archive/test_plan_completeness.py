"""
Test script for plan completeness safeguard.

Tests the _enforce_plan_completeness function to ensure it catches
all invalid, partial, or degraded plans.
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.planner import _enforce_plan_completeness

print("="*80)
print("PLAN COMPLETENESS SAFEGUARD TESTS")
print("="*80)

# Test cases
test_cases = [
    {
        "name": "VALID: Single-step plan",
        "operations": ["add 3 and 5"],
        "plan": [
            {"type": "tool", "name": "add_numbers", "args": [3, 5], "input_text": "3 and 5"}
        ],
        "should_pass": True
    },
    {
        "name": "VALID: Two-step plan with correct chaining",
        "operations": ["add 3 and 5", "square the result"],
        "plan": [
            {"type": "tool", "name": "add_numbers", "args": [3, 5], "input_text": "3 and 5"},
            {"type": "tool", "name": "square_number", "args": ["PREVIOUS_RESULT"], "input_text": "result of previous step"}
        ],
        "should_pass": True
    },
    {
        "name": "INVALID: Empty plan",
        "operations": ["add 3 and 5"],
        "plan": [],
        "should_pass": False,
        "expected_error": "Plan incomplete: empty plan returned"
    },
    {
        "name": "INVALID: Step count mismatch (too few steps)",
        "operations": ["add 3 and 5", "square the result"],
        "plan": [
            {"type": "tool", "name": "add_numbers", "args": [3, 5], "input_text": "3 and 5"}
        ],
        "should_pass": False,
        "expected_error": "Plan incomplete: step count does not match"
    },
    {
        "name": "INVALID: Step count mismatch (too many steps)",
        "operations": ["add 3 and 5"],
        "plan": [
            {"type": "tool", "name": "add_numbers", "args": [3, 5], "input_text": "3 and 5"},
            {"type": "tool", "name": "square_number", "args": ["PREVIOUS_RESULT"], "input_text": "result"}
        ],
        "should_pass": False,
        "expected_error": "Plan incomplete: step count does not match"
    },
    {
        "name": "INVALID: Step is not a dict",
        "operations": ["add 3 and 5"],
        "plan": ["not a dict"],
        "should_pass": False,
        "expected_error": "Invalid step at index 0: not a dict"
    },
    {
        "name": "INVALID: Missing required fields",
        "operations": ["add 3 and 5"],
        "plan": [
            {"type": "tool", "name": "add_numbers"}  # Missing args and input_text
        ],
        "should_pass": False,
        "expected_error": "Incomplete step at index 0: missing required fields"
    },
    {
        "name": "INVALID: First step uses PREVIOUS_RESULT",
        "operations": ["add 3 and 5"],
        "plan": [
            {"type": "tool", "name": "add_numbers", "args": ["PREVIOUS_RESULT"], "input_text": "result"}
        ],
        "should_pass": False,
        "expected_error": "Invalid plan: first step cannot use PREVIOUS_RESULT"
    },
    {
        "name": "INVALID: Broken chaining (second step doesn't use PREVIOUS_RESULT)",
        "operations": ["add 3 and 5", "square the result"],
        "plan": [
            {"type": "tool", "name": "add_numbers", "args": [3, 5], "input_text": "3 and 5"},
            {"type": "tool", "name": "square_number", "args": [5], "input_text": "5"}
        ],
        "should_pass": False,
        "expected_error": "Invalid chaining at step 2"
    },
    {
        "name": "INVALID: Broken chaining (second step has extra args)",
        "operations": ["add 3 and 5", "multiply the result by 3"],
        "plan": [
            {"type": "tool", "name": "add_numbers", "args": [3, 5], "input_text": "3 and 5"},
            {"type": "tool", "name": "multiply_numbers", "args": ["PREVIOUS_RESULT", 3], "input_text": "result and 3"}
        ],
        "should_pass": False,
        "expected_error": "Invalid chaining at step 2"
    },
    {
        "name": "VALID: Three-step plan with correct chaining",
        "operations": ["add 1 and 2", "multiply the result by 3", "square that"],
        "plan": [
            {"type": "tool", "name": "add_numbers", "args": [1, 2], "input_text": "1 and 2"},
            {"type": "tool", "name": "multiply_numbers", "args": ["PREVIOUS_RESULT"], "input_text": "result"},
            {"type": "tool", "name": "square_number", "args": ["PREVIOUS_RESULT"], "input_text": "result"}
        ],
        "should_pass": True
    }
]

print("\nRunning tests...\n")

passed = 0
failed = 0

for idx, test in enumerate(test_cases, 1):
    print(f"Test {idx}: {test['name']}")
    
    try:
        _enforce_plan_completeness(test['operations'], test['plan'])
        
        if test['should_pass']:
            print(f"  Status: ✓ PASS - Plan validated successfully")
            passed += 1
        else:
            print(f"  Status: ✗ FAIL - Should have raised ValueError but didn't")
            failed += 1
    
    except ValueError as e:
        error_msg = str(e)
        
        if not test['should_pass']:
            if test['expected_error'] in error_msg:
                print(f"  Status: ✓ PASS - Correctly rejected")
                print(f"  Error: {error_msg[:80]}...")
                passed += 1
            else:
                print(f"  Status: ✗ FAIL - Raised ValueError but wrong message")
                print(f"  Expected: {test['expected_error']}")
                print(f"  Got: {error_msg}")
                failed += 1
        else:
            print(f"  Status: ✗ FAIL - Should have passed but raised ValueError")
            print(f"  Error: {error_msg}")
            failed += 1
    
    print()

print("="*80)
print(f"RESULTS: {passed} passed, {failed} failed")
print("="*80)

# Summary of rules tested
print("\n" + "="*80)
print("RULE COVERAGE SUMMARY")
print("="*80)
print("✓ RULE 1: NO EMPTY PLAN")
print("✓ RULE 2: STEP COUNT MATCH")
print("✓ RULE 3: VALID STEP STRUCTURE")
print("✓ RULE 4: FIRST STEP MUST NOT USE PREVIOUS_RESULT")
print("✓ RULE 5: CHAINING INTEGRITY (subsequent steps must use PREVIOUS_RESULT only)")
print("="*80)
