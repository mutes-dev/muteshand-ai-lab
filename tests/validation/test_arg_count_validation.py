"""
Test script to verify argument count validation in validation.py
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
print("TEST: Argument Count Validation")
print("="*80)
print()

# Test 1: Missing arguments (0 args, expects 2)
print("TEST 1: Missing Arguments")
print("-"*80)
plan_missing_args = [
    {
        "type": "tool",
        "name": "add_numbers",
        "args": [],
        "input_text": ""
    }
]

print(f"Plan: {plan_missing_args}")
print(f"Expected args: 2")
print(f"Actual args: 0")
print()

is_valid, error = validate_plan(plan_missing_args, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if not is_valid and "expected 2 args but got 0" in error:
    print("✓ SUCCESS: Validation correctly rejected plan with missing arguments")
else:
    print("✗ FAILURE: Validation did not reject missing arguments")

print()

# Test 2: Too few arguments (1 arg, expects 2)
print("TEST 2: Too Few Arguments")
print("-"*80)
plan_too_few = [
    {
        "type": "tool",
        "name": "add_numbers",
        "args": [5],
        "input_text": "5"
    }
]

print(f"Plan: {plan_too_few}")
print(f"Expected args: 2")
print(f"Actual args: 1")
print()

is_valid, error = validate_plan(plan_too_few, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if not is_valid and "expected 2 args but got 1" in error:
    print("✓ SUCCESS: Validation correctly rejected plan with too few arguments")
else:
    print("✗ FAILURE: Validation did not reject too few arguments")

print()

# Test 3: Too many arguments (3 args, expects 2)
print("TEST 3: Too Many Arguments")
print("-"*80)
plan_too_many = [
    {
        "type": "tool",
        "name": "add_numbers",
        "args": [1, 2, 3],
        "input_text": "1 2 3"
    }
]

print(f"Plan: {plan_too_many}")
print(f"Expected args: 2")
print(f"Actual args: 3")
print()

is_valid, error = validate_plan(plan_too_many, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if not is_valid and "expected 2 args but got 3" in error:
    print("✓ SUCCESS: Validation correctly rejected plan with too many arguments")
else:
    print("✗ FAILURE: Validation did not reject too many arguments")

print()

# Test 4: Correct argument count (2 args, expects 2)
print("TEST 4: Correct Argument Count")
print("-"*80)
plan_correct = [
    {
        "type": "tool",
        "name": "add_numbers",
        "args": [1, 2],
        "input_text": "1 and 2"
    }
]

print(f"Plan: {plan_correct}")
print(f"Expected args: 2")
print(f"Actual args: 2")
print()

is_valid, error = validate_plan(plan_correct, tool_index)
print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if is_valid:
    print("✓ SUCCESS: Validation correctly accepted plan with correct argument count")
else:
    print(f"✗ FAILURE: Validation rejected valid plan: {error}")

print()
print("="*80)
print("TEST COMPLETE")
print("="*80)
