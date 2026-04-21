def resolve_decision(validator_output, execution_result, context):
    """
    Determine final output based on execution truth.
    SINGLE SOURCE: execution_result only
    """

    # SINGLE SOURCE — execution_result only
    if execution_result is not None:
        return execution_result

    # DEFAULT — no result
    return None


def decide_next_action(validator_output, execution_result, step, context):
    """
    Determines next action for a step.

    Returns:
        "retry" | "continue" | "complete" | "fail"
    """
    # Failure path
    if execution_result and execution_result.get("status") == "failure":
        retries = step.get("retries", 0)
        max_retries = step.get("max_retries", 0)

        if retries < max_retries:
            return "retry"
        return "fail"

    # Validator advisory
    if validator_output and validator_output.get("decision") == "retry":
        return "retry"

    return "complete"
