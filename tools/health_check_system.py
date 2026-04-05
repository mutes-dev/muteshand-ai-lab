import os

INPUT_SPEC = {}

BASE = "E:/MutesHand"

CHECKS = {
    "tools_directory": "tools",
    "agents_directory": "agents",
    "memory_directory": "memory",
    "logs_directory": "logs",
    "projects_directory": "projects",
    "tool_index": "memory/tool_index/tools.json",
    "system_map": "memory/system_map.json",
    "manager_log": "logs/manager.log",
    "code_agent": "agents/code_agent.py",
    "tester_agent": "agents/tester_agent.py"
}

def run():
    results = {}

    for name, path in CHECKS.items():
        full = os.path.join(BASE, path)
        results[name] = "ok" if os.path.exists(full) else "missing"

    status = "ok"
    if "missing" in results.values():
        status = "warning"

    return {
        "status": status,
        "checks": results
    }