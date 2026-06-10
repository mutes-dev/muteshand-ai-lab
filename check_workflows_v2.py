#!/usr/bin/env python3
import os
import json
import requests

wf_dir = 'E:/MutesHand/memory/active_workflows'
files = [(f, os.path.getmtime(os.path.join(wf_dir, f))) for f in os.listdir(wf_dir) if f.startswith('workflow_') and f.endswith('.json')]
files.sort(key=lambda x: x[1], reverse=True)

print('Recent workflows:')
for f, _ in files[:10]:
    wf_id = f.replace('.json', '')
    with open(os.path.join(wf_dir, f), 'r') as fp:
        wf = json.load(fp)
    
    goal = wf.get('goal', '')
    print(f'{wf_id}: {wf.get("status")} - {goal[:50]}...')

print('\nLooking for accuweather workflows...')
for f, _ in files:
    wf_id = f.replace('.json', '')
    with open(os.path.join(wf_dir, f), 'r') as fp:
        wf = json.load(fp)
    
    goal = wf.get('goal', '')
    if 'accuweather' in goal.lower():
        print(f'\nFound: {wf_id}')
        print(f'  Status: {wf.get("status")}')
        steps = wf.get('steps', [])
        print(f'  Steps: {len(steps)}')
        if steps:
            step = steps[0]
            print(f'    Step status: {step.get("status")}')
            print(f'    Step tool: {step.get("tool_call", "")[:50]}')
            print(f'    Blocked reason: {step.get("blocked_reason")}')
            print(f'    Retries: {step.get("retries")}')
        
        # Check controls
        try:
            resp = requests.get(f'http://localhost:8000/user-controls/{wf_id}')
            if resp.status_code == 200:
                data = resp.json()
                requests_list = data.get('requests', [])
                if isinstance(requests_list, dict):
                    print(f'  Controls: {len(requests_list)}')
                    for cid, cdata in requests_list.items():
                        print(f'    - {cid}: {cdata.get("requested_action")} ({cdata.get("status")})')
                elif isinstance(requests_list, list):
                    print(f'  Controls: {len(requests_list)}')
        except Exception as e:
            print(f'  Error checking controls: {e}')
