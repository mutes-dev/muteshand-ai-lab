"""
ISSUE-092B Live Smoke Validation — Greeting prompts only
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

def test_prompt(label, prompt):
    print(f"\n=== {label}: '{prompt}' ===")
    try:
        bg_id, wf_id = call_stream(prompt)
        print(f"bg_id={bg_id}, workflow_id={wf_id}")
        result = poll_stream(bg_id)
        if not result:
            print("TIMEOUT waiting for terminal state")
            return
        print(json.dumps(result, indent=2, default=str))
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    test_prompt("Greeting A", "Hi I am Bryan")
    test_prompt("Greeting B", "Hi my name is Bryan")
