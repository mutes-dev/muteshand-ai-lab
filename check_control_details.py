#!/usr/bin/env python3
import os
import json
import requests

# Check the latest workflow events
wf_dir = 'E:/MutesHand/memory/active_workflows'
files = [(f, os.path.getmtime(os.path.join(wf_dir, f))) for f in os.listdir(wf_dir) if f.startswith('workflow_') and f.endswith('.json')]
files.sort(key=lambda x: x[1], reverse=True)

if files:
    newest = files[0][0]
    wf_id = newest.replace('.json', '')
    print(f'Workflow: {wf_id}')
    
    # Read events
    event_path = f'E:/MutesHand/memory/events/{wf_id}.jsonl'
    try:
        with open(event_path, 'r') as f:
            events = [json.loads(line) for line in f if line.strip()]
        
        print(f'\nEvent timeline ({len(events)} events):')
        for i, ev in enumerate(events):
            ev_type = ev.get('event_type', ev.get('type', 'unknown'))
            ts = ev.get('timestamp', 'no-ts')
            print(f'  {i+1}. {ev_type} at {ts}')
            if 'data' in ev:
                data = ev['data']
                if 'step_id' in data:
                    print(f'      step_id: {data["step_id"]}')
                if 'control_id' in data:
                    print(f'      control_id: {data["control_id"]}')
                if 'execution_status' in data:
                    print(f'      execution_status: {data["execution_status"]}')
                if 'failure_reason' in data:
                    print(f'      failure_reason: {data["failure_reason"]}')
    except Exception as e:
        print(f'Error reading events: {e}')
    
    # Check controls for this workflow
    print(f'\nControls for {wf_id}:')
    response = requests.get(f'http://localhost:8000/user-controls/{wf_id}')
    if response.status_code == 200:
        controls_data = response.json()
        requests_list = controls_data.get('requests', [])
        if isinstance(requests_list, dict):
            # Handle dict format
            for cid, cdata in requests_list.items():
                print(f'  - {cid}:')
                print(f'      action: {cdata.get("requested_action")}')
                print(f'      status: {cdata.get("status")}')
                print(f'      destination: {cdata.get("metadata", {}).get("destination")}')
        elif isinstance(requests_list, list):
            for c in requests_list:
                if isinstance(c, dict):
                    print(f'  - {c.get("control_id")}:')
                    print(f'      action: {c.get("requested_action")}')
                    print(f'      status: {c.get("status")}')
                    print(f'      destination: {c.get("metadata", {}).get("destination")}')
                else:
                    print(f'  - {c}')

print('\n' + '='*60)
print('VERIFICATION:')
print('1. Was step_started before control created? (SHOULD NOT HAPPEN)')
print('2. Is step blocked with external_call_risk? (SHOULD HAPPEN)')
print('3. Is control PENDING for accept_external_call_risk? (SHOULD HAPPEN)')
print('4. Were retries incremented? (SHOULD NOT HAPPEN)')
print('='*60)
