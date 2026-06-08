"""
Direct API check for failure_display_message field.
"""
import sys, json, time, urllib.request

BASE = "http://127.0.0.1:8000"

def call_stream(input_text):
    req = urllib.request.Request(
        f"{BASE}/execute/stream",
        data=json.dumps({"input": input_text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req)
    data = json.loads(resp.read().decode())
    return data.get("bg_id"), data.get("workflow_id")

def poll_stream(bg_id):
    for _ in range(60):
        try:
            resp = urllib.request.urlopen(f"{BASE}/execute/stream/workflow_id/{bg_id}")
            data = json.loads(resp.read().decode())
            if data.get("status") in ("FAILED", "COMPLETED", "CANCELLED"):
                return data
        except Exception as e:
            print(f"poll error: {e}")
        time.sleep(1)
    return None

bg_id, wf_id = call_stream("Hi I am Bryan")
print(f"bg_id={bg_id}, workflow_id={wf_id}")
result = poll_stream(bg_id)
if result:
    r = result.get("result", {})
    print(f"reason: {r.get('reason')}")
    print(f"failure_reason: {r.get('failure_reason')}")
    print(f"failure_display_message: {r.get('failure_display_message')}")
    print(f"retry_eligible: {r.get('retry_eligible')}")
    print(f"failed_step_id: {r.get('failed_step_id')}")
    if r.get("failure_display_message"):
        print("PASS: failure_display_message present")
    else:
        print("FAIL: failure_display_message missing")
else:
    print("TIMEOUT")
