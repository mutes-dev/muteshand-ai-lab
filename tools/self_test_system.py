import os
import json

INPUT_SPEC = {}

BASE = "E:/MutesHand"

def test_write_read():
    try:
        test_file = os.path.join(BASE, "memory", "self_test.txt")

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
        path = os.path.join(BASE, "memory", "tool_index", "tools.json")
        with open(path, "r") as f:
            json.load(f)
        return "pass"
    except:
        return "fail"


def test_code_agent():
    try:
        path = os.path.join(BASE, "agents", "code_agent.py")
        return "pass" if os.path.exists(path) else "fail"
    except:
        return "fail"


def test_tester_agent():
    try:
        path = os.path.join(BASE, "agents", "tester_agent.py")
        return "pass" if os.path.exists(path) else "fail"
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