import sys
sys.path.insert(0, '.')
from system.orchestrator.orchestrator_planner import plan_workflow
import json

test_cases = [
    'subtract -5 from -10',
    'repeat test 0 times',
    'add 2 and 3 then multiply by 4'
]

print('=' * 70)
print('PLANNER TOOL CONTEXT - HARDENED CONSTRAINTS - TEST RESULTS')
print('=' * 70)

all_pass = True

for test_input in test_cases:
    print(f'\n--- TEST: {test_input} ---')
    result = plan_workflow(test_input)
    print(f'Result: {json.dumps(result, indent=2)}')
    
    # Check for tool syntax violations
    steps = result.get('workflow', {}).get('steps', [])
    for step in steps:
        purpose = step.get('purpose', '')
        violations = []
        if '_' in purpose:  # snake_case tool names
            violations.append('tool_name_snake_case')
        if '(' in purpose or ')' in purpose:  # function syntax
            violations.append('function_syntax')
        if 'USE_TOOL' in purpose:
            violations.append('USE_TOOL_syntax')
        if '"' in purpose or "'" in purpose:  # quoted arguments
            violations.append('quoted_arguments')
        if violations:
            print(f'VIOLATIONS: {violations}')
            all_pass = False
    print()

print('=' * 70)
if all_pass:
    print('ALL TESTS PASSED - No tool syntax detected')
else:
    print('VIOLATIONS DETECTED - Tool syntax found in output')
print('=' * 70)
