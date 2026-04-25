import os
import json
from core.config import BASE_PATH
from pathlib import Path

INPUT_SPEC = {}

def test_write_read():
    try:
        test_file = BASE_PATH / "memory" / "self_test.txt"

        with open(test_file, "w") as f:
            f.write("AI_LAB_TEST")

        with open(test_file, "r") as f:
            data = f.read()

        os.remove(test_file)

        return "pass" if data == "AI_LAB_TEST" else "fail"
    except:
        return "fail"


def test_tool_index():
    try:
        path = BASE_PATH / "memory" / "tool_index" / "tools.json"
        with open(path, "r") as f:
            json.load(f)
        return "pass"
    except:
        return "fail"


def test_code_agent():
    try:
        path = BASE_PATH / "agents" / "code_agent.py"
        return "pass" if path.exists() else "fail"
    except:
        return "fail"


def test_tester_agent():
    try:
        path = BASE_PATH / "agents" / "tester_agent.py"
        return "pass" if path.exists() else "fail"
    except:
        return "fail"


def run():

    tests = {}

    tests["write_read_test"] = test_write_read()
    tests["tool_index_json"] = test_tool_index()
    tests["code_agent_presence"] = test_code_agent()
    tests["tester_agent_presence"] = test_tester_agent()

    status = "ok"
    if "fail" in tests.values():
        status = "warning"

    return {
        "status": status,
        "tests": tests
    }