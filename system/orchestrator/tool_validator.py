def validate_tool_input(tool: dict, input_data) -> dict:
    if input_data is None:
        return {"status": "failure", "reason": "invalid_tool_input"}

    if not isinstance(tool, dict):
        return {"status": "failure", "reason": "invalid_tool_input"}

    if "input_schema" not in tool or not isinstance(tool["input_schema"], dict):
        return {"status": "failure", "reason": "invalid_tool_input"}

    return {"status": "success"}


def validate_tool_output(tool: dict, output: dict) -> dict:
    if not isinstance(output, dict):
        return {"status": "failure", "reason": "invalid_tool_output"}

    if "status" not in output:
        return {"status": "failure", "reason": "invalid_tool_output"}

    if output["status"] == "success":
        if "result" not in output:
            return {"status": "failure", "reason": "invalid_tool_output"}

    return {"status": "success"}
