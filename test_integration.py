#!/usr/bin/env python
"""Integration test for structural realignment."""
import sys
sys.path.insert(0, '.')

from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator.workflow_validator import validate_workflow, VALID_STEP_STATUSES

print('=== STEP SCHEMA CONTRACT V1 VALIDATION ===')

# Test 1: Full schema step
workflow_full = {
    'id': 'test_workflow',
    'name': 'test',
    'status': 'ACTIVE',
    'steps': [
        {
            'id': 'step_1',
            'type': 'EXECUTE_API',
            'name': 'test_step',
            'purpose': 'add 5 3',
            'tool_call': None,
            'expected_outcome': 'Sum calculated',
            'risk': 'LOW',
            'importance': 'MEDIUM',
            'resource_targets': [],
            'agent': 'default_agent',
            'status': 'PENDING',
            'retries': 0,
            'max_retries': 1,
            'input': 'add 5 3'
        }
    ]
}

result = validate_workflow(workflow_full)
print(f'Full schema step validation: {result}')

# Test 2: Valid step states
print()
print('=== STATE TRANSITIONS CONTRACT V1 ===')
print(f'Valid step states: {VALID_STEP_STATUSES}')
print(f'Expected: ["PENDING", "ACTIVE", "COMPLETED", "FAILED", "BLOCKED"]')

# Test 3: Workflow execution
print()
print('=== WORKFLOW EXECUTION TEST ===')
result = run_workflow(workflow_full)
print(f'Workflow result: {result}')

print()
print('INTEGRATION TEST COMPLETE')
