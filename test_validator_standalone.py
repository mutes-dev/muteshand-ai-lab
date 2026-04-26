import sys
sys.path.insert(0, '.')
from system.orchestrator.planner_output_validator import validate_planner_output
from system.orchestrator.orchestrator_planner import plan_workflow
import json

test_cases = [
    'subtract -5 from -10',
    'repeat test 0 times',
    'add 2 and 3 then multiply by 4'
]

print('=' * 70)
print('PLANNER OUTPUT VALIDATOR — STANDALONE TEST RESULTS')
print('=' * 70)

all_valid = True
for test_input in test_cases:
    print(f'\n--- TEST: {test_input} ---')
    
    # Get planner output
    planner_result = plan_workflow(test_input)
    steps = planner_result.get('workflow', {}).get('steps', [])
    
    print('Planner steps:')
    for step in steps:
        purpose = step.get('purpose', 'N/A')
        print(f'  - {purpose}')
    
    # Run validator
    validation = validate_planner_output(steps)
    print('Validator result:')
    print(f'  valid: {validation["valid"]}')
    if validation['issues']:
        print(f'  issues: {json.dumps(validation["issues"], indent=4)}')
        all_valid = False
    else:
        print('  issues: []')
    print()

print('=' * 70)
if all_valid:
    print('ALL TESTS VALID: No tool syntax detected in planner output')
else:
    print('ISSUES DETECTED: Some planner output contains tool-like patterns')
print('=' * 70)
