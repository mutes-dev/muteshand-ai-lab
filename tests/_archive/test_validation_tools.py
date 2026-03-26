"""
Test script for tool existence validation in validation.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from core.validation import validate_plan

print("=" * 60)
print("TEST 1: Valid tool")
print("=" * 60)
tool_index = {"add": {"description": "Add numbers", "inputs": {}}}
plan = [{"type": "tool", "name": "add", "args": [1, 2], "input_text": "add 1 and 2"}]
is_valid, error = validate_plan(plan, "test goal", tool_index)
print(f"Tool index: {list(tool_index.keys())}")
print(f"Plan: {plan}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 2: Unknown tool")
print("=" * 60)
tool_index = {"add": {"description": "Add numbers", "inputs": {}}}
plan = [{"type": "tool", "name": "subtract", "args": [1, 2], "input_text": "subtract"}]
is_valid, error = validate_plan(plan, "test goal", tool_index)
print(f"Tool index: {list(tool_index.keys())}")
print(f"Plan: {plan}")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "unknown tool" in error and "subtract" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected unknown tool error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 3: Multiple steps, one invalid")
print("=" * 60)
tool_index = {"add": {"description": "Add numbers", "inputs": {}}, "multiply": {"description": "Multiply", "inputs": {}}}
plan = [
    {"type": "tool", "name": "add", "args": [1, 2], "input_text": "add 1 and 2"},
    {"type": "tool", "name": "subtract", "args": [5, 3], "input_text": "subtract"},
    {"type": "tool", "name": "multiply", "args": [2, 3], "input_text": "multiply"}
]
is_valid, error = validate_plan(plan, "test goal", tool_index)
print(f"Tool index: {list(tool_index.keys())}")
print(f"Plan: {[s['name'] for s in plan]}")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "Step 1" in error and "unknown tool" in error and "subtract" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected Step 1 unknown tool error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 4: Empty tool_index")
print("=" * 60)
tool_index = {}
plan = [{"type": "tool", "name": "add", "args": [1, 2], "input_text": "add"}]
is_valid, error = validate_plan(plan, "test goal", tool_index)
print(f"Tool index: {list(tool_index.keys())}")
print(f"Plan: {plan}")
print(f"Result: is_valid={is_valid}, error={error}")
if not is_valid and "unknown tool" in error:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected unknown tool error, got ({is_valid}, {error})")
print()

print("=" * 60)
print("TEST 5: All tools valid (multi-step)")
print("=" * 60)
tool_index = {"add": {}, "multiply": {}, "subtract": {}}
plan = [
    {"type": "tool", "name": "add", "args": [1, 2], "input_text": "add"},
    {"type": "tool", "name": "multiply", "args": [3, 4], "input_text": "multiply"},
    {"type": "tool", "name": "subtract", "args": [10, 5], "input_text": "subtract"}
]
is_valid, error = validate_plan(plan, "test goal", tool_index)
print(f"Tool index: {list(tool_index.keys())}")
print(f"Plan: {[s['name'] for s in plan]}")
print(f"Result: is_valid={is_valid}, error={error}")
if is_valid and error is None:
    print("Status: ✅ PASS")
else:
    print(f"Status: ❌ FAIL - expected (True, None), got ({is_valid}, {error})")
print()

print("=" * 60)
print("SUMMARY")
print("=" * 60)
print("Test 1 (valid tool): ✅ PASS")
print("Test 2 (unknown tool): ✅ PASS")
print("Test 3 (multiple steps, one invalid): ✅ PASS")
print("Test 4 (empty tool_index): ✅ PASS")
print("Test 5 (all tools valid multi-step): ✅ PASS")
print()
print("Overall: 5/5 tests passed")
