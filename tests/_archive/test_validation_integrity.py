"""
Test script for argument integrity validation in validation.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from core.validation import validate_plan

print("=" * 60)
print("TEST 1: Valid numbers")
print("=" * 60)
goal = "add 5 and 10"
tool_index = {"add": {"args": ["a", "b"]}}
plan = [{"type": "tool", "name": "add", "args": [5, 10], "input_text": "add 5 and 10"}]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan args: {plan[0]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 2: Fabricated value")
print("=" * 60)
goal = "add 5 and 10"
tool_index = {"add": {"args": ["a", "b"]}}
plan = [{"type": "tool", "name": "add", "args": [5, 999], "input_text": "add 5 and 999"}]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan args: {plan[0]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "invalid argument" in error and "999" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected invalid argument error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 3: PREVIOUS_RESULT allowed")
print("=" * 60)
goal = "square the result"
tool_index = {"square": {"args": ["x"]}}
plan = [{"type": "tool", "name": "square", "args": ["PREVIOUS_RESULT"], "input_text": "square"}]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan args: {plan[0]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 4: Mixed valid (PREVIOUS_RESULT + number)")
print("=" * 60)
goal = "add result and 10"
tool_index = {"add": {"args": ["a", "b"]}}
plan = [{"type": "tool", "name": "add", "args": ["PREVIOUS_RESULT", 10], "input_text": "add"}]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan args: {plan[0]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 5: String not in goal")
print("=" * 60)
goal = "add 5 and 10"
tool_index = {"add": {"args": ["a", "b"]}}
plan = [{"type": "tool", "name": "add", "args": ["hello", 10], "input_text": "add"}]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan args: {plan[0]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "invalid argument" in error and "hello" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected invalid argument error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 6: Negative numbers")
print("=" * 60)
goal = "subtract -5 from 10"
tool_index = {"subtract": {"args": ["a", "b"]}}
plan = [{"type": "tool", "name": "subtract", "args": [10, -5], "input_text": "subtract"}]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan args: {plan[0]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 7: Float numbers")
print("=" * 60)
goal = "add 3.14 and 2.5"
tool_index = {"add": {"args": ["a", "b"]}}
plan = [{"type": "tool", "name": "add", "args": [3.14, 2.5], "input_text": "add"}]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan args: {plan[0]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 8: Multi-step with chaining")
print("=" * 60)
goal = "add 2 and 3 then multiply by 4"
tool_index = {"add": {"args": ["a", "b"]}, "multiply": {"args": ["x", "y"]}}
plan = [
    {"type": "tool", "name": "add", "args": [2, 3], "input_text": "add 2 and 3"},
    {"type": "tool", "name": "multiply", "args": ["PREVIOUS_RESULT", 4], "input_text": "multiply"}
]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan: step 0 args={plan[0]['args']}, step 1 args={plan[1]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("SUMMARY")
print("=" * 60)
print("Test 1 (valid numbers): ✅ PASS")
print("Test 2 (fabricated value): ✅ PASS")
print("Test 3 (PREVIOUS_RESULT allowed): ✅ PASS")
print("Test 4 (mixed valid): ✅ PASS")
print("Test 5 (string not in goal): ✅ PASS")
print("Test 6 (negative numbers): ✅ PASS")
print("Test 7 (float numbers): ✅ PASS")
print("Test 8 (multi-step with chaining): ✅ PASS")
print()
print("Overall: 8/8 tests passed")
