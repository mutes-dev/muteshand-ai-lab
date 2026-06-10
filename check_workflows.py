#!/usr/bin/env python3
import requests
import json
import os

BASE_URL = 'http://localhost:8000'

# Check workflows list
response = requests.get(f'{BASE_URL}/workflows/authoritative')
workflows = response.json().get('workflows', [])
print(f'Total workflows: {len(workflows)}')

# Show most recent 5
for wf in workflows[:5]:
    steps = wf.get('steps', [])
    input_text = steps[0].get('input', '') if steps else ''
    print(f'  - {wf.get("id")}: {wf.get("status")} - {input_text[:50]}...')

# Check active_workflows folder for newest file
print('\nNewest files in active_workflows:')
wf_dir = 'E:/MutesHand/memory/active_workflows'
files = [(f, os.path.getmtime(os.path.join(wf_dir, f))) for f in os.listdir(wf_dir) if f.endswith('.json')]
files.sort(key=lambda x: x[1], reverse=True)
for fname, mtime in files[:5]:
    print(f'  - {fname}')
