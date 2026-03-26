"""
Test script to verify planner can generate plans with unknown tools after validation removal.
"""

import sys
import os
import json

# Add paths
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from core.planner import _validate_plan

# Test data - simulate a plan with unknown tool
tool_names = ['add_numbers', 'subtract_numbers', 'multiply_numbers']

unknown_tool_plan = [
    {
        "type": "tool",
        "name": "completely_unknown_tool_xyz",
        "args": [5, 10],
        "input_text": "5 and 10"
    }
]

print("="*80)
print("TEST: Planner Internal Validation (After Modification)")
print("="*80)
print()

print("STEP 1: Test planner's internal _validate_plan with unknown tool")
print("-"*80)
print(f"Plan: {json.dumps(unknown_tool_plan, indent=2)}")
print(f"Available tools: {tool_names}")
print()

is_valid, error = _validate_plan(unknown_tool_plan, tool_names)

print(f"Planner Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if is_valid:
    print("✓ SUCCESS: Planner's internal validation now accepts unknown tools")
    print("✓ Plan will be returned to manager.py")
    print("✓ Validation layer (validation.py) will enforce tool existence")
else:
    print("✗ FAILURE: Planner still rejecting unknown tools")
    print(f"✗ Error: {error}")

print()
print("="*80)
print("TEST COMPLETE")
print("="*80)
