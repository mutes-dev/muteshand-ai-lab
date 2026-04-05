from system.entry.llm_entry import llm_entry


def route_input(input_text):
    """
    Entry Router (Flow Selector)

    Responsibilities:
    - route ALL raw strings to planner
    - route structured plans to direct execution
    - return routing decision ONLY

    DO NOT:
    - inspect content
    - split input
    - modify structure
    """
    # Case 1: dict with failure status → pass through unchanged
    if isinstance(input_text, dict) and input_text.get("status") == "failure":
        return input_text

    # Case 2: string → planner path (NO inspection, NO splitting)
    if isinstance(input_text, str):
        return {
            "mode": "planner",
            "data": input_text
        }

    # Case 3: structured plan (list) → direct execution path
    if isinstance(input_text, list):
        return {
            "mode": "direct_plan",
            "data": input_text
        }

    # Fail-safe → planner path
    return {
        "mode": "planner",
        "data": input_text
    }
