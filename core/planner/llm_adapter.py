def generate_plan(input_text: str):
    """
    LLM Adapter Layer

    Current behavior:
    - No model configured
    - Must return controlled failure

    DO NOT:
    - call any API
    - simulate responses
    - generate plans
    """

    return {
        "status": "failure",
        "reason": "llm_not_configured"
    }
