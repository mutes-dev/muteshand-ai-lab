"""
Test suite to demonstrate complete argument fallback visibility.

Shows all logging scenarios:
- Fallback triggered with correct count
- Fallback triggered with mismatch + warning
- Fallback skipped (valid args)
"""

import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from core.argument_resolver import resolve_arguments
from core.parser import parse_tool_input

print("="*80)
print("COMPLETE ARGUMENT FALLBACK VISIBILITY DEMONSTRATION")
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

def simulate_complete_fallback_logging(step, results=[]):
    """
    Simulates the manager's complete args processing with full logging.
    This mirrors the EXACT logic with all logging added to manager.py.
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
        
        if len(args) != expected_args:
            print(f"[ARG WARNING] Argument count mismatch for {tool_name} — execution may fail")
    else:
        print(f"[ARG FALLBACK] Skipped — args already valid: {args}")
    
    print(f"\nFinal args: {args}")
    return args

print("\n" + "="*80)
print("TEST 1: VALID ARGS - FALLBACK SKIPPED")
print("="*80)

print("\nGoal: add 2 and 3")
print("Expected: Fallback skipped log")

step1 = {
    "type": "tool",
    "name": "add_numbers",
    "args": [2, 3],
    "input_text": "2 and 3"
}

result1 = simulate_complete_fallback_logging(step1)

print("\n" + "="*80)
print("TEST 2: INVALID ARGS - FALLBACK TRIGGERED - COUNT MATCH")
print("="*80)

print("\nGoal: multiply with invalid args, correct count after fallback")
print("Expected: Fallback logs + count match + NO warning")

step2 = {
    "type": "tool",
    "name": "multiply_numbers",
    "args": ["text", 3],
    "input_text": "4 by 5"
}

result2 = simulate_complete_fallback_logging(step2)

print("\n" + "="*80)
print("TEST 3: INVALID ARGS - FALLBACK TRIGGERED - COUNT MISMATCH (TOO FEW)")
print("="*80)

print("\nGoal: add with invalid args, too few after fallback")
print("Expected: Fallback logs + count mismatch + WARNING")

step3 = {
    "type": "tool",
    "name": "add_numbers",
    "args": ["PREVIOUS_RESULT"],
    "input_text": "add 5"
}

result3 = simulate_complete_fallback_logging(step3)

print("\n" + "="*80)
print("TEST 4: INVALID ARGS - FALLBACK TRIGGERED - COUNT MISMATCH (TOO MANY)")
print("="*80)

print("\nGoal: square with invalid args, too many after fallback")
print("Expected: Fallback logs + count mismatch + WARNING")

step4 = {
    "type": "tool",
    "name": "square",
    "args": [],
    "input_text": "2 and 3 and 4"
}

result4 = simulate_complete_fallback_logging(step4)

print("\n" + "="*80)
print("TEST 5: INVALID ARGS - FALLBACK TRIGGERED - ZERO ARGS AFTER")
print("="*80)

print("\nGoal: divide with invalid args, empty input_text")
print("Expected: Fallback logs + count mismatch + WARNING")

step5 = {
    "type": "tool",
    "name": "divide_numbers",
    "args": ["text"],
    "input_text": ""
}

result5 = simulate_complete_fallback_logging(step5)

print("\n" + "="*80)
print("TEST 6: VALID FLOAT ARGS - FALLBACK SKIPPED")
print("="*80)

print("\nGoal: divide 10.5 by 2.5")
print("Expected: Fallback skipped log")

step6 = {
    "type": "tool",
    "name": "divide_numbers",
    "args": [10.5, 2.5],
    "input_text": "10.5 by 2.5"
}

result6 = simulate_complete_fallback_logging(step6)

print("\n" + "="*80)
print("TEST 7: VALID NEGATIVE ARGS - FALLBACK SKIPPED")
print("="*80)

print("\nGoal: add -5 and 3")
print("Expected: Fallback skipped log")

step7 = {
    "type": "tool",
    "name": "add_numbers",
    "args": [-5, 3],
    "input_text": "-5 and 3"
}

result7 = simulate_complete_fallback_logging(step7)

print("\n" + "="*80)
print("COMPLETE VISIBILITY SUMMARY")
print("="*80)

print("""
FULL LOGGING COVERAGE:
----------------------

1. FALLBACK TRIGGERED (INVALID ARGS)
   ✅ Tool name
   ✅ Original args
   ✅ Parsed tokens
   ✅ Resolved args
   ✅ Expected vs actual count
   ✅ Warning on mismatch

2. FALLBACK SKIPPED (VALID ARGS)
   ✅ Confirmation message
   ✅ Args shown

LOG SEQUENCE (FALLBACK TRIGGERED):
-----------------------------------
[ARG FALLBACK] Triggered for tool: <tool_name>
[ARG FALLBACK] Original args: <original_args>
[ARG FALLBACK] Tokens: <parsed_tokens>
[ARG FALLBACK] Resolved args: <resolved_args>
[ARG CHECK POST-FALLBACK] Expected: <expected>, Actual: <actual>
[ARG WARNING] Argument count mismatch for <tool_name> — execution may fail
                                                         ↑ only if mismatch

LOG SEQUENCE (FALLBACK SKIPPED):
---------------------------------
[ARG FALLBACK] Skipped — args already valid: <args>

DEBUGGING VALUE:
----------------
✅ Full traceability: original → tokens → resolved
✅ Early warning: mismatch detected before execution
✅ Clear distinction: triggered vs skipped
✅ Visibility: see exactly what resolver produces
✅ Diagnosis: identify insufficient input_text
✅ Verification: confirm valid args pass through

WHEN EACH LOG APPEARS:
-----------------------

[ARG FALLBACK] Triggered
→ When args is empty OR contains non-numeric values

[ARG FALLBACK] Skipped
→ When args contains only int/float values

[ARG WARNING] Argument count mismatch
→ When resolved arg count ≠ expected count

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
   f. Get expected count
   g. Log expected vs actual
   h. IF mismatch: log warning
   ELSE:
   a. Log skipped + valid args
4. Execution continues (no interruption)

NO LOGIC CHANGES:
-----------------
✅ Detection logic unchanged
✅ Fallback logic unchanged
✅ Resolution logic unchanged
✅ Validation logic unchanged
✅ Execution flow unchanged
✅ Only print statements added
✅ No branching introduced
✅ No enforcement added
✅ Non-blocking warnings only

COMPLETE VISIBILITY ACHIEVED:
------------------------------
✅ Know when fallback triggers
✅ Know when fallback is skipped
✅ See what resolver produces
✅ See if args match expected count
✅ Get early warning before failure
""")

print("\n" + "="*80)
print("END OF DEMONSTRATION")
print("="*80)
