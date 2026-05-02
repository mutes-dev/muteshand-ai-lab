#!/usr/bin/env python3
"""
CONSTRAINT EXTRACTION DEBUG FIRST
Run tests to reveal what LLM actually returns.
"""

from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator import trace_collector

# Test inputs (exact 3 from task)
test_inputs = [
    "repeat \"abc\" 3 times but output only the count",
    "multiply 2 and 3 but respond in words",
    "repeat \"test\" 5 times but return only the first word"
]

print("=" * 100)
print("CONSTRAINT EXTRACTION DEBUG FIRST")
print("=" * 100)
print("\nGoal: Reveal what LLM is actually returning")
print("NO fixes applied - only observation\n")

for i, test_input in enumerate(test_inputs, 1):
    print("\n" + "=" * 100)
    print(f"TEST {i}: {test_input}")
    print("=" * 100)
    
    workflow = {
        "id": f"debug_test_{i}",
        "name": f"debug_test_{i}",
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
        
        # Extract trace data
        trace = trace_collector.get_trace()
        if trace:
            steps = trace.get("steps", [])
            for step in steps:
                if step.get("step_id") == f"step_{i}":
                    print(f"\nEXECUTION RESULT:")
                    print(f"  Status: {step.get('execution_result', {}).get('status')}")
                    print(f"  Output: {step.get('execution_result', {}).get('result')}")
                    print(f"\nVALIDATOR OUTPUT:")
                    print(f"  Recommendation: {step.get('validator_advisory')}")
                    print(f"  Extracted constraints: {step.get('validator_signals', {}).get('extracted_constraints')}")
                    print(f"  Constraint OK: {step.get('validator_signals', {}).get('constraint_ok')}")
                    print(f"  Constraint violation: {step.get('validator_signals', {}).get('constraint_violation')}")
        
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")

print("\n" + "=" * 100)
print("DEBUG TESTS COMPLETE")
print("=" * 100)
