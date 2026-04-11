tools = {}


def register_tool(tool: dict) -> dict:
    if not isinstance(tool, dict):
        return {"status": "failure", "reason": "invalid_tool_type"}

    required_fields = ["name", "input_schema", "output_schema"]

    for field in required_fields:
        if field not in tool:
            return {"status": "failure", "reason": "missing_tool_field"}

    name = tool["name"]

    if not isinstance(name, str) or not name:
        return {"status": "failure", "reason": "invalid_tool_name"}

    if not isinstance(tool["input_schema"], dict):
        return {"status": "failure", "reason": "invalid_input_schema"}

    if not isinstance(tool["output_schema"], dict):
        return {"status": "failure", "reason": "invalid_output_schema"}

    if name in tools:
        return {"status": "failure", "reason": "duplicate_tool"}

    tools[name] = tool

    return {"status": "success"}


def get_tool(name: str) -> dict:
    if name not in tools:
        return {"status": "failure", "reason": "tool_not_found"}

    return {"status": "success", "tool": tools[name]}


def list_tools() -> dict:
    return {
        "status": "success",
        "tools": list(tools.keys())
    }
