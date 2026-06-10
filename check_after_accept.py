import requests
import json

workflow_id = 'workflow_ef0a222f'

print('=== CHECKING AFTER ACCEPT ===')
resp = requests.get('http://localhost:8000/workflows/authoritative')
data = resp.json()
workflows = data.get('workflows', [])
print(f'Total workflows: {len(workflows)}')

wf = None
for w in workflows:
    if w.get('id') == workflow_id:
        wf = w
        break

if wf:
    print(f'Workflow status: {wf.get("status")}')
    steps = wf.get('steps', [])
    if steps:
        step = steps[0]
        print(f'Step status: {step.get("status")}')
        print(f'Blocked reason: {step.get("blocked_reason")}')
        print(f'Retries: {step.get("retries")}')
        print(f'Tool call: {step.get("tool_call")}')
        exec_result = step.get('execution_result', {})
        print(f'Execution status: {exec_result.get("status")}')
        print(f'Execution reason: {exec_result.get("reason")}')
else:
    print('Workflow not found in authoritative list')
    # Check persistence directly
    try:
        with open(f'E:/MutesHand/memory/active_workflows/{workflow_id}.json', 'r') as f:
            wf = json.load(f)
        print(f'Persistence status: {wf.get("status")}')
        steps = wf.get('steps', [])
        if steps:
            step = steps[0]
            print(f'Step status: {step.get("status")}')
            print(f'Blocked reason: {step.get("blocked_reason")}')
            print(f'Retries: {step.get("retries")}')
    except Exception as e:
        print(f'Error: {e}')
