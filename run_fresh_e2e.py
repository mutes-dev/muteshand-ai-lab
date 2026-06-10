#!/usr/bin/env python3
import requests
import json
import time
import os

BASE_URL = 'http://localhost:8000'

# Create workflow
print('Creating workflow...')
resp = requests.post(f'{BASE_URL}/execute/stream', json={'input': 'Read the webpage at https://www.accuweather.com/'}, timeout=5)
print(f'Status: {resp.status_code}')
data = resp.json()
print(f'bg_id: {data.get("bg_id")}')

# Wait
print('Waiting 15s...')
time.sleep(15)

# Find newest workflow
wf_dir = 'E:/MutesHand/memory/active_workflows'
files = [(f, os.path.getmtime(os.path.join(wf_dir, f))) for f in os.listdir(wf_dir) if f.startswith('workflow_') and f.endswith('.json')]
files.sort(key=lambda x: x[1], reverse=True)

if files:
    newest = files[0][0]
    wf_id = newest.replace('.json', '')
    print(f'\nNewest workflow: {wf_id}')
    
    with open(os.path.join(wf_dir, newest), 'r') as f:
        wf = json.load(f)
    
    print(f'Status: {wf.get("status")}')
    steps = wf.get('steps', [])
    if steps:
        step = steps[0]
        print(f'Step status: {step.get("status")}')
        print(f'Blocked reason: {step.get("blocked_reason")}')
        print(f'Retries: {step.get("retries")}')
        print(f'Tool: {step.get("tool_call", "")[:50]}')
        print(f'Selected tool: {step.get("_agent_metadata", {}).get("selected_tool")}')
    else:
        print('No steps yet')
    
    # Check events
    event_path = f'E:/MutesHand/memory/events/{wf_id}.jsonl'
    if os.path.exists(event_path):
        with open(event_path, 'r') as f:
            events = [json.loads(line) for line in f if line.strip()]
        print(f'\nEvents ({len(events)}):')
        for ev in events:
            ev_type = ev.get('event_type', ev.get('type', 'unknown'))
            if ev_type in ['user_control_request_created', 'step_blocked', 'step_completed', 'step_execution_blocked']:
                print(f'  - {ev_type}')
    
    # Check controls
    print('\nChecking controls...')
    try:
        resp = requests.get(f'{BASE_URL}/user-controls/{wf_id}')
        if resp.status_code == 200:
            data = resp.json()
            requests_list = data.get('requests', {})
            if isinstance(requests_list, dict):
                print(f'Controls: {len(requests_list)}')
                for cid, cdata in requests_list.items():
                    print(f'  - {cid}: {cdata.get("requested_action")} ({cdata.get("status")})')
                    if cdata.get('requested_action') == 'accept_external_call_risk':
                        print(f'\n*** CONTROL FOUND: {cid} ***')
            else:
                print(f'Controls type: {type(requests_list)}')
        else:
            print(f'Error: {resp.status_code}')
    except Exception as e:
        print(f'Error: {e}')
