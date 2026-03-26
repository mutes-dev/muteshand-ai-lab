"""
Test script to verify PREVIOUS_RESULT chaining validation rules
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
print("TEST: PREVIOUS_RESULT Chaining Validation")
print("="*80)
print()

# Test 1: PREVIOUS_RESULT in first step (INVALID)
print("TEST 1: PREVIOUS_RESULT in First Step (INVALID)")
print("-"*80)
plan_first_step = [
    {
        "type": "tool",
        "name": "multiply_numbers",
        "args": ["PREVIOUS_RESULT", 2],
        "input_text": "result of previous step and 2"
    }
]

print(f"Plan: {plan_first_step}")
print(f"Step 0 uses PREVIOUS_RESULT")
print()

is_valid, error = validate_plan(plan_first_step, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if not is_valid and "Step 0 cannot use PREVIOUS_RESULT" in error:
    print("✓ SUCCESS: Validation correctly rejected PREVIOUS_RESULT in first step")
else:
    print("✗ FAILURE: Validation did not reject PREVIOUS_RESULT in first step")

print()

# Test 2: Multiple PREVIOUS_RESULT in one step (INVALID)
print("TEST 2: Multiple PREVIOUS_RESULT in One Step (INVALID)")
print("-"*80)
plan_multiple = [
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

print(f"Plan: {plan_multiple}")
print(f"Step 1 uses PREVIOUS_RESULT twice")
print()

is_valid, error = validate_plan(plan_multiple, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if not is_valid and "Only one PREVIOUS_RESULT allowed per step" in error:
    print("✓ SUCCESS: Validation correctly rejected multiple PREVIOUS_RESULT")
else:
    print("✗ FAILURE: Validation did not reject multiple PREVIOUS_RESULT")

print()

# Test 3: Valid single-step chaining (VALID)
print("TEST 3: Valid Single-Step Chaining (VALID)")
print("-"*80)
plan_valid_single = [
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

print(f"Plan: {plan_valid_single}")
print(f"Step 0: add 1 and 2")
print(f"Step 1: multiply PREVIOUS_RESULT by 2")
print()

is_valid, error = validate_plan(plan_valid_single, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if is_valid:
    print("✓ SUCCESS: Validation correctly accepted valid chaining")
else:
    print(f"✗ FAILURE: Validation rejected valid chaining: {error}")

print()

# Test 4: Valid multi-step chaining (VALID)
print("TEST 4: Valid Multi-Step Chaining (VALID)")
print("-"*80)
plan_valid_multi = [
    {
        "type": "tool",
        "name": "add_numbers",
        "args": [2, 3],
        "input_text": "2 and 3"
    },
    {
        "type": "tool",
        "name": "multiply_numbers",
        "args": ["PREVIOUS_RESULT", 4],
        "input_text": "result and 4"
    },
    {
        "type": "tool",
        "name": "add_numbers",
        "args": ["PREVIOUS_RESULT", 10],
        "input_text": "result and 10"
    }
]

print(f"Plan: {plan_valid_multi}")
print(f"Step 0: add 2 and 3")
print(f"Step 1: multiply PREVIOUS_RESULT by 4")
print(f"Step 2: add PREVIOUS_RESULT and 10")
print()

is_valid, error = validate_plan(plan_valid_multi, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if is_valid:
    print("✓ SUCCESS: Validation correctly accepted multi-step chaining")
else:
    print(f"✗ FAILURE: Validation rejected multi-step chaining: {error}")

print()

# Test 5: PREVIOUS_RESULT in second arg position (VALID)
print("TEST 5: PREVIOUS_RESULT in Second Arg Position (VALID)")
print("-"*80)
plan_second_arg = [
    {
        "type": "tool",
        "name": "add_numbers",
        "args": [5, 7],
        "input_text": "5 and 7"
    },
    {
        "type": "tool",
        "name": "multiply_numbers",
        "args": [3, "PREVIOUS_RESULT"],
        "input_text": "3 and result"
    }
]

print(f"Plan: {plan_second_arg}")
print(f"Step 0: add 5 and 7")
print(f"Step 1: multiply 3 by PREVIOUS_RESULT")
print()

is_valid, error = validate_plan(plan_second_arg, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if is_valid:
    print("✓ SUCCESS: Validation correctly accepted PREVIOUS_RESULT in second position")
else:
    print(f"✗ FAILURE: Validation rejected valid second-position chaining: {error}")

print()
print("="*80)
print("TEST COMPLETE")
print("="*80)
