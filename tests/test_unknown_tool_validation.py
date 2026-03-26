"""
Test script to verify unknown tool validation flow.
"""

import sys
import os

# Add paths
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MANAGER_PATH = os.path.join(PROJECT_ROOT, "projects", "manager")
CORE_PATH = os.path.join(PROJECT_ROOT, "core")

sys.path.insert(0, MANAGER_PATH)
sys.path.insert(0, PROJECT_ROOT)

from core.planner import generate_structured_plan
from core.validation import validate_plan

# Test data
tool_names = ['add_numbers', 'subtract_numbers', 'multiply_numbers']
tool_index = {
    'add_numbers': {'inputs': {'a': 'number', 'b': 'number'}},
    'subtract_numbers': {'inputs': {'a': 'number', 'b': 'number'}},
    'multiply_numbers': {'inputs': {'a': 'number', 'b': 'number'}},
}

# Manually create a plan with unknown tool (simulating what LLM might generate)
unknown_tool_plan = [
    {
        "type": "tool",
        "name": "completely_unknown_tool_xyz",
        "args": [5, 10],
        "input_text": "5 and 10"
    }
]

print("="*80)
print("TEST: Unknown Tool Validation Flow")
print("="*80)
print()

print("STEP 1: Validate plan with unknown tool using validation.py")
print("-"*80)
print(f"Plan: {unknown_tool_plan}")
print()

is_valid, error = validate_plan(unknown_tool_plan, tool_index)

print(f"Validation Result: is_valid={is_valid}")
print(f"Error Message: {error}")
print()

if not is_valid:
    print("✓ SUCCESS: Validation layer correctly rejected unknown tool")
    print(f"✓ Error message: {error}")
else:
    print("✗ FAILURE: Validation layer did not reject unknown tool")

print()
print("="*80)
print("TEST COMPLETE")
print("="*80)
