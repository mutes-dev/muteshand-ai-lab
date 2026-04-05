from system.llm.adapter import generate_plan


def llm_entry(input_text: str):
    """
    LLM Entry Hook (Pre-Planner)

    Responsibilities:
    - call adapter
    - return raw input OR structured plan
    - DO NOT call planner
    - DO NOT modify structure
    - VALIDATE structure strictly per SYSTEM_CONTRACTS
    """

    # Try-except wrapper for adapter call
    try:
        result = generate_plan(input_text)
    except Exception:
        return input_text

    # Adapter failure dict → pass-through
    if isinstance(result, dict) and result.get("status") == "failure":
        return input_text

    # STRICT STRUCTURE VALIDATION
    # Output must be a list
    if not isinstance(result, list):
        return input_text

    # Output must not be empty
    if len(result) == 0:
        return input_text

    # Validate each item in the list
    for item in result:
        # Each item must be a dict
        if not isinstance(item, dict):
            return input_text

        # Each dict must have EXACT keys: {type, name, input_text}
        if set(item.keys()) != {"type", "name", "input_text"}:
            return input_text

        # type must be "tool" or "agent"
        if item["type"] not in ["tool", "agent"]:
            return input_text

        # name must be string
        if not isinstance(item["name"], str):
            return input_text

        # input_text must be string
        if not isinstance(item["input_text"], str):
            return input_text

    # All validation passed → return structured output
    return result
