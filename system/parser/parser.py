import re

def parse(planner_output):
    if isinstance(planner_output, dict) and planner_output["status"] == "failure":
        return planner_output

    if not isinstance(planner_output, list):
        return {
            "status": "failure",
            "reason": "argument_parse_error"
        }

    if len(planner_output) == 0:
        return {
            "status": "failure",
            "reason": "argument_parse_error"
        }

    result = []

    for step in planner_output:
        if step["type"] != "tool":
            return {
                "status": "failure",
                "reason": "unsupported_step_type"
            }

        tool_name = step["name"]

        numbers = re.findall(r"-?\d+", step["input_text"])
        args = [int(n) for n in numbers]

        if len(args) == 0:
            return {
                "status": "failure",
                "reason": "argument_parse_error"
            }

        result.append({
            "tool": tool_name,
            "args": args
        })

    return result
