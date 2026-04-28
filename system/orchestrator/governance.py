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

    AUTHORITY: execution_result is the PRIMARY decision driver.

    Validator signals are advisory only and MUST NOT influence control flow.
    All retry and completion decisions are based solely on execution_result.

    Returns:
        "retry" | "complete" | "fail"
    """
    # === ADVISORY SIGNALS (metadata only, NO decision influence) ===
    if validator_output:
        step["_validator_advisory"] = validator_output.get("reason")
        step["_validator_decision"] = validator_output.get("recommendation")
        step["_validator_signals"] = validator_output.get("signals")

    if step.get("mismatch") is True:
        step["_mismatch_advisory"] = True

    # === DECISION LOGIC: execution_result ONLY ===
    if execution_result and execution_result.get("status") == "failure":
        retries = step.get("retries", 0)
        max_retries = step.get("max_retries", 0)

        if retries < max_retries:
            return "retry"
        return "fail"

    if execution_result and execution_result.get("status") == "success":

        # Validator signals are advisory only

        # No decision impact per AUTHORITY_MODEL

        pass

        # Validator signals are advisory only

        # No decision impact per AUTHORITY_MODEL

        pass

        return "complete"

    # No execution_result — cannot determine outcome
    return "fail"
