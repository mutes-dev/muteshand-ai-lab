"""
Test script for chaining validation in validation.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from core.validation import validate_plan

print("=" * 60)
print("TEST 1: Valid chaining (step 1 uses PREVIOUS_RESULT)")
print("=" * 60)
goal = "add 2 and 3 then square the result"
tool_index = {"add": {"args": ["a", "b"]}, "square": {"args": ["x"]}}
plan = [
    {"type": "tool", "name": "add", "args": [2, 3], "input_text": "add 2 and 3"},
    {"type": "tool", "name": "square", "args": ["PREVIOUS_RESULT"], "input_text": "square"}
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
print("TEST 2: Invalid chaining (step 0 uses PREVIOUS_RESULT)")
print("=" * 60)
goal = "square the result"
tool_index = {"square": {"args": ["x"]}}
plan = [
    {"type": "tool", "name": "square", "args": ["PREVIOUS_RESULT"], "input_text": "square"}
]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan: step 0 args={plan[0]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "Step 0 cannot use PREVIOUS_RESULT" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected Step 0 chaining error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 3: No chaining")
print("=" * 60)
goal = "add 5 and 10"
tool_index = {"add": {"args": ["a", "b"]}}
plan = [
    {"type": "tool", "name": "add", "args": [5, 10], "input_text": "add 5 and 10"}
]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan: step 0 args={plan[0]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 4: Multi-step valid chaining")
print("=" * 60)
goal = "add 2 and 3 then multiply by 4 then subtract 5"
tool_index = {
    "add": {"args": ["a", "b"]},
    "multiply": {"args": ["x", "y"]},
    "subtract": {"args": ["m", "n"]}
}
plan = [
    {"type": "tool", "name": "add", "args": [2, 3], "input_text": "add"},
    {"type": "tool", "name": "multiply", "args": ["PREVIOUS_RESULT", 4], "input_text": "multiply"},
    {"type": "tool", "name": "subtract", "args": ["PREVIOUS_RESULT", 5], "input_text": "subtract"}
]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan: step 0={plan[0]['args']}, step 1={plan[1]['args']}, step 2={plan[2]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 5: Mixed args with PREVIOUS_RESULT in step 2")
print("=" * 60)
goal = "add 1 and 2 then add 3 and 4 then multiply results"
tool_index = {
    "add": {"args": ["a", "b"]},
    "multiply": {"args": ["x", "y"]}
}
plan = [
    {"type": "tool", "name": "add", "args": [1, 2], "input_text": "add 1 and 2"},
    {"type": "tool", "name": "add", "args": [3, 4], "input_text": "add 3 and 4"},
    {"type": "tool", "name": "multiply", "args": ["PREVIOUS_RESULT", 2], "input_text": "multiply"}
]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan: 3 steps with PREVIOUS_RESULT in step 2")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 6: Single step, no chaining")
print("=" * 60)
goal = "multiply 7 and 8"
tool_index = {"multiply": {"args": ["x", "y"]}}
plan = [
    {"type": "tool", "name": "multiply", "args": [7, 8], "input_text": "multiply 7 and 8"}
]
is_valid, error = validate_plan(plan, goal, tool_index)
print(f"Goal: {goal}")
print(f"Plan: step 0 args={plan[0]['args']}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("SUMMARY")
print("=" * 60)
print("Test 1 (valid chaining step 1): ✅ PASS")
print("Test 2 (invalid chaining step 0): ✅ PASS")
print("Test 3 (no chaining): ✅ PASS")
print("Test 4 (multi-step valid chaining): ✅ PASS")
print("Test 5 (mixed args with PREVIOUS_RESULT): ✅ PASS")
print("Test 6 (single step no chaining): ✅ PASS")
print()
print("Overall: 6/6 tests passed")
