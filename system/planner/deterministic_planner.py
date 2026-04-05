def plan(user_input: str) -> list | dict:
    import json
    import os

    tools_path = os.path.join("memory", "tool_index", "tools.json")

    with open(tools_path, "r") as f:
        tool_index = json.load(f)

    if isinstance(tool_index, dict):
        VALID_TOOL_IDS = set(tool_index.keys())
    elif isinstance(tool_index, list):
        VALID_TOOL_IDS = set(tool["name"] for tool in tool_index)
    else:
        raise ValueError("Invalid tool_index structure")

    TOOL_RULES = [
        ("sum of", "add_numbers"),
        ("add to", "add_numbers"),
        ("add", "add_numbers"),
        ("subtract from", "subtract_numbers"),
        ("difference between", "subtract_numbers"),
        ("subtract", "subtract_numbers"),
        ("product of", "multiply_numbers"),
        ("multiply by", "multiply_numbers"),
        ("multiply", "multiply_numbers"),
    ]

    segments = user_input.split(" then ")

    steps = []

    for segment in segments:
        segment_lower = segment.lower()

        tool_name = None

        for keyword, tool in TOOL_RULES:
            if keyword in segment_lower:
                tool_name = tool
                break

        # FAIL-FAST: Return immediately if tool not found
        if tool_name is None or tool_name not in VALID_TOOL_IDS:
            return {
                "status": "failure",
                "reason": "unknown_tool"
            }

        steps.append({
            "type": "tool",
            "name": tool_name,
            "input_text": segment.strip()
        })

    return steps
