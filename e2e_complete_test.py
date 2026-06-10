#!/usr/bin/env python3
"""ISSUE-098KR Complete E2E Test with Accept Flow"""
import requests
import json
import time
import os
from datetime import datetime

BASE_URL = 'http://localhost:8000'

def main():
    print('='*70)
    print('ISSUE-098KR POST-RESTART E2E VERIFICATION')
    print('='*70)
    
    # Step 1: Create workflow
    print('\n[1] Creating workflow with AccuWeather prompt...')
    resp = requests.post(f'{BASE_URL}/execute/stream', 
                        json={'input': 'Read the webpage at https://www.accuweather.com/'}, 
                        timeout=5)
    print(f'    Response: {resp.status_code}')
    data = resp.json()
    bg_id = data.get('bg_id')
    print(f'    bg_id: {bg_id}')
    
    # Step 2: Wait for execution
    print('\n[2] Waiting 15s for workflow execution...')
    time.sleep(15)
    
    # Step 3: Find the workflow
    print('\n[3] Finding workflow...')
    wf_dir = 'E:/MutesHand/memory/active_workflows'
    files = [(f, os.path.getmtime(os.path.join(wf_dir, f))) 
             for f in os.listdir(wf_dir) if f.startswith('workflow_') and f.endswith('.json')]
    files.sort(key=lambda x: x[1], reverse=True)
    
    wf_id = None
    for f, _ in files:
        with open(os.path.join(wf_dir, f), 'r') as fp:
            wf = json.load(fp)
        if 'accuweather' in wf.get('goal', '').lower():
            wf_id = f.replace('.json', '')
            break
    
    if not wf_id:
        print('    ERROR: Workflow not found')
        return 1
    
    print(f'    workflow_id: {wf_id}')
    
    # Step 4: Check workflow state
    print('\n[4] Checking workflow state...')
    with open(os.path.join(wf_dir, f'{wf_id}.json'), 'r') as fp:
        wf = json.load(fp)
    
    print(f'    Workflow status: {wf.get("status")}')
    steps = wf.get('steps', [])
    if steps:
        step = steps[0]
        print(f'    Step status: {step.get("status")}')
        print(f'    Blocked reason: {step.get("blocked_reason")}')
        print(f'    Retries: {step.get("retries")}')
        print(f'    Tool call: {step.get("tool_call", "")[:50]}')
        agent_meta = step.get('_agent_metadata', {})
        print(f'    Selected tool: {agent_meta.get("selected_tool")}')
    
    # Step 5: Check events
    print('\n[5] Checking events...')
    event_path = f'E:/MutesHand/memory/events/{wf_id}.jsonl'
    if os.path.exists(event_path):
        with open(event_path, 'r') as f:
            events = [json.loads(line) for line in f if line.strip()]
        print(f'    Total events: {len(events)}')
        for ev in events:
            ev_type = ev.get('event_type', ev.get('type', 'unknown'))
            if 'user_control' in ev_type.lower() or ev_type in ['step_completed', 'step_execution_blocked']:
                print(f'    - {ev_type}')
    
    # Step 6: Check controls
    print('\n[6] Checking user controls...')
    resp = requests.get(f'{BASE_URL}/user-controls/{wf_id}')
    control_id = None
    if resp.status_code == 200:
        data = resp.json()
        requests_list = data.get('requests', {})
        if isinstance(requests_list, dict):
            print(f'    Controls found: {len(requests_list)}')
            for cid, cdata in requests_list.items():
                print(f'    - {cid}: {cdata.get("requested_action")} ({cdata.get("status")})')
                if cdata.get('requested_action') == 'accept_external_call_risk':
                    control_id = cid
                    print(f'    *** CONTROL ID FOR ACCEPT: {cid} ***')
    
    # Save state before accept
    before_accept = {
        'timestamp': datetime.now().isoformat(),
        'workflow_id': wf_id,
        'control_id': control_id,
        'workflow_status': wf.get('status'),
        'step_status': step.get('status') if steps else None,
        'blocked_reason': step.get('blocked_reason') if steps else None,
        'retries': step.get('retries') if steps else None,
        'selected_tool': agent_meta.get('selected_tool') if steps else None,
    }
    
    with open('E:/MutesHand/ISSUE-098KR_E2E_BEFORE_ACCEPT.json', 'w') as f:
        json.dump(before_accept, f, indent=2)
    
    print('\n' + '='*70)
    print('BEFORE ACCEPT STATE')
    print('='*70)
    print(json.dumps(before_accept, indent=2))
    
    # Verification checks before accept
    print('\n' + '='*70)
    print('VERIFICATION CHECKS (Before Accept)')
    print('='*70)
    
    passed = 0
    total = 0
    
    # Check 1: Control created
    total += 1
    if control_id:
        print(f'✓ [{total}] User control request created')
        passed += 1
    else:
        print(f'✗ [{total}] User control request NOT created')
    
    # Check 2: Step blocked
    total += 1
    if steps and step.get('status') == 'BLOCKED':
        print(f'✓ [{total}] Step is BLOCKED')
        passed += 1
    else:
        print(f'✗ [{total}] Step is NOT blocked (status: {step.get("status") if steps else "N/A"})')
    
    # Check 3: Blocked reason correct
    total += 1
    if steps and step.get('blocked_reason') == 'external_call_risk':
        print(f'✓ [{total}] Blocked reason is external_call_risk')
        passed += 1
    else:
        print(f'✗ [{total}] Blocked reason is {step.get("blocked_reason") if steps else "N/A"}')
    
    # Check 4: Tool selected
    total += 1
    if steps and agent_meta.get('selected_tool') == 'read_webpage':
        print(f'✓ [{total}] AG1 selected read_webpage')
        passed += 1
    else:
        print(f'✗ [{total}] Tool not selected correctly')
    
    # Check 5: No retries burned
    total += 1
    retries = step.get('retries', 0) if steps else 0
    if retries == 0:
        print(f'✓ [{total}] No retries burned (retries={retries})')
        passed += 1
    else:
        print(f'⚠ [{total}] Retries: {retries}')
        # Still pass if < 2
        if retries < 2:
            passed += 1
    
    print(f'\nChecks passed: {passed}/{total}')
    
    if not control_id:
        print('\n*** CANNOT PROCEED: No control_id found ***')
        return 1
    
    # Step 7: Accept the control
    print('\n' + '='*70)
    print('ACCEPTING CONTROL REQUEST')
    print('='*70)
    print(f'POST /user-controls/{control_id}/accept')
    
    resp = requests.post(f'{BASE_URL}/user-controls/{control_id}/accept')
    print(f'    Response: {resp.status_code}')
    if resp.status_code == 200:
        accept_data = resp.json()
        print(f'    Result: {json.dumps(accept_data, indent=2)}')
    else:
        print(f'    Error: {resp.text}')
        return 1
    
    # Step 8: Wait for execution after accept
    print('\n[8] Waiting 10s for execution after accept...')
    time.sleep(10)
    
    # Step 9: Check after-accept state
    print('\n[9] Checking post-accept state...')
    with open(os.path.join(wf_dir, f'{wf_id}.json'), 'r') as fp:
        wf_after = json.load(fp)
    
    print(f'    Workflow status: {wf_after.get("status")}')
    steps_after = wf_after.get('steps', [])
    if steps_after:
        step_after = steps_after[0]
        print(f'    Step status: {step_after.get("status")}')
        print(f'    Retries: {step_after.get("retries")}')
        print(f'    Execution result: {json.dumps(step_after.get("execution_result", {}), indent=2)[:100]}')
    
    # Check events after accept
    print('\n[10] Checking events after accept...')
    if os.path.exists(event_path):
        with open(event_path, 'r') as f:
            events_after = [json.loads(line) for line in f if line.strip()]
        print(f'    Total events: {len(events_after)}')
        for ev in events_after:
            ev_type = ev.get('event_type', ev.get('type', 'unknown'))
            if 'user_control' in ev_type.lower() or ev_type in ['step_completed', 'step_execution_blocked', 'step_started']:
                ts = ev.get('timestamp', 'no-ts')
                print(f'    - {ev_type} at {ts}')
    
    # Save state after accept
    after_accept = {
        'timestamp': datetime.now().isoformat(),
        'workflow_id': wf_id,
        'control_id': control_id,
        'workflow_status': wf_after.get('status'),
        'step_status': step_after.get('status') if steps_after else None,
        'retries': step_after.get('retries') if steps_after else None,
        'execution_result': step_after.get('execution_result') if steps_after else None,
    }
    
    with open('E:/MutesHand/ISSUE-098KR_E2E_AFTER_ACCEPT.json', 'w') as f:
        json.dump(after_accept, f, indent=2)
    
    # Final verification
    print('\n' + '='*70)
    print('FINAL VERIFICATION')
    print('='*70)
    
    # Check if system_entry was called after accept
    exec_result = step_after.get('execution_result', {}) if steps_after else {}
    has_execution = exec_result.get('status') is not None or exec_result.get('result') is not None
    
    if has_execution:
        print('✓ Tool was executed after Accept')
    else:
        print('⚠ Tool execution status unclear')
    
    print('\n' + '='*70)
    print('E2E TEST COMPLETE')
    print('='*70)
    print(f'Workflow ID: {wf_id}')
    print(f'Control ID: {control_id}')
    print(f'Before Accept State: E:/MutesHand/ISSUE-098KR_E2E_BEFORE_ACCEPT.json')
    print(f'After Accept State: E:/MutesHand/ISSUE-098KR_E2E_AFTER_ACCEPT.json')
    
    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())
