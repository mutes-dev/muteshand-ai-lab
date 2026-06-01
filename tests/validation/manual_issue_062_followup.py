import urllib.request
import json

BASE = "http://127.0.0.1:8001"
WF_ID = "test_issue_062_manual_failed"

# Check workflow status after retry
resp = urllib.request.urlopen(f"{BASE}/workflows/authoritative")
data = json.loads(resp.read())
for w in data["workflows"]:
    if w["workflow_id"] == WF_ID:
        print("=== POST-RETRY STATUS ===")
        print(f"status: {w.get('status')}")
        print(f"actionability: {w.get('actionability')}")
        print(f"taskhub_action: {w.get('taskhub_action')}")
        print(f"taskhub_eligible: {w.get('taskhub_eligible')}")
        print(f"history_eligible: {w.get('history_eligible')}")
        print(f"retention_state: {w.get('retention_state')}")
        break

# Check historical record
resp = urllib.request.urlopen(f"{BASE}/workflows/historical")
data = json.loads(resp.read())
for w in data["workflows"]:
    if w["workflow_id"] == WF_ID:
        print("\n=== POST-ARCHIVE HISTORY ===")
        print(f"status: {w.get('status')}")
        print(f"retention_state: {w.get('retention_state')}")
        print(f"archived: {w.get('archived')}")
        print(f"history_eligible: {w.get('history_eligible')}")
        # Confirm no action controls in History API
        has_action = any(k in w for k in ["taskhub_action", "action_label", "replan_eligible"])
        print(f"has_action_fields: {has_action}")
        break
