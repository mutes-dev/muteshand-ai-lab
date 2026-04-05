import re

def parse(planner_output):
    """
    Parser - Non-blocking argument extraction.
    
    NEVER returns failure dict.
    ONLY extracts available arguments.
    """
    # If planner returned failure, pass it through for resolver to handle
    if isinstance(planner_output, dict) and planner_output.get("status") == "failure":
        return planner_output

    # Non-blocking: if not a list, return empty list
    if not isinstance(planner_output, list):
        return []

    result = []

    for step in planner_output:
        # Skip non-tool steps silently
        if step.get("type") != "tool":
            continue

        tool_name = step.get("name", "")
        input_text = step.get("input_text", "")

        # Extract numbers - may be empty
        numbers = re.findall(r"-?\d+", input_text)
        args = [int(n) for n in numbers]

        result.append({
            "tool": tool_name,
            "args": args
        })

    return result
