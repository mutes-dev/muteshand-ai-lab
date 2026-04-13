def evaluate(input_text, tool_name, args, result, status):
    # RULE 1 — TOOL FAILURE
    if status == "failure":
        return {"decision": "retry", "reason": "tool_failure"}

    math_tools = {"add_numbers", "subtract_numbers", "multiply_numbers", "divide_numbers"}

    # RULE 2 — SIMPLE MATH CHECK
    if tool_name in math_tools and args and len(args) >= 2:
        try:
            a, b = args[0], args[1]

            if tool_name == "add_numbers":
                expected = a + b
            elif tool_name == "subtract_numbers":
                expected = a - b
            elif tool_name == "multiply_numbers":
                expected = a * b
            elif tool_name == "divide_numbers":
                if b == 0:
                    return {"decision": "retry", "reason": "tool_failure"}
                expected = a / b

            if abs(expected - result) >= 1e-6:
                return {"decision": "retry", "reason": "incorrect_output"}

        except Exception:
            return {"decision": "retry", "reason": "incorrect_output"}

    # RULE 3 — TOOL MISMATCH
    input_lower = input_text.lower()

    if "subtract" in input_lower and tool_name == "add_numbers":
        return {"decision": "retry", "reason": "tool_mismatch"}

    if "add" in input_lower and tool_name == "subtract_numbers":
        return {"decision": "retry", "reason": "tool_mismatch"}

    # RULE 4 — UNNECESSARY TOOL
    if any(word in input_lower for word in ["what", "who", "why", "explain"]) and tool_name in math_tools:
        return {"decision": "retry", "reason": "unnecessary_tool"}

    # RULE 6 — RESULT TYPE VALIDATION
    if tool_name in math_tools:
        if not isinstance(result, (int, float)):
            return {"decision": "retry", "reason": "invalid_result_type"}

    # RULE 7 — ARGUMENT COUNT SAFETY
    if tool_name in math_tools:
        if not args or len(args) != 2:
            return {"decision": "retry", "reason": "invalid_arguments"}

    # RULE 8 — NEGATIVE / EDGE DOMAIN CHECK (SAFE ONLY)
    if tool_name == "divide_numbers":
        if args and len(args) == 2 and args[1] == 0:
            return {"decision": "retry", "reason": "division_by_zero"}

    # RULE 9 — OUTPUT FORMAT SANITY
    if isinstance(result, str):
        if not any(char.isdigit() for char in result):
            return {"decision": "retry", "reason": "non_numeric_output"}

    # RULE 5 — DEFAULT
    return {"decision": "accept"}
