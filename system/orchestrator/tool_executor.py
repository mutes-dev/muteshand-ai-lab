from system.orchestrator.tool_validator import validate_tool_input, validate_tool_output


def execute_tool(tool: dict, input_data):
    input_validation = validate_tool_input(tool, input_data)

    if input_validation["status"] == "failure":
        return {
            "status": "failure",
            "reason": "invalid_tool_input"
        }

    result = {
        "status": "success",
        "result": {
            "tool": tool["name"],
            "message": "tool_executed"
        }
    }

    output_validation = validate_tool_output(tool, result)

    if output_validation["status"] == "failure":
        return {
            "status": "failure",
            "reason": "invalid_tool_output"
        }

    return result
