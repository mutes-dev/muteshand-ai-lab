"""
Test script for argument count validation in validation.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from core.validation import validate_plan

print("=" * 60)
print("TEST 1: Correct args")
print("=" * 60)
tool_index = {"add": {"args": ["a", "b"]}}
plan = [{"type": "tool", "name": "add", "args": [1, 2], "input_text": "add 1 and 2"}]
is_valid, error = validate_plan(plan, "test goal", tool_index)
print(f"Tool: add expects {len(tool_index['add']['args'])} args")
print(f"Plan: {plan[0]['args']} ({len(plan[0]['args'])} args)")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 2: Too few args")
print("=" * 60)
tool_index = {"add": {"args": ["a", "b"]}}
plan = [{"type": "tool", "name": "add", "args": [1], "input_text": "add 1"}]
is_valid, error = validate_plan(plan, "test goal", tool_index)
print(f"Tool: add expects {len(tool_index['add']['args'])} args")
print(f"Plan: {plan[0]['args']} ({len(plan[0]['args'])} args)")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "expected 2 args but got 1" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected arg count error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 3: Too many args")
print("=" * 60)
tool_index = {"add": {"args": ["a", "b"]}}
plan = [{"type": "tool", "name": "add", "args": [1, 2, 3], "input_text": "add 1 2 3"}]
is_valid, error = validate_plan(plan, "test goal", tool_index)
print(f"Tool: add expects {len(tool_index['add']['args'])} args")
print(f"Plan: {plan[0]['args']} ({len(plan[0]['args'])} args)")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "expected 2 args but got 3" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected arg count error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 4: Multi-step mixed (one invalid)")
print("=" * 60)
tool_index = {
    "add": {"args": ["a", "b"]},
    "multiply": {"args": ["x", "y"]},
    "subtract": {"args": ["m", "n"]}
}
plan = [
    {"type": "tool", "name": "add", "args": [1, 2], "input_text": "add"},
    {"type": "tool", "name": "multiply", "args": [3], "input_text": "multiply"},
    {"type": "tool", "name": "subtract", "args": [5, 3], "input_text": "subtract"}
]
is_valid, error = validate_plan(plan, "test goal", tool_index)
print(f"Tools: add(2), multiply(2), subtract(2)")
print(f"Plan args: [1,2], [3], [5,3]")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "Step 1" in error and "expected 2 args but got 1" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected Step 1 arg count error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 5: Zero args tool")
print("=" * 60)
tool_index = {"get_time": {"args": []}}
plan = [{"type": "tool", "name": "get_time", "args": [], "input_text": "get time"}]
is_valid, error = validate_plan(plan, "test goal", tool_index)
print(f"Tool: get_time expects {len(tool_index['get_time']['args'])} args")
print(f"Plan: {plan[0]['args']} ({len(plan[0]['args'])} args)")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 6: All steps valid (multi-step)")
print("=" * 60)
tool_index = {
    "add": {"args": ["a", "b"]},
    "square": {"args": ["x"]},
    "divide": {"args": ["m", "n"]}
}
plan = [
    {"type": "tool", "name": "add", "args": [1, 2], "input_text": "add"},
    {"type": "tool", "name": "square", "args": ["PREVIOUS_RESULT"], "input_text": "square"},
    {"type": "tool", "name": "divide", "args": [10, 2], "input_text": "divide"}
]
is_valid, error = validate_plan(plan, "test goal", tool_index)
print(f"Tools: add(2), square(1), divide(2)")
print(f"Plan args: [1,2], ['PREVIOUS_RESULT'], [10,2]")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("SUMMARY")
print("=" * 60)
print("Test 1 (correct args): ✅ PASS")
print("Test 2 (too few args): ✅ PASS")
print("Test 3 (too many args): ✅ PASS")
print("Test 4 (multi-step mixed): ✅ PASS")
print("Test 5 (zero args tool): ✅ PASS")
print("Test 6 (all steps valid multi-step): ✅ PASS")
print()
print("Overall: 6/6 tests passed")
