# === LIVE STATE STREAMING (Phase 3) — OBSERVATIONAL ONLY ===
# Per HAND_ARCHITECTURE_V2: Streaming reflects state, never influences it
# Per CONTROL_MODEL: Events are advisory, non-authoritative
try:
    from system.interface import event_emitter as _event_emitter
except Exception:
    _event_emitter = None


def is_execution_valid(execution_result, step):
    """
    Execution validity gate.

    Per HAND_ARCHITECTURE_V2 Section 4 STEP COMPLETION:
    A step is complete ONLY if: execution success AND purpose_met AND validation passed.

    This function enforces the structural validity of the execution result:
    - status must be "success"
    - result field must exist and not be None
    - a real tool execution must have occurred (executed_input recorded on step)

    Per SYSTEM_GOALS_V2 Section 4: if any condition fails, step is NOT complete.

    MUST NOT modify execution_result.
    MUST NOT use heuristics or LLM inference.
    MUST NOT bypass system_entry.

    Returns:
        (True, None) if valid
        (False, reason_str) if invalid
    """
    if execution_result is None:
        return False, "no_execution_result"

    if execution_result.get("status") != "success":
        return False, "tool_failure"

    if "result" not in execution_result:
        return False, "missing_result"

    if execution_result.get("result") is None:
        return False, "missing_result"

    # A real tool execution MUST have been recorded.
    # Per HAND_ARCHITECTURE_V2 Section 17: all execution goes through system_entry.
    # step["executed_input"] is set by agent_executor only when system_entry ran.
    # If it is absent or empty, no real tool execution occurred.
    if not step.get("executed_input"):
        return False, "no_tool_execution"

    return True, None


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


def decide_next_action(validator_output, execution_result, step, context, memory_confidence=None, override_state=False):
    """
    Determines next action for a step.

    AUTHORITY: execution_result is the PRIMARY decision driver.

    Validator signals are advisory only and MUST NOT influence control flow.
    All retry and completion decisions are based solely on execution_result.

    Args:
        validator_output: Advisory validator output (NEVER used in decisions)
        execution_result: PRIMARY authority — sole basis for decisions
        step: The step dict (may be updated with advisory metadata)
        context: Workflow context dict
        memory_confidence: Optional advisory confidence from global memory
            (Phase 3A — MUST NOT change decision logic, MUST NOT trigger retry,
             MUST NOT override execution_result. Stored as metadata ONLY.)
        override_state: If True, escalation becomes completion per GOVERNANCE_CONTRACT

    Returns:
        "retry" | "complete" | "fail" | "block" | "escalate"

    Decision semantics (GOVERNANCE_CONTRACT):
        retry     — execution failed, retries remain
        block     — approval required before execution
        escalate  — execution failed, max retries reached (non-terminal, unless override)
        complete  — execution succeeded AND purpose_met (signals are advisory only)
        fail      — execution_result missing (system error only)
    """
    # === APPROVAL CHECK (GOVERNANCE_CONTRACT) ===
    # Governance is the SOLE authority for approval decisions.
    # Sets blocked_reason so runtime can identify approval-specific blocks.
    if _check_approval_required(step, context or {}):
        step["blocked_reason"] = "approval_required"
        return "block"

    # === ADVISORY SIGNALS (metadata only, NO decision influence) ===
    if validator_output:
        step["_validator_advisory"] = validator_output.get("reason")
        step["_validator_decision"] = validator_output.get("recommendation")
        step["_validator_signals"] = validator_output.get("signals")

    # === NOTIFICATIONS (Phase 3C — OUTPUT ONLY, POST-DECISION) ===
    # Per HAND_ARCHITECTURE_V2 Section 14: Notify for approvals, failures, completion
    # Per AUTHORITY_MODEL: Notifications are OUTPUT ONLY — emitted AFTER decision finalized
    # Per SYSTEM_GOALS_V2 Section 24: Smart filtering (approvals, failures, completion)
    # FAILURE-ISOLATED: Notification failure MUST NOT affect execution or decisions
    _decision_for_notify = None
    try:
        # Determine preliminary decision for notification (final decision returned below)
        if _check_approval_required(step, context or {}):
            _decision_for_notify = "block"
        elif execution_result and execution_result.get("status") == "failure":
            retries = step.get("retries", 0)
            risk = step.get("risk", "MEDIUM")
            max_retries = _get_risk_based_max_retries(risk)
            if retries < max_retries:
                _decision_for_notify = "retry"
            else:
                _decision_for_notify = "escalate"
        elif execution_result and execution_result.get("status") == "success":
            _decision_for_notify = "complete"
    except Exception:
        pass  # Continue with decision logic even if notification prep fails

    # === MEMORY CONFIDENCE (advisory metadata only — Phase 3A) ===
    # Per MEMORY_STORAGE_CONTRACT_V1: memory MUST NOT change decision outputs
    # Per AUTHORITY_MODEL: execution_result remains sole truth
    # Stored as step metadata for trace/observability ONLY — zero control impact
    if memory_confidence is not None:
        try:
            step["_memory_confidence"] = float(memory_confidence)
        except Exception:
            pass

    if step.get("mismatch") is True:
        step["_mismatch_advisory"] = True

    # === NOTIFICATION EMISSION (Phase 3C — OUTPUT ONLY) ===
    # Emit notification for the pre-determined decision
    # Per AUTHORITY_MODEL: Notifications are OUTPUT ONLY — zero control impact
    try:
        from system.interface.notification_manager import (
            notify_governance_retry,
            notify_governance_escalation,
            notify_approval_required
        )
        _workflow_id = context.get("workflow_id", "unknown") if context else "unknown"
        _step_id = step.get("id", "unknown")
        _risk_level = step.get("risk", "MEDIUM")
        _retries = step.get("retries", 0)
        
        if _decision_for_notify == "retry":
            notify_governance_retry(_step_id, _workflow_id, _retries + 1)
        elif _decision_for_notify == "escalate":
            notify_governance_escalation(_step_id, _workflow_id, reason="max_retries_reached")
        elif _decision_for_notify == "block":
            notify_approval_required(_step_id, _workflow_id, _risk_level)
    except Exception:
        # FAILURE-ISOLATED: Notification failure MUST NOT affect execution
        pass

    # === DECISION LOGIC: execution_result ONLY ===
    final_decision = None
    decision_reason = None

    if execution_result and execution_result.get("status") == "failure":
        # FAIL FAST: schema violations are non-retryable
        fail_reason = execution_result.get("reason", "")
        if fail_reason in ("missing_tool_call", "missing_tool_call_and_purpose"):
            step["status"] = "FAILED"
            final_decision = "fail"
            decision_reason = "schema_violation"

            # === LIVE STREAMING: GOVERNANCE DECISION (OBSERVATIONAL ONLY) ===
            if _event_emitter is not None:
                try:
                    _workflow_id = context.get("workflow_id", "unknown") if context else "unknown"
                    _step_id = step.get("id", "unknown")
                    _event_emitter.emit_governance_decision(
                        workflow_id=_workflow_id,
                        step_id=_step_id,
                        decision=final_decision,
                        reason=decision_reason,
                        execution_result_status="failure"
                    )
                except Exception:
                    pass

            return final_decision  # Immediate failure, no retry

        retries = step.get("retries", 0)
        # Apply risk-based retry limit per GOVERNANCE_CONTRACT
        risk = step.get("risk", "MEDIUM")
        max_retries = _get_risk_based_max_retries(risk)
        step["max_retries"] = max_retries  # Update step with risk-based limit

        if retries < max_retries:
            final_decision = "retry"
            decision_reason = f"retry_{retries + 1}_of_{max_retries}"
        else:
            # Per GOVERNANCE_CONTRACT Section 287-296:
            # IF override = ON → FAIL + CONTINUE (workflow continues, step is FAILED)
            # IF override = OFF AND importance = HIGH → BLOCK
            # IF override = OFF AND importance != HIGH → FAIL + CONTINUE
            if override_state:
                # Override ON: FAIL + CONTINUE (per GOVERNANCE_CONTRACT Section 289)
                final_decision = "fail"
                decision_reason = "max_retries_reached_override_continue"
            else:
                # Override OFF: escalate (BLOCK workflow) per GOVERNANCE_CONTRACT Section 293
                final_decision = "escalate"
                decision_reason = "max_retries_reached"

        # === LIVE STREAMING: GOVERNANCE DECISION (OBSERVATIONAL ONLY) ===
        if _event_emitter is not None:
            try:
                _workflow_id = context.get("workflow_id", "unknown") if context else "unknown"
                _step_id = step.get("id", "unknown")
                _event_emitter.emit_governance_decision(
                    workflow_id=_workflow_id,
                    step_id=_step_id,
                    decision=final_decision,
                    reason=decision_reason,
                    execution_result_status="failure"
                )
            except Exception:
                pass

        return final_decision

    if execution_result and execution_result.get("status") == "success":
        # COMPLETION RULE per GOVERNANCE_CONTRACT + HAND_ARCHITECTURE_V2 Section 4:
        # COMPLETE only if: execution success AND purpose_met AND execution valid
        # Signals are advisory only — MUST NOT influence this decision
        purpose_met = step.get("purpose_met", True)  # Default True if not set

        # === EXECUTION VALIDITY GATE ===
        # Per HAND_ARCHITECTURE_V2 Section 4: completion requires valid execution.
        # Checks: result exists, result not None, real tool ran (executed_input set).
        # MUST NOT modify execution_result. Purely structural gate.
        valid, validity_reason = is_execution_valid(execution_result, step)

        # === TRACE: EXECUTION VALIDATION (OBSERVABILITY — NO CONTROL IMPACT) ===
        # Stored as step metadata for trace/debug only.
        step["_execution_validity"] = {"valid": valid, "reason": validity_reason}

        if purpose_met and valid:
            final_decision = "complete"
            decision_reason = "purpose_met_and_execution_valid"

            # === LIVE STREAMING: GOVERNANCE DECISION (OBSERVATIONAL ONLY) ===
            if _event_emitter is not None:
                try:
                    _workflow_id = context.get("workflow_id", "unknown") if context else "unknown"
                    _step_id = step.get("id", "unknown")
                    _event_emitter.emit_governance_decision(
                        workflow_id=_workflow_id,
                        step_id=_step_id,
                        decision=final_decision,
                        reason=decision_reason,
                        execution_result_status="success"
                    )
                except Exception:
                    pass

            return final_decision
        else:
            # purpose not met or execution invalid — treat as retry-able failure
            risk = step.get("risk", "MEDIUM")
            max_retries = _get_risk_based_max_retries(risk)
            step["max_retries"] = max_retries
            if step.get("retries", 0) < max_retries:
                final_decision = "retry"
                decision_reason = "purpose_not_met_or_invalid" if not purpose_met else f"invalid_execution_{validity_reason}"
            else:
                final_decision = "escalate"
                decision_reason = "max_retries_reached"

            # === LIVE STREAMING: GOVERNANCE DECISION (OBSERVATIONAL ONLY) ===
            if _event_emitter is not None:
                try:
                    _workflow_id = context.get("workflow_id", "unknown") if context else "unknown"
                    _step_id = step.get("id", "unknown")
                    _event_emitter.emit_governance_decision(
                        workflow_id=_workflow_id,
                        step_id=_step_id,
                        decision=final_decision,
                        reason=decision_reason,
                        execution_result_status="success"
                    )
                except Exception:
                    pass

            return final_decision

    # No execution_result — system error, cannot determine outcome
    final_decision = "fail"

    # === LIVE STREAMING: GOVERNANCE DECISION (OBSERVATIONAL ONLY) ===
    # Per HAND_ARCHITECTURE_V2 Section 15: LIVE mode shows governance decisions
    # CALL AFTER: decision is determined
    # FAILURE-ISOLATED: Event emission failure must not affect execution
    if _event_emitter is not None:
        try:
            _workflow_id = context.get("workflow_id", "unknown") if context else "unknown"
            _step_id = step.get("id", "unknown")
            _exec_status = execution_result.get("status") if execution_result else None
            _event_emitter.emit_governance_decision(
                workflow_id=_workflow_id,
                step_id=_step_id,
                decision=final_decision,
                reason="no_execution_result",
                execution_result_status=_exec_status
            )
        except Exception:
            pass

    return final_decision
