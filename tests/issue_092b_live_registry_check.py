"""
Check stream registry contents for the bg_id from live smoke test.
"""
import sys, json, urllib.request

BASE = "http://127.0.0.1:8000"
bg_id = "47642e1e-6392-4cdd-9b73-c1ab6b577cf7"

# We need an admin/debug endpoint or we can inspect via a custom script.
# The backend doesn't expose stream registry directly.
# But we can infer from the /execute/stream/workflow_id response.
resp = urllib.request.urlopen(f"{BASE}/execute/stream/workflow_id/{bg_id}")
data = json.loads(resp.read().decode())
print("=== STREAM RESPONSE ===")
print(json.dumps(data, indent=2, default=str))
