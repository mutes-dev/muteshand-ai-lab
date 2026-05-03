#!/usr/bin/env python
"""Test valid tool_call enforcement."""
import sys
sys.path.insert(0, '.')

from system.orchestrator.orchestrator_runtime import run_workflow

# Test: Valid tool_call execution
workflow = {
    'id': 'test_workflow',
    'name': 'test',
    'status': 'ACTIVE',
    'steps': [
        {
            'id': 'step_1',
            'type': 'EXECUTE_API',
            'name': 'test_step',
            'purpose': 'add 10 20',
            'tool_call': 'add_numbers 10 20',  # VALID tool_call
            'expected_outcome': 'Sum calculated',
            'risk': 'LOW',
            'importance': 'MEDIUM',
            'resource_targets': [],
            'agent': 'default_agent',
            'status': 'PENDING',
            'retries': 0,
            'max_retries': 1,
            'input': 'add 10 20'
        }
    ]
}

print('=== VALID tool_call TEST ===')
print(f"tool_call: {repr(workflow['steps'][0]['tool_call'])}")
print(f"tool_call is valid: {workflow['steps'][0]['tool_call'] is not None}")
print()

result = run_workflow(workflow)
print(f"Result: {result.get('status')}")
if result.get('status') == 'success':
    print(f"Execution result: {result.get('result')}")
else:
    print(f"Failure reason: {result.get('reason')}")
    print(f"Trace steps: {len(result.get('trace', {}).get('steps', []))}")
    for s in result.get('trace', {}).get('steps', [])[:3]:
        print(f"  - {s.get('step_id')}: {s.get('governance_decision')} (status: {s.get('status')})")

print()
print('TEST COMPLETE')
