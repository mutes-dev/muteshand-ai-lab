import sys
sys.path.insert(0, '.')
from system.orchestrator.orchestrator_runtime import execute_from_input
from system.orchestrator.planner_output_validator import validate_planner_output
from system.orchestrator.orchestrator_planner import plan_workflow
import json

test_cases = [
    'subtract -5 from -10',
    'repeat test 0 times',
    'add 2 and 3 then multiply by 4'
]

print('=' * 70)
print('PLANNER OUTPUT VALIDATOR — INTEGRATION TEST RESULTS')
print('=' * 70)

for test_input in test_cases:
    print(f'\n--- TEST: {test_input} ---')
    
    # First, get planner output directly
    planner_result = plan_workflow(test_input)
    steps = planner_result.get('workflow', {}).get('steps', [])
    
    print(f'Planner steps:')
    for step in steps:
        print(f'  - {step.get("purpose", "N/A")}')
    
    # Run validator
    validation = validate_planner_output(steps)
    print(f'Validator result:')
    print(f'  valid: {validation["valid"]}')
    if validation["issues"]:
        print(f'  issues: {json.dumps(validation["issues"], indent=4)}')
    else:
        print(f'  issues: []')
    
    print()

print('=' * 70)
print('TESTING FULL EXECUTION WITH VALIDATOR OBSERVATION')
print('=' * 70)

for test_input in test_cases:
    print(f'\n--- FULL EXECUTION: {test_input} ---')
    result = execute_from_input(test_input)
    print(f'Execution result: {json.dumps(result, indent=2)}')
    print()

print('=' * 70)
print('INTEGRATION TESTS COMPLETE')
print('=' * 70)
