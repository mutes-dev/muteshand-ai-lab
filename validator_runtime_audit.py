#!/usr/bin/env python3
"""
RUNTIME TRACE VERIFICATION
Capture validator inputs during real execution.
"""

from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator import trace_collector

# Known blind spot inputs
test_inputs = [
    "repeat \"abc\" 3 times but output only the count",
    "multiply 2 and 3 but respond in words"
]

print("=" * 80)
print("RUNTIME TRACE VERIFICATION")
print("=" * 80)

for i, test_input in enumerate(test_inputs, 1):
    print(f"\n--- Test {i}: {test_input[:50]}... ---")
    
    workflow = {
        "id": f"runtime_audit_{i}",
        "name": f"runtime_audit_{i}",
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
                if step.get("event") != "governance_decision":
                    print(f"  Execution status: {step.get('execution_result', {}).get('status')}")
                    print(f"  Output: {step.get('execution_result', {}).get('result')}")
                    print(f"  Validator advisory: {step.get('validator_advisory')}")
                    print(f"  Governance: {step.get('governance_decision')}")
        else:
            print("  [NO TRACE]")
            
    except Exception as e:
        print(f"  [ERROR] {type(e).__name__}: {e}")

print("\n" + "=" * 80)
print("RUNTIME VERIFICATION COMPLETE")
print("=" * 80)
