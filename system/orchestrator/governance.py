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

    Validator signals are advisory and MAY be evaluated by governance to trigger
    corrective actions (e.g. retry) when execution_result is successful but
    semantically invalid.

    Validator does NOT make decisions.
    Governance evaluates signals and determines the final action.

    Returns:
        "retry" | "complete" | "fail"
    """
    # === ADVISORY SIGNALS (metadata only, NO decision influence) ===
    if validator_output and validator_output.get("recommendation") == "retry":
        step["_validator_advisory"] = validator_output.get("reason", "unknown")

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

        # --- VALIDATOR SIGNAL CHECK (ADVISORY ONLY) ---
        if (
            validator_output
            and validator_output.get("reason") == "argument_mismatch"
            and step.get("retries", 0) == 0
        ):
            return "retry"

        # --- FINAL ANSWER SIGNAL CHECK (ADVISORY ONLY) ---
        signals = validator_output.get("signals", {}) if validator_output else {}
        if (
            signals.get("final_answer_correct") is False
            and step.get("retries", 0) == 0
        ):
            return "retry"

        return "complete"

    # No execution_result — cannot determine outcome
    return "fail"
