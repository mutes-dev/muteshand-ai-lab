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


def _get_risk_based_max_retries(risk_level: str) -> int:
    """Return max retries based on risk level per GOVERNANCE_CONTRACT."""
    risk_limits = {
        "LOW": 5,
        "MEDIUM": 3,
        "HIGH": 1
    }
    return risk_limits.get(risk_level, 2)


def _check_approval_required(step: dict, context: dict) -> bool:
    """Check if approval is required for this step."""
    # Placeholder: approval_required flag from classification or step
    if step.get("approval_required"):
        return True
    if context.get("approval_required"):
        return True
    # HIGH risk steps may require approval
    if step.get("risk") == "HIGH" and step.get("importance") == "HIGH":
        return True
    return False


def decide_next_action(validator_output, execution_result, step, context):
    """
    Determines next action for a step.

    AUTHORITY: execution_result is the PRIMARY decision driver.

    Validator signals are advisory only and MUST NOT influence control flow.
    All retry and completion decisions are based solely on execution_result.

    Returns:
        "retry" | "complete" | "fail" | "block" | "escalate"

    Decision semantics (GOVERNANCE_CONTRACT):
        retry     — execution failed, retries remain
        block     — approval required before execution
        escalate  — execution failed, max retries reached (non-terminal)
        complete  — execution succeeded AND purpose_met (signals are advisory only)
        fail      — execution_result missing (system error only)
    """
    # === APPROVAL CHECK (GOVERNANCE_CONTRACT) ===
    if _check_approval_required(step, context or {}):
        return "block"

    # === ADVISORY SIGNALS (metadata only, NO decision influence) ===
    if validator_output:
        step["_validator_advisory"] = validator_output.get("reason")
        step["_validator_decision"] = validator_output.get("recommendation")
        step["_validator_signals"] = validator_output.get("signals")

    if step.get("mismatch") is True:
        step["_mismatch_advisory"] = True

    # === DECISION LOGIC: execution_result ONLY ===
    if execution_result and execution_result.get("status") == "failure":
        # FAIL FAST: schema violations are non-retryable
        fail_reason = execution_result.get("reason", "")
        if fail_reason == "missing_tool_call":
            step["status"] = "FAILED"
            return "fail"  # Immediate failure, no retry

        retries = step.get("retries", 0)
        # Apply risk-based retry limit per GOVERNANCE_CONTRACT
        risk = step.get("risk", "MEDIUM")
        max_retries = _get_risk_based_max_retries(risk)
        step["max_retries"] = max_retries  # Update step with risk-based limit

        if retries < max_retries:
            return "retry"
        return "escalate"  # CONTROL_MODEL RULE 7: escalation is NOT failure

    if execution_result and execution_result.get("status") == "success":
        # COMPLETION RULE per GOVERNANCE_CONTRACT:
        # COMPLETE only if: execution success AND purpose_met
        # Signals are advisory only — MUST NOT influence this decision
        purpose_met = step.get("purpose_met", True)  # Default True if not set

        if purpose_met:
            return "complete"
        else:
            # purpose not met — treat as retry-able failure
            risk = step.get("risk", "MEDIUM")
            max_retries = _get_risk_based_max_retries(risk)
            step["max_retries"] = max_retries
            if step.get("retries", 0) < max_retries:
                return "retry"
            return "escalate"

    # No execution_result — system error, cannot determine outcome
    return "fail"
