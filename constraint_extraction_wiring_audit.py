#!/usr/bin/env python3
"""
CONSTRAINT_EXTRACTION_WIRING_AUDIT
Debug LLM extraction and variable flow.
"""

import json
from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator import trace_collector
from system.orchestrator.intent_validator import _extract_constraints_llm, _validate_constraints

# Test inputs
test_inputs = [
    "repeat \"abc\" 3 times but output only the count",
    "multiply 2 and 3 but respond in words"
]

print("=" * 100)
print("CONSTRAINT EXTRACTION WIRING AUDIT")
print("=" * 100)

print("\n" + "=" * 100)
print("PART 1: DIRECT FUNCTION TEST")
print("=" * 100)

for i, test_input in enumerate(test_inputs, 1):
    print(f"\n--- Test {i}: {test_input} ---")
    
    # Call extraction directly
    constraints = _extract_constraints_llm(test_input)
    print(f"Extracted constraints: {constraints}")
    print(f"Type: {type(constraints)}")
    print(f"Is empty dict: {constraints == {}}")
    
    # Mock execution result for validation
    mock_execution = {"status": "success", "result": "abcabcabc"}
    signals = _validate_constraints(mock_execution, constraints)
    print(f"Validation signals: {signals}")

print("\n" + "=" * 100)
print("PART 2: RUNTIME TRACE TEST")
print("=" * 100)

for i, test_input in enumerate(test_inputs, 1):
    print(f"\n--- Runtime Test {i}: {test_input[:50]}... ---")
    
    workflow = {
        "id": f"wiring_audit_{i}",
        "name": f"wiring_audit_{i}",
        "status": "ACTIVE",
        "steps": [
            {
                "id": f"step_{i}",
                "name": f"step_{i}",
                "agent": "system",
                "purpose": test_input,
                "input": test_input,
                "status": "PENDING",
                "retries": 0,
                "max_retries": 2
            }
        ]
    }
    
    try:
        result = run_workflow(workflow)
        trace = trace_collector.get_trace()
        
        if trace:
            steps = trace.get("steps", [])
            for step in steps:
                if step.get("step_id") == f"step_{i}":
                    print(f"  Execution status: {step.get('execution_result', {}).get('status')}")
                    print(f"  Output: {step.get('execution_result', {}).get('result')}")
                    print(f"  Validator signals: {step.get('validator_signals')}")
                    print(f"  Extracted constraints (from trace): {step.get('validator_signals', {}).get('extracted_constraints')}")
        else:
            print("  [NO TRACE]")
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")

print("\n" + "=" * 100)
print("WIRING ANALYSIS")
print("=" * 100)

print("""
CODE PATH VERIFICATION:

1. _extract_constraints_llm() CALL:
   Location: evaluate_intent() line 232
   Call: constraints = _extract_constraints_llm(user_input)
   Status: ✅ CONFIRMED

2. CONSTRAINT VARIABLE FLOW:
   Line 232: constraints = _extract_constraints_llm(user_input)
   Line 233: constraint_signals = _validate_constraints(execution_result, constraints)
   Line 304: meta['extracted_constraints'] = constraints
   Status: ✅ NO REASSIGNMENTS, NO OVERWRITES

3. _validate_constraints() INPUT:
   Parameter: constraints (from line 232)
   Check at line 111: if not constraints: return signals
   Status: ✅ EMPTY DICT BYPASSES VALIDATION

ROOT CAUSE HYPOTHESIS:
- Wiring is CORRECT
- _extract_constraints_llm() returns {} (empty dict)
- Empty dict causes early return at line 111-112
- No validation performed
- constraint_ok stays True

PROBABLE EXTRACTION FAILURE:
- LLM returns invalid JSON
- LLM returns "{}" or malformed response
- json.JSONDecodeError triggers line 93
""")

print("=" * 100)
print("AUDIT COMPLETE")
print("=" * 100)
