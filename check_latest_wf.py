#!/usr/bin/env python3
import os
import json
import time

# Find the newest workflow file
wf_dir = 'E:/MutesHand/memory/active_workflows'
files = [(f, os.path.getmtime(os.path.join(wf_dir, f))) for f in os.listdir(wf_dir) if f.startswith('workflow_') and f.endswith('.json')]
files.sort(key=lambda x: x[1], reverse=True)

if files:
    newest = files[0][0]
    wf_id = newest.replace('.json', '')
    print(f'Newest workflow: {wf_id}')
    
    with open(os.path.join(wf_dir, newest), 'r') as f:
        wf = json.load(f)
    
    print(f'Workflow status: {wf.get("status")}')
    print(f'Workflow goal: {wf.get("goal", "")[:60]}...')
    
    steps = wf.get('steps', [])
    if steps:
        step = steps[0]
        print(f'Step status: {step.get("status")}')
        print(f'Step blocked_reason: {step.get("blocked_reason")}')
        print(f'Step retries: {step.get("retries")}')
        print(f'Selected tool: {step.get("_agent_metadata", {}).get("selected_tool")}')
        print(f'Tool call: {step.get("tool_call")}')

# Also check user controls
import requests
response = requests.get('http://localhost:8000/user-controls/pending')
if response.status_code == 200:
    controls = response.json()
    print(f'\nPending controls: {len(controls)}')
    for c in controls:
        print(f'  - {c.get("control_id")}: {c.get("requested_action")} ({c.get("status")})')
