import os
import json
import importlib
import py_compile

from core.logger import log
from core.config import BASE_PATH

MEMORY_FILE = BASE_PATH / "memory" / "system_map.json"

def load_memory():
    if not os.path.exists(MEMORY_FILE):
        return {"agents": [], "tools": [], "projects": []}

    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2)


def validate_python_file(file_path):
    try:
        py_compile.compile(file_path, doraise=True)
        return True
    except Exception as e:
        return str(e)


def refresh_system(TOOLS_PATH, AGENTS_PATH, TOOLS, AGENTS, memory):

    importlib.invalidate_caches()

    TOOLS.clear()
    AGENTS.clear()

    # Load tools
    for file in os.listdir(TOOLS_PATH):

        if file.endswith(".py"):

            tool_name = file[:-3]

            module = importlib.import_module(f"tools.{tool_name}")
            importlib.reload(module)

            TOOLS[tool_name] = module.run

    # Load agents
    if os.path.exists(AGENTS_PATH):

        for file in os.listdir(AGENTS_PATH):

            if file.endswith(".py"):

                agent_name = file[:-3]

                module = importlib.import_module(f"agents.{agent_name}")
                importlib.reload(module)

                AGENTS[agent_name] = module.run

    # Update memory
    memory["tools"] = list(TOOLS.keys())
    memory["agents"] = list(AGENTS.keys())

    save_memory(memory)

    log("System refreshed.")