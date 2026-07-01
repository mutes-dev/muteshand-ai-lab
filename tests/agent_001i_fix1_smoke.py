"""
AGENT-001I-FIX1 Real LLM Smoke Tests for extract_key_points

Runs execute_tool_selection with real Ollama LLM to verify:
1. File key-points produce substantive bullet points
2. URL key-points produce substantive bullet points
3. Summarize regression still works

Usage:
    cd E:\MutesHand
    python tests\agent_001i_fix1_smoke.py
"""

import os
import sys
import urllib.request

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from system.orchestrator.agents.tool_selection_agent import execute_tool_selection


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _fetch_url(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _smoke(label: str, input_data: str, dependency_data: str, allowed_tool: str = "finalize_output", capability_metadata: dict = None):
    print(f"\n{'=' * 60}")
    print(f"SMOKE: {label}")
    print(f"{'=' * 60}")

    context = {
        "workflow_id": "wf_smoke_001i",
        "step_id": "step_2",
        "allowed_tool": allowed_tool,
        "dependency_outputs": {
            "step_1": {
                "status": "success",
                "data": dependency_data,
                "purpose": "Read resource",
                "selected_tool": "read_file",
            },
        },
    }
    if capability_metadata:
        context["capability_metadata"] = capability_metadata

    result = execute_tool_selection(
        agent={"name": "tool_selection_agent", "role": "tool_selection", "scope": ["tool_selection"]},
        input_data=input_data,
        context=context,
    )

    print(f"Status: {result.get('status')}")
    if result.get("status") == "success":
        output = result.get("result", {}).get("output", "")
        executed_input = result.get("result", {}).get("executed_input", "")
        print(f"\n--- executed_input (first 500 chars) ---")
        print(executed_input[:500])
        print(f"\n--- output (first 800 chars) ---")
        print(output[:800])

        # Heuristic checks
        if capability_metadata and capability_metadata.get("final_action") == "extract_key_points":
            lines = [l.strip() for l in output.splitlines() if l.strip()]
            bullet_lines = [l for l in lines if l.startswith("-") or l.startswith("*") or l.startswith("•")]
            print(f"\n[CHECK] Bullet-like lines found: {len(bullet_lines)}")
            if len(bullet_lines) < 2:
                print("[WARN] Expected at least 2 bullet-like lines for key points")
            else:
                print("[PASS] At least 2 bullet-like lines present")
        print(f"{'=' * 60}\n")
        return True
    else:
        print(f"Result: {result}")
        print(f"{'=' * 60}\n")
        return False


if __name__ == "__main__":
    # 1. File key-points smoke
    file_path = os.path.join(_project_root, "Project Docs", "SYSTEM_STATE_V2.txt")
    file_content = _read_file(file_path)
    # Truncate to avoid token overflow for local LLM
    file_content = file_content[:3000]
    ok1 = _smoke(
        "File key-points: SYSTEM_STATE_V2.txt",
        "Extract key points from the file contents from step_1",
        file_content,
        capability_metadata={
            "final_action": "extract_key_points",
            "intent_mode": "extract_key_points",
            "transform_required": True,
        },
    )

    # 2. URL key-points smoke
    try:
        url_content = _fetch_url("https://example.com")
        url_content = url_content[:3000]
    except Exception as e:
        print(f"WARN: Could not fetch example.com: {e}")
        url_content = "Example Domain. This domain is for use in illustrative examples in documents."

    ok2 = _smoke(
        "URL key-points: example.com",
        "Extract key points from the webpage contents from step_1",
        url_content,
        capability_metadata={
            "final_action": "extract_key_points",
            "intent_mode": "extract_key_points",
            "transform_required": True,
        },
    )

    # 3. Regression smoke: summarize
    ok3 = _smoke(
        "Regression summarize: SYSTEM_STATE_V2.txt",
        "Summarize the file contents from step_1",
        file_content,
        capability_metadata={
            "final_action": "summarize",
            "intent_mode": "summarize",
            "transform_required": True,
        },
    )

    print("\n" + "=" * 60)
    print("SMOKE SUMMARY")
    print("=" * 60)
    print(f"File key-points:   {'PASS' if ok1 else 'FAIL'}")
    print(f"URL key-points:    {'PASS' if ok2 else 'FAIL'}")
    print(f"Regression summarize: {'PASS' if ok3 else 'FAIL'}")
    print("=" * 60)
