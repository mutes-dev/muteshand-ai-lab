import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from core.planner import generate_structured_plan
from core.parser import parse_tool_input
from core.argument_resolver import resolve_arguments
from core.validation import validate_plan
import json

tool_names = ['add_numbers', 'subtract_numbers', 'multiply_numbers', 'divide_numbers']
tool_index = {
    'add_numbers': {'inputs': ['a', 'b']},
    'subtract_numbers': {'inputs': ['a', 'b']},
    'multiply_numbers': {'inputs': ['a', 'b']},
    'divide_numbers': {'inputs': ['a', 'b']}
}

# Test "sum of 2 and 3"
goal = "sum of 2 and 3"
print(f"Testing: {goal}")
print()

# Step 1: Planner
plan = generate_structured_plan(goal, tool_names)
print(f"1. Planner output:")
print(json.dumps(plan, indent=2))
print()

# Step 2: Resolver
if isinstance(plan, list):
    for step in plan:
        if step.get("type") == "tool":
            input_text = step.get("input_text", "")
            print(f"2. Resolving: {input_text}")
            
            tokens = parse_tool_input(input_text)
            print(f"   Tokens: {tokens}")
            
            resolved_args = resolve_arguments(step["name"], tokens, input_text)
            print(f"   Resolved args: {resolved_args}")
            
            step["args"] = resolved_args if resolved_args else []
    
    print()
    print(f"3. Plan after resolver:")
    print(json.dumps(plan, indent=2))
    print()
    
    # Step 3: Validation
    result = validate_plan(plan, tool_index)
    print(f"4. Validation result: {result}")
