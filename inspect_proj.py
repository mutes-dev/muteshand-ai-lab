import requests
resp = requests.get('http://localhost:8000/projection/workflow_f8ebdfc8')
print(f"status_code={resp.status_code}")
if resp.status_code == 200:
    d = resp.json()
    print(f"lifecycle_status={d.get('lifecycle_status')}")
    for s in d.get('steps', []):
        print(f"{s['step_id']}: status={s['status']} blocked_reason={s.get('blocked_reason')}")
else:
    print(f"error: {resp.text}")
