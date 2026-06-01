import urllib.request
import json

BASE = "http://127.0.0.1:8001"

def get_authoritative():
    resp = urllib.request.urlopen(f"{BASE}/workflows/authoritative")
    return json.loads(resp.read())

def get_historical():
    resp = urllib.request.urlopen(f"{BASE}/workflows/historical")
    return json.loads(resp.read())

def get_projection(wf_id):
    try:
        resp = urllib.request.urlopen(f"{BASE}/projection/{wf_id}")
        return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

def post_retry(wf_id, step_id):
    req = urllib.request.Request(
        f"{BASE}/workflow/{wf_id}/mutation",
        data=json.dumps({"mutation_type": "retry_step", "payload": {"step_id": step_id}}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())

def post_archive(wf_id):
    req = urllib.request.Request(
        f"{BASE}/workflow/{wf_id}/archive",
        method="POST"
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

WF_ID = "test_issue_062_manual_failed"

# 1. Authoritative
print("=== 1. AUTHORITATIVE METADATA ===")
auth = get_authoritative()
for w in auth["workflows"]:
    if w["workflow_id"] == WF_ID:
        print(f"failed_recoverable: {w.get('failed_recoverable')}")
        print(f"retry_eligible: {w.get('retry_eligible')}")
        print(f"taskhub_eligible: {w.get('taskhub_eligible')}")
        print(f"history_eligible: {w.get('history_eligible')}")
        print(f"taskhub_action: {w.get('taskhub_action')}")
        print(f"action_label: {w.get('action_label')}")
        print(f"actionability: {w.get('actionability')}")
        break
else:
    print("ERROR: workflow not found in authoritative")

# 2. Projection
print("\n=== 2. PROJECTION METADATA ===")
proj = get_projection(WF_ID)
if "error" in proj:
    print(f"Projection error: {proj['error']}")
else:
    print(f"lifecycle_status: {proj.get('lifecycle_status')}")
    print(f"retry_target_step_id: {proj.get('retry_target_step_id')}")
    print(f"failed_recoverable: {proj.get('failed_recoverable')}")
    print(f"retry_eligible: {proj.get('retry_eligible')}")

# 3. Retry
print("\n=== 3. RETRY ENDPOINT ===")
retry_result = post_retry(WF_ID, "step_1")
print(json.dumps(retry_result, indent=2))

# 4. History before archive
print("\n=== 4. HISTORY (before archive) ===")
hist = get_historical()
for w in hist["workflows"]:
    if w["workflow_id"] == WF_ID:
        print(f"Found in history: retention_state={w.get('retention_state')}, history_eligible={w.get('history_eligible')}")
        break
else:
    print("Not found in history (expected: actionable FAILED excluded from All)")

# 5. Archive
print("\n=== 5. ARCHIVE ===")
archive_result = post_archive(WF_ID)
print(json.dumps(archive_result, indent=2))

# 6. History after archive
print("\n=== 6. HISTORY (after archive) ===")
hist2 = get_historical()
for w in hist2["workflows"]:
    if w["workflow_id"] == WF_ID:
        print(f"Found in history: retention_state={w.get('retention_state')}, archived={w.get('archived')}, history_eligible={w.get('history_eligible')}")
        break
else:
    print("Not found in history after archive")
