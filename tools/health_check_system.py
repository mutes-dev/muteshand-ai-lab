import os
from core.config import BASE_PATH
from pathlib import Path

INPUT_SPEC = {}

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
        full = BASE_PATH / path
        results[name] = "ok" if full.exists() else "missing"

    status = "ok"
    if "missing" in results.values():
        status = "warning"

    return {
        "status": status,
        "checks": results
    }