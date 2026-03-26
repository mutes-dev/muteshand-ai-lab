"""
Test suite to demonstrate argument fallback logging behavior.

Shows when logs appear and what they contain.
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.argument_resolver import resolve_arguments
from core.parser import parse_tool_input

print("="*80)
print("ARGUMENT FALLBACK LOGGING DEMONSTRATION")
print("="*80)

def simulate_manager_with_logging(step, results=[]):
    """
    Simulates the manager's args processing with logging.
    This mirrors the EXACT logic with logging added to manager.py.
    """
    tool_name = step["name"]
    args = step.get("args", [])
    
    print(f"\n{'='*80}")
    print(f"PROCESSING: {tool_name}")
    print(f"{'='*80}")
    print(f"Step args:    {args}")
    print(f"Input text:   {step.get('input_text', '')}")
    print()
    
    # Detect invalid args (EXACT LOGIC FROM MANAGER)
    invalid_args = (
        not args or
        any(not isinstance(a, (int, float)) for a in args)
    )
    
    if invalid_args:
        print(f"[ARG FALLBACK] Triggered for tool: {tool_name}")
        print(f"[ARG FALLBACK] Original args: {args}")
        
        tokens = parse_tool_input(step.get("input_text", ""))
        print(f"[ARG FALLBACK] Tokens: {tokens}")
        
        args = resolve_arguments(tool_name, tokens)
        print(f"[ARG FALLBACK] Resolved args: {args}")
    
    print(f"\nFinal args: {args}")
    return args

print("\n" + "="*80)
print("SCENARIO 1: VALID ARGS - NO LOGS")
print("="*80)

print("\nGoal: add 2 and 3")
print("Expected: NO fallback logs (args are valid)")

step1 = {
    "type": "tool",
    "name": "add_numbers",
    "args": [2, 3],
    "input_text": "2 and 3"
}

result1 = simulate_manager_with_logging(step1)

print("\n" + "="*80)
print("SCENARIO 2: INVALID ARGS (STRING) - LOGS APPEAR")
print("="*80)

print("\nGoal: multiply with invalid args")
print("Expected: Fallback logs MUST appear")

step2 = {
    "type": "tool",
    "name": "multiply_numbers",
    "args": ["text", 3],
    "input_text": "4 by 5"
}

result2 = simulate_manager_with_logging(step2)

print("\n" + "="*80)
print("SCENARIO 3: EMPTY ARGS - LOGS APPEAR")
print("="*80)

print("\nGoal: divide with empty args")
print("Expected: Fallback logs MUST appear")

step3 = {
    "type": "tool",
    "name": "divide_numbers",
    "args": [],
    "input_text": "10 by 2"
}

result3 = simulate_manager_with_logging(step3)

print("\n" + "="*80)
print("SCENARIO 4: PREVIOUS_RESULT TOKEN - LOGS APPEAR")
print("="*80)

print("\nGoal: add with PREVIOUS_RESULT token")
print("Expected: Fallback logs MUST appear")

step4 = {
    "type": "tool",
    "name": "add_numbers",
    "args": ["PREVIOUS_RESULT"],
    "input_text": "7 and 8"
}

result4 = simulate_manager_with_logging(step4)

print("\n" + "="*80)
print("SCENARIO 5: VALID FLOAT ARGS - NO LOGS")
print("="*80)

print("\nGoal: divide 10.5 by 2.5")
print("Expected: NO fallback logs (args are valid)")

step5 = {
    "type": "tool",
    "name": "divide_numbers",
    "args": [10.5, 2.5],
    "input_text": "10.5 by 2.5"
}

result5 = simulate_manager_with_logging(step5)

print("\n" + "="*80)
print("LOG BEHAVIOR SUMMARY")
print("="*80)

print("""
WHEN LOGS APPEAR:
-----------------
✅ Args is empty list []
✅ Args contains string values
✅ Args contains PREVIOUS_RESULT token
✅ Args contains any non-numeric value

WHEN LOGS DO NOT APPEAR:
-------------------------
✅ Args contains only int values
✅ Args contains only float values
✅ Args contains mix of int and float

LOG FORMAT:
-----------
[ARG FALLBACK] Triggered for tool: <tool_name>
[ARG FALLBACK] Original args: <original_args_list>
[ARG FALLBACK] Tokens: <parsed_tokens_list>
[ARG FALLBACK] Resolved args: <resolved_numeric_args>

DEBUGGING VALUE:
----------------
1. Visibility: See when fallback is triggered
2. Traceability: Track original → tokens → resolved
3. Verification: Confirm resolver working correctly
4. Diagnosis: Identify invalid args sources

EXECUTION FLOW:
---------------
1. Args extracted from step
2. Invalid args detection
3. IF invalid:
   a. Log trigger + original args
   b. Parse input_text to tokens
   c. Log tokens
   d. Resolve tokens to numeric args
   e. Log resolved args
4. Execution continues with final args

NO LOGIC CHANGES:
-----------------
✅ Detection logic unchanged
✅ Parser logic unchanged
✅ Resolver logic unchanged
✅ Execution flow unchanged
✅ Only print statements added
""")

print("\n" + "="*80)
print("END OF DEMONSTRATION")
print("="*80)
