import copy
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm

TOOLS_PATH = os.path.join("system", "tool_index", "tools.json")
TOOLS_DIR = "tools"


def load_tools():
    with open(TOOLS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tools(data):
    with open(TOOLS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


BANNED_WORDS = ["process", "handle", "various", "operation"]


def load_code_snippet(tool_name):
    tool_file = os.path.join(TOOLS_DIR, f"{tool_name}.py")
    if not os.path.exists(tool_file):
        return None
    try:
        with open(tool_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return "".join(lines[:15])
    except Exception:
        return None


def load_full_code(tool_name):
    tool_file = os.path.join(TOOLS_DIR, f"{tool_name}.py")
    if not os.path.exists(tool_file):
        return None
    try:
        with open(tool_file, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


PLACEHOLDER_PHRASES = ["clear, specific", "one sentence description"]


def validate_metadata(data):
    if not isinstance(data, dict):
        return False
    description = data.get("description", "")
    if not isinstance(description, str) or len(description.split()) < 3:
        return False
    desc_lower = description.lower()
    if any(w in desc_lower for w in BANNED_WORDS):
        return False
    # A. Placeholder rejection
    if any(ph in desc_lower for ph in PLACEHOLDER_PHRASES):
        return False
    return True


def generate_metadata(provider, tool_name, inputs, code_snippet):
    prompt = f"""Analyze the following Python tool and generate metadata.

Tool name: {tool_name}

Inputs: {inputs}

Tool code:
{code_snippet}

Return ONLY valid JSON in this format:

{{
  "description": "Short sentence describing the tool"
}}"""

    for attempt in range(3):
        try:
            response = execute_llm(provider, prompt)
            if not response or response.get("status") != "success":
                continue

            raw = response.get("result", "")

            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start == -1 or end == 0:
                continue

            data = json.loads(raw[start:end])

            if validate_metadata(data):
                return data.get("description", "")

        except Exception:
            continue

    return None


def run():
    tools = load_tools()

    if not isinstance(tools, dict):
        print("❌ Error: tools.json is not a dict — aborting")
        return

    provider_result = get_llm("ollama_llm")
    if not provider_result or provider_result.get("status") != "success":
        print("❌ Error: LLM provider not available — aborting")
        return

    provider = provider_result["provider"]
    if provider is None:
        print("❌ Error: provider is None — aborting")
        return

    tools_copy = copy.deepcopy(tools)

    for tool_name, tool_data in tools_copy.items():
        if tool_data.get("description"):
            print(f"⏭️ Skipping (exists): {tool_name}")
            continue

        print(f"Processing: {tool_name}")

        code_snippet = load_code_snippet(tool_name)
        if code_snippet is None:
            print(f"⚠️ Skipped: {tool_name}")
            continue

        full_code = load_full_code(tool_name)
        if full_code is None:
            print(f"⚠️ Skipped: {tool_name}")
            continue

        combined_snippet = code_snippet + "\n\nFULL CODE:\n" + full_code

        inputs = tool_data.get("inputs", {})
        description = generate_metadata(provider, tool_name, inputs, combined_snippet)

        if description:
            tool_data["description"] = description
            print(f"✅ Success: {tool_name}")
        else:
            print(f"⚠️ Skipped: {tool_name}")

    try:
        save_tools(tools_copy)
        print("\ntools.json written successfully")
    except Exception as e:
        print(f"❌ Error: file write failed — {e}")


if __name__ == "__main__":
    run()
