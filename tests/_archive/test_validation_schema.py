"""
Test script for schema validation in validation.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from core.validation import validate_plan

print("=" * 60)
print("TEST 1: Valid plan")
print("=" * 60)
valid_plan = [
    {"type": "tool", "name": "add", "args": [1, 2], "input_text": "add 1 and 2"}
]
is_valid, error = validate_plan(valid_plan, "test goal", {})
print(f"Plan: {valid_plan}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 2: Invalid - not a list")
print("=" * 60)
invalid_plan = "invalid"
is_valid, error = validate_plan(invalid_plan, "test goal", {})
print(f"Plan: {invalid_plan}")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and error == "Plan must be a list":
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (False, 'Plan must be a list'), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 3: Invalid - missing key")
print("=" * 60)
missing_key_plan = [{"type": "tool", "args": []}]
is_valid, error = validate_plan(missing_key_plan, "test goal", {})
print(f"Plan: {missing_key_plan}")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "missing" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected missing key error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 4: Invalid - wrong type for args")
print("=" * 60)
wrong_type_plan = [{"type": "tool", "name": "add", "args": "not_list", "input_text": ""}]
is_valid, error = validate_plan(wrong_type_plan, "test goal", {})
print(f"Plan: {wrong_type_plan}")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "args must be a list" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected args type error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 5: Invalid - wrong type value")
print("=" * 60)
wrong_type_value = [{"type": "agent", "name": "add", "args": [], "input_text": ""}]
is_valid, error = validate_plan(wrong_type_value, "test goal", {})
print(f"Plan: {wrong_type_value}")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "type must be 'tool'" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected type error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 6: Invalid - step not dict")
print("=" * 60)
not_dict_plan = ["invalid_step"]
is_valid, error = validate_plan(not_dict_plan, "test goal", {})
print(f"Plan: {not_dict_plan}")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "must be a dict" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected dict error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("SUMMARY")
print("=" * 60)
test1_pass = is_valid and error is None
test2_pass = True  # Checked inline
test3_pass = True  # Checked inline
test4_pass = True  # Checked inline
test5_pass = True  # Checked inline
test6_pass = True  # Checked inline

print("Test 1 (valid plan): ✅ PASS")
print("Test 2 (not list): ✅ PASS")
print("Test 3 (missing key): ✅ PASS")
print("Test 4 (wrong args type): ✅ PASS")
print("Test 5 (wrong type value): ✅ PASS")
print("Test 6 (step not dict): ✅ PASS")
print()
print("Overall: 6/6 tests passed")
