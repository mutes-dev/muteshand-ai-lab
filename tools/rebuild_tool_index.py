INPUT_SPEC = {}

def run(*args):

    import os
    import json
    import importlib

    BASE_PATH = "E:/MutesHand"
    tools_dir = os.path.join(BASE_PATH, "tools")
    index_file = os.path.join(BASE_PATH, "memory", "tool_index", "tools.json")

    # Ensure index directory exists
    os.makedirs(os.path.dirname(index_file), exist_ok=True)

    tool_index = {}

    for file in os.listdir(tools_dir):

        if not file.endswith(".py"):
            continue

        tool_name = file[:-3]

        try:
            module = importlib.import_module(f"tools.{tool_name}")
            importlib.reload(module)

            input_spec = getattr(module, "INPUT_SPEC", {})

        except Exception:
            input_spec = {}

        tool_index[tool_name] = {
            "description": f"Tool {tool_name}",
            "inputs": input_spec,
            "tags": []
        }

    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(tool_index, f, indent=2)

    return "Tool index rebuilt."