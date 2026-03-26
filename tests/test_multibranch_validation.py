"""
Test script to verify multi-branch dependency blocking in validation.py
"""

import sys
import os

# Add paths
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from core.validation import validate_plan

# Test data
tool_index = {
    'add_numbers': {
        'inputs': {
            'a': 'number',
            'b': 'number'
        }
    },
    'multiply_numbers': {
        'inputs': {
            'x': 'number',
            'y': 'number'
        }
    },
}

print("="*80)
print("TEST: Multi-Branch Dependency Blocking")
print("="*80)
print()

# Test 1: Multi-branch reference (INVALID)
print("TEST 1: Multiple 'result of' References (INVALID)")
print("-"*80)
plan_multibranch = [
    {
        "type": "tool",
        "name": "add_numbers",
        "args": [1, 2],
        "input_text": "1 and 2"
    },
    {
        "type": "tool",
        "name": "multiply_numbers",
        "args": [3, 4],
        "input_text": "3 and 4"
    },
    {
        "type": "tool",
        "name": "add_numbers",
        "args": ["result of adding 1 and 2", "result of multiplying 3 and 4"],
        "input_text": "result of adding 1 and 2 and result of multiplying 3 and 4"
    }
]

print(f"Plan: Step 0: add 1 and 2")
print(f"      Step 1: multiply 3 and 4")
print(f"      Step 2: add 'result of adding 1 and 2' and 'result of multiplying 3 and 4'")
print()
print(f"Step 2 args contain multiple 'result of' references")
print()

is_valid, error = validate_plan(plan_multibranch, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if not is_valid and "Multiple result references not allowed" in error:
    print("✓ SUCCESS: Validation correctly rejected multi-branch dependency")
else:
    print("✗ FAILURE: Validation did not reject multi-branch dependency")

print()

# Test 2: Single 'result of' reference (VALID)
print("TEST 2: Single 'result of' Reference (VALID)")
print("-"*80)
plan_single_result = [
    {
        "type": "tool",
        "name": "add_numbers",
        "args": [1, 2],
        "input_text": "1 and 2"
    },
    {
        "type": "tool",
        "name": "multiply_numbers",
        "args": ["result of previous step", 5],
        "input_text": "result of previous step and 5"
    }
]

print(f"Plan: Step 0: add 1 and 2")
print(f"      Step 1: multiply 'result of previous step' by 5")
print()
print(f"Step 1 args contain only one 'result of' reference")
print()

is_valid, error = validate_plan(plan_single_result, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if is_valid:
    print("✓ SUCCESS: Validation correctly accepted single 'result of' reference")
else:
    print(f"✗ FAILURE: Validation rejected valid single reference: {error}")

print()

# Test 3: PREVIOUS_RESULT token (VALID - no 'result of' text)
print("TEST 3: PREVIOUS_RESULT Token (VALID)")
print("-"*80)
plan_previous_result = [
    {
        "type": "tool",
        "name": "add_numbers",
        "args": [1, 2],
        "input_text": "1 and 2"
    },
    {
        "type": "tool",
        "name": "multiply_numbers",
        "args": ["PREVIOUS_RESULT", 2],
        "input_text": "result of previous step and 2"
    }
]

print(f"Plan: Step 0: add 1 and 2")
print(f"      Step 1: multiply PREVIOUS_RESULT by 2")
print()
print(f"Step 1 uses PREVIOUS_RESULT token (not 'result of' text)")
print()

is_valid, error = validate_plan(plan_previous_result, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if is_valid:
    print("✓ SUCCESS: Validation correctly accepted PREVIOUS_RESULT token")
else:
    print(f"✗ FAILURE: Validation rejected PREVIOUS_RESULT: {error}")

print()

# Test 4: No chaining at all (VALID)
print("TEST 4: No Chaining (VALID)")
print("-"*80)
plan_no_chain = [
    {
        "type": "tool",
        "name": "add_numbers",
        "args": [5, 10],
        "input_text": "5 and 10"
    }
]

print(f"Plan: Step 0: add 5 and 10")
print(f"No chaining references")
print()

is_valid, error = validate_plan(plan_no_chain, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if is_valid:
    print("✓ SUCCESS: Validation correctly accepted plan with no chaining")
else:
    print(f"✗ FAILURE: Validation rejected valid plan: {error}")

print()

# Test 5: Multiple PREVIOUS_RESULT still blocked (existing rule)
print("TEST 5: Multiple PREVIOUS_RESULT Tokens (INVALID - Existing Rule)")
print("-"*80)
plan_multi_prev = [
    {
        "type": "tool",
        "name": "add_numbers",
        "args": [1, 2],
        "input_text": "1 and 2"
    },
    {
        "type": "tool",
        "name": "add_numbers",
        "args": ["PREVIOUS_RESULT", "PREVIOUS_RESULT"],
        "input_text": "result and result"
    }
]

print(f"Plan: Step 0: add 1 and 2")
print(f"      Step 1: add PREVIOUS_RESULT and PREVIOUS_RESULT")
print()

is_valid, error = validate_plan(plan_multi_prev, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if not is_valid and "Only one PREVIOUS_RESULT allowed per step" in error:
    print("✓ SUCCESS: Existing PREVIOUS_RESULT rule still enforced")
else:
    print("✗ FAILURE: PREVIOUS_RESULT count rule not working")

print()
print("="*80)
print("TEST COMPLETE")
print("="*80)
