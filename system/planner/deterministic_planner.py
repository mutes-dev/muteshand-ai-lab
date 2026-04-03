def plan(user_input: str) -> list:
    import json
    import os

    tools_path = os.path.join("memory", "tool_index", "tools.json")

    with open(tools_path, "r") as f:
        tool_index = json.load(f)

    if isinstance(tool_index, dict):
        VALID_TOOL_IDS = set(tool["name"] for tool in tool_index.values())
    elif isinstance(tool_index, list):
        VALID_TOOL_IDS = set(tool["name"] for tool in tool_index)
    else:
        raise ValueError("Invalid tool_index structure")

    TOOL_RULES = [
        ("add", "add_numbers"),
        ("multiply", "multiply_numbers"),
    ]

    segments = user_input.split(" then ")

    steps = []

    for segment in segments:
        segment_lower = segment.lower()

        tool_name = "unknown"

        for keyword, tool in TOOL_RULES:
            if keyword in segment_lower:
                tool_name = tool
                break

        if tool_name not in VALID_TOOL_IDS:
            tool_name = "unknown"

        steps.append({
            "type": "tool",
            "name": tool_name,
            "input_text": segment.strip()
        })

    return steps
