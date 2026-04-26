import sys
sys.path.insert(0, '.')
from system.orchestrator.orchestrator_planner import plan_workflow
import json

print('=' * 70)
print('PLANNER PHRASING DRIFT AUDIT')
print('=' * 70)

# Test cases with multiple runs
test_cases = [
    # Core cases
    'power 2 to 3',
    'add -3 and -7',
    'multiply -4 by 5',
    'subtract -5 from -10',
    # Variation cases
    'calculate 2 to the power of 3',
    'what is 2^3',
    'raise 2 to 3'
]

runs_per_test = 3

results = {}

for test_input in test_cases:
    print(f"\n{'=' * 70}")
    print(f"TEST CASE: {test_input}")
    print('=' * 70)
    
    run_results = []
    for run_num in range(1, runs_per_test + 1):
        print(f"\n--- Run {run_num} ---")
        result = plan_workflow(test_input)
        
        steps = result.get('workflow', {}).get('steps', [])
        parsed_steps = [step.get('purpose', '') for step in steps]
        
        print(f"INPUT: {test_input}")
        print(f"PLANNER RAW OUTPUT: (see above DEBUG_PLANNER_RAW_OUTPUT)")
        print(f"PARSED STEPS: {parsed_steps}")
        
        run_results.append({
            'run': run_num,
            'input': test_input,
            'steps': parsed_steps
        })
    
    results[test_input] = run_results

# Summary analysis
print('\n' + '=' * 70)
print('REWRITE FREQUENCY ANALYSIS')
print('=' * 70)

for test_input, runs in results.items():
    print(f"\nInput: {test_input}")
    all_steps = [tuple(r['steps']) for r in runs]
    unique_outputs = set(all_steps)
    
    if len(unique_outputs) == 1:
        print(f"  Consistency: DETERMINISTIC (all {runs_per_test} runs identical)")
        print(f"  Output: {runs[0]['steps']}")
    else:
        print(f"  Consistency: VARIABLE ({len(unique_outputs)} unique outputs)")
        for i, u in enumerate(unique_outputs):
            count = all_steps.count(u)
            print(f"  Variant {i+1} ({count}/{runs_per_test} runs): {list(u)}")
    
    # Check for rewriting
    rewritten = any(r['steps'][0] != test_input for r in runs if r['steps'])
    if rewritten:
        print(f"  REWRITE DETECTED: Yes")
    else:
        print(f"  REWRITE DETECTED: No (input preserved)")

print('\n' + '=' * 70)
print('AUDIT COMPLETE')
print('=' * 70)
