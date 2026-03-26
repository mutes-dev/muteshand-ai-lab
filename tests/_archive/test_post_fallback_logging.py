"""
Test suite to demonstrate post-fallback argument count logging.

Shows when argument count mismatches are detected and logged.
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.argument_resolver import resolve_arguments
from core.parser import parse_tool_input

print("="*80)
print("POST-FALLBACK ARGUMENT COUNT LOGGING DEMONSTRATION")
print("="*80)

# Mock tool index for testing
MOCK_TOOL_INDEX = {
    "add_numbers": {"inputs": {"a": "int", "b": "int"}},  # expects 2
    "multiply_numbers": {"inputs": {"a": "int", "b": "int"}},  # expects 2
    "square": {"inputs": {"n": "int"}},  # expects 1
    "divide_numbers": {"inputs": {"a": "int", "b": "int"}},  # expects 2
}

def get_expected_arg_count(tool_name):
    """Mock version of get_expected_arg_count from manager."""
    if tool_name not in MOCK_TOOL_INDEX:
        return None
    
    inputs = MOCK_TOOL_INDEX[tool_name].get("inputs", {})
    
    if not inputs:
        return 0
    
    return len(inputs)

def simulate_manager_with_post_fallback_logging(step, results=[]):
    """
    Simulates the manager's args processing with post-fallback logging.
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
        
        expected_args = get_expected_arg_count(tool_name)
        print(f"[ARG CHECK POST-FALLBACK] Expected: {expected_args}, Actual: {len(args)}")
    
    print(f"\nFinal args: {args}")
    return args

print("\n" + "="*80)
print("SCENARIO 1: CORRECT ARG COUNT AFTER FALLBACK")
print("="*80)

print("\nGoal: add with invalid args, input_text has 2 values")
print("Expected: Fallback logs + arg count MATCH (2 == 2)")

step1 = {
    "type": "tool",
    "name": "add_numbers",
    "args": ["text", 3],
    "input_text": "5 and 7"
}

result1 = simulate_manager_with_post_fallback_logging(step1)

print("\n" + "="*80)
print("SCENARIO 2: INCORRECT ARG COUNT AFTER FALLBACK (TOO FEW)")
print("="*80)

print("\nGoal: multiply with invalid args, input_text has only 1 value")
print("Expected: Fallback logs + arg count MISMATCH (2 != 1)")

step2 = {
    "type": "tool",
    "name": "multiply_numbers",
    "args": ["PREVIOUS_RESULT"],
    "input_text": "multiply 5"
}

result2 = simulate_manager_with_post_fallback_logging(step2)

print("\n" + "="*80)
print("SCENARIO 3: INCORRECT ARG COUNT AFTER FALLBACK (TOO MANY)")
print("="*80)

print("\nGoal: square with invalid args, input_text has 3 values")
print("Expected: Fallback logs + arg count MISMATCH (1 != 3)")

step3 = {
    "type": "tool",
    "name": "square",
    "args": [],
    "input_text": "2 and 3 and 4"
}

result3 = simulate_manager_with_post_fallback_logging(step3)

print("\n" + "="*80)
print("SCENARIO 4: EMPTY INPUT TEXT - ZERO ARGS AFTER FALLBACK")
print("="*80)

print("\nGoal: divide with invalid args, empty input_text")
print("Expected: Fallback logs + arg count MISMATCH (2 != 0)")

step4 = {
    "type": "tool",
    "name": "divide_numbers",
    "args": ["text"],
    "input_text": ""
}

result4 = simulate_manager_with_post_fallback_logging(step4)

print("\n" + "="*80)
print("SCENARIO 5: FILLER WORDS ONLY - ZERO ARGS AFTER FALLBACK")
print("="*80)

print("\nGoal: add with invalid args, input_text has only filler words")
print("Expected: Fallback logs + arg count MISMATCH (2 != 0)")

step5 = {
    "type": "tool",
    "name": "add_numbers",
    "args": ["and", "of"],
    "input_text": "and the by with"
}

result5 = simulate_manager_with_post_fallback_logging(step5)

print("\n" + "="*80)
print("SCENARIO 6: CORRECT ARG COUNT - VALID ARGS (NO FALLBACK)")
print("="*80)

print("\nGoal: multiply with valid args")
print("Expected: NO fallback logs (args are valid)")

step6 = {
    "type": "tool",
    "name": "multiply_numbers",
    "args": [4, 5],
    "input_text": "4 by 5"
}

result6 = simulate_manager_with_post_fallback_logging(step6)

print("\n" + "="*80)
print("POST-FALLBACK LOGGING SUMMARY")
print("="*80)

print("""
WHEN POST-FALLBACK LOG APPEARS:
--------------------------------
✅ Only when fallback is triggered
✅ Always after args are resolved
✅ Shows expected vs actual count

LOG FORMAT:
-----------
[ARG CHECK POST-FALLBACK] Expected: <expected_count>, Actual: <actual_count>

DEBUGGING VALUE:
----------------
1. Visibility: See if fallback produced correct arg count
2. Diagnosis: Identify when input_text is insufficient
3. Traceability: Link resolution to validation
4. Early Warning: Detect issues before execution

COMMON MISMATCH SCENARIOS:
--------------------------
1. Input text has too few numeric values
   → Actual < Expected
   
2. Input text has too many numeric values
   → Actual > Expected
   
3. Input text has only filler words
   → Actual = 0
   
4. Input text is empty
   → Actual = 0

EXECUTION FLOW:
---------------
1. Invalid args detected
2. Fallback triggered
3. Tokens parsed from input_text
4. Args resolved from tokens
5. Expected count retrieved
6. POST-FALLBACK LOG APPEARS ← NEW
7. Execution continues (validation may catch later)

NO LOGIC CHANGES:
-----------------
✅ Detection logic unchanged
✅ Fallback logic unchanged
✅ Validation logic unchanged
✅ Execution flow unchanged
✅ Only print statement added
✅ No branching introduced
✅ No enforcement added
""")

print("\n" + "="*80)
print("END OF DEMONSTRATION")
print("="*80)
