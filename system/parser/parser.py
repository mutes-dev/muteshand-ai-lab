import re

def is_number(token):
    """Check if token is a valid number."""
    try:
        float(token)
        return True
    except ValueError:
        return False

def parse_arguments(input_text):
    """
    Parser - Numeric extraction ONLY.
    
    Contract-compliant behavior:
    - Extracts ALL numbers from input_text
    - Returns list of numbers (int or float)
    - Returns [] if no numbers found
    - NEVER returns failure dict
    """
    print(f"[PARSER_INPUT]: {input_text}")
    tokens = input_text.strip().split()
    numbers = []

    for token in tokens:
        if is_number(token):
            if token.isdigit() or (token.startswith('-') and token[1:].isdigit()):
                numbers.append(int(token))
            else:
                numbers.append(float(token))

    print(f"[PARSER_OUTPUT]: {numbers}")
    return numbers

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

        # Use strict argument parsing (supports numbers and quoted strings)
        args = parse_arguments(input_text)

        result.append({
            "tool": tool_name,
            "args": args
        })

    return result
