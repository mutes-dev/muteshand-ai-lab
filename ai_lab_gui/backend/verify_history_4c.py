import urllib.request
import json

req = urllib.request.Request("http://localhost:8000/workflows/historical")
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read())

workflows = data.get("workflows", [])
print(f"TOTAL: {len(workflows)}")
for i, w in enumerate(workflows[:6]):
    hst = w.get("history_sort_timestamp")
    hss = w.get("history_sort_source")
    uid = w["workflow_id"][-8:]
    status = w["status"]
    print(f"[{i}] {uid} status={status:12s} hst={hst} hss={hss}")
