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
        "retry" | "complete" | "escalate" | "fail"

    Decision semantics (CONTROL_MODEL):
        retry     — execution failed, retries remain
        escalate  — execution failed, max retries reached (non-terminal)
        complete  — execution succeeded
        fail      — execution_result missing (system error only)
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
        return "escalate"  # CONTROL_MODEL RULE 7: escalation is NOT failure

    if execution_result and execution_result.get("status") == "success":
        return "complete"

    # No execution_result — system error, cannot determine outcome
    return "fail"
