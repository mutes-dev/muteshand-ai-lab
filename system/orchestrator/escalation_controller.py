"""
ESCALATION CONTROLLER — Retry and Escalation Management

Responsibility:
- Manage hybrid retry model (bounded retries)
- Handle escalation triggers
- Route to user when internal resolution fails

Architecture Alignment:
- Section 6 of HAND_ARCHITECTURE.txt
- Governance decides (retry/escalate/complete), Controller executes
- Runtime delegates control logic to this module

Rules:
- MUST NOT loop infinitely
- MUST track retry history
- User escalation is not failure — it's controlled handoff
"""

from typing import Dict, Any, Optional, Tuple


def _structured_log(event_type, workflow_id, step_id, data):
    """Structured debug logger for runtime trace evidence."""
    import json
    log_entry = {
        "EVENT": event_type,
        "workflow_id": workflow_id,
        "step_id": step_id,
        "timestamp": __import__('datetime').datetime.now().isoformat(),
        "data": data
    }
    print(f"[RUNTIME_TRACE] {json.dumps(log_entry, default=str)}")


def _normalize_action(action: str) -> str:
    """
    Normalize escalation action to valid contract value.
    
    Ensures controller ALWAYS returns a valid action.
    Invalid actions are normalized to BLOCKED (fail-safe).
    
    Args:
        action: The action string to normalize
        
    Returns:
        Valid action: "RETRY", "COMPLETE", or "BLOCKED"
    """
    valid = {"RETRY", "COMPLETE", "BLOCKED"}
    if action not in valid:
        return "BLOCKED"
    return action


def handle_retry(
    step: Dict[str, Any],
    workflow: Dict[str, Any],
    next_decision,
    governance_decision=None
) -> Dict[str, Any]:
    """
    Handle retry logic for a step.
    
    Governance has decided "retry" — this function executes that decision.
    
    Args:
        step: The step being processed
        workflow: The parent workflow
        next_decision: The governance decision (should be "retry")
        governance_decision: Full GovernanceDecision object with retry metadata
            (retry_strategy, retry_guidance, retry_remediation) - Phase 1 propagation
    
    Returns:
        Dict with explicit action:
        - {"action": "RETRY"} to continue to next iteration (retry)
        - {"action": "BLOCKED"} to break out of step loop (max retries reached)
    
    State mutations (intentional - execution state management):
        - step["retries"]: incremented
        - step["status"]: may be updated to PENDING or FAILED
        - step["output"]: cleared for clean retry
        - step["execution_result"]: preserved (NOT cleared) for deterministic retry
        - step["executed_input"]: preserved (NOT cleared) for deterministic retry
    """
    workflow_id = workflow.get("id", "unknown")
    step_id = step.get("id", "unknown")

    # RUNTIME TRACE: Retry handler entry
    _structured_log("RETRY_HANDLER_ENTRY", workflow_id, step_id, {
        "next_decision": next_decision,
        "current_retries": step.get("retries", 0),
        "current_status": step.get("status"),
        "current_input": step.get("input"),
        "original_input": step.get("_original_input"),
        "validator_signals": step.get("_validator_signals"),
        "extracted_constraints": step.get("_extracted_constraints")
    })

    # Phase 2: Governance metadata visibility - log governance-approved retry metadata
    retry_strategy = None
    if governance_decision is not None:
        # Extract retry metadata from GovernanceDecision for observability
        retry_strategy = getattr(governance_decision, 'retry_strategy', None)
        retry_guidance = getattr(governance_decision, 'retry_guidance', None)
        retry_remediation = getattr(governance_decision, 'retry_remediation', None)
        
        _structured_log("RETRY_GOVERNANCE_METADATA", workflow_id, step_id, {
            "governance_decision_type": type(governance_decision).__name__,
            "retry_strategy": str(retry_strategy) if retry_strategy else None,
            "retry_guidance_present": retry_guidance is not None,
            "retry_remediation_present": retry_remediation is not None,
            "governance_action": getattr(governance_decision, 'action', None),
            "governance_reason": getattr(governance_decision, 'reason', None)
        })
    else:
        # Phase 2: Backward compatibility - no governance decision provided
        _structured_log("RETRY_GOVERNANCE_FALLBACK", workflow_id, step_id, {
            "reason": "governance_decision_not_provided",
            "fallback_strategy": "same",
            "note": "Using default retry behavior for backward compatibility"
        })

    if next_decision != "retry":
        _structured_log("RETRY_HANDLER_EXIT", workflow_id, step_id, {
            "action": "COMPLETE",
            "reason": "next_decision_not_retry"
        })
        return {"action": _normalize_action("COMPLETE")}

    # PRESERVE ORIGINAL INPUT (only once)
    if "_original_input" not in step:
        step["_original_input"] = step["input"]
        _structured_log("RETRY_ORIGINAL_INPUT_CAPTURED", workflow_id, step_id, {
            "original_input": step["_original_input"]
        })

    retries_before = step.get("retries", 0)
    step["retries"] += 1
    retries_after = step["retries"]

    _structured_log("RETRY_INCREMENT", workflow_id, step_id, {
        "retries_before": retries_before,
        "retries_after": retries_after,
        "max_retries": step.get("max_retries", 3)
    })

    # Max retries check: convert retry to escalation
    if step["retries"] >= step["max_retries"]:
        from system.orchestrator.workflow_control import request_step_transition as _rst_ec, _update_workflow_state
        _rst_ec(step, "FAILED", "max_retries_exceeded", _internal=True)
        workflow_id_inner = workflow.get("id", "unknown_workflow")
        workflow["error"] = "max_retries_exceeded"
        _update_workflow_state(workflow_id_inner, "BLOCKED", "max_retries_exceeded")  # Authoritative registry ONLY

        _structured_log("RETRY_HANDLER_BLOCKED", workflow_id, step_id, {
            "reason": "max_retries_exceeded",
            "retries": step["retries"],
            "max_retries": step.get("max_retries", 3)
        })

        return {"action": _normalize_action("BLOCKED")}

    # Prepare for retry - state remains ACTIVE (per STATE_TRANSITIONS_CONTRACT_V1: RETRY does NOT change state)
    # retry_count distinguishes retry from new execution
    # while preserving execution continuity semantics
    from system.orchestrator.workflow_control import request_step_transition as _rst_ec
    if step.get("status") != "ACTIVE":
        _rst_ec(step, "ACTIVE", "retry_prepare", _internal=True)
    # === FIX B: STATE INVARIANT — ACTIVE MUST NOT carry blocked_reason (Phase 1B) ===
    # Per DEPENDENCY_MODEL_CONTRACT_V1: a step cannot be simultaneously ACTIVE and
    # dependency-blocked.  blocked_reason is only valid on BLOCKED steps.
    step.pop("blocked_reason", None)
    # Mark as retry-pending so scheduler excludes this step from the active_steps
    # boundary guard (which blocks new group formation) while still allowing it to
    # be picked up as a candidate for re-dispatch.
    step["_retry_pending"] = True

    # Phase 1: Extract governance-approved retry_guidance for downstream propagation
    # Store on step for step_executor/agent_executor access (observational only for now)
    governance_retry_guidance = None
    if governance_decision is not None:
        _guidance_obj = getattr(governance_decision, 'retry_guidance', None)
        if _guidance_obj is not None:
            # Extract guidance string from RetryGuidance object
            governance_retry_guidance = getattr(_guidance_obj, 'rationale', None)
            step["_governance_retry_guidance"] = governance_retry_guidance
            _structured_log("RETRY_GUIDANCE_EXTRACTED", workflow_id, step_id, {
                "governance_retry_guidance": governance_retry_guidance,
                "retry_strategy": str(getattr(governance_decision, 'retry_strategy', None)),
                "source": "GovernanceDecision.retry_guidance"
            })
    
    # CONTROL_MODEL RULE 6: retry guidance is execution-driven only
    # Validator reason MUST NOT influence retry content
    # Phase 3: Hard-coded guidance injection requires governance authorization
    
    # Extract retry_strategy for authorization check
    guidance_retry_strategy = None
    if governance_decision is not None:
        guidance_retry_strategy = getattr(governance_decision, 'retry_strategy', None)
    
    # Hard-coded guidance definition (unchanged)
    retry_guidance = (
        "The previous attempt did not complete successfully.\n"
        "Review the operation and arguments, then try again."
    )
    
    # Inject retry guidance ONCE (prevent stacking)
    # Phase 3: Only inject if governance authorizes default retry behavior
    if step.get("retries", 0) == 1:
        # Authorization check: inject only if retry_strategy allows
        # - If governance_decision is None: allow (backward compatibility)
        # - If retry_strategy is "same": allow (default retry behavior)
        # - If retry_strategy is "constraint_refined": skip (governance handles refinement)
        guidance_authorized = (
            governance_decision is None or  # Backward compatibility
            guidance_retry_strategy == "same"  # Default retry behavior
        )
        
        _structured_log("RETRY_GUIDANCE_AUTHORIZATION", workflow_id, step_id, {
            "governance_decision_present": governance_decision is not None,
            "retry_strategy": str(guidance_retry_strategy) if guidance_retry_strategy else None,
            "guidance_authorized": guidance_authorized,
            "authorization_reason": (
                "backward_compatibility" if governance_decision is None else
                "retry_strategy_same" if guidance_retry_strategy == "same" else
                "retry_strategy_not_same"
            )
        })
        
        if guidance_authorized:
            input_before_guidance = step["input"]
            step["input"] = f"{step['input']}\n\n{retry_guidance}"
            _structured_log("RETRY_GUIDANCE_INJECTED", workflow_id, step_id, {
                "input_before": input_before_guidance,
                "input_after": step["input"],
                "guidance": retry_guidance,
                "governance_authorized": True,
                "retry_strategy": str(guidance_retry_strategy) if guidance_retry_strategy else None
            })
        else:
            _structured_log("RETRY_GUIDANCE_SKIPPED", workflow_id, step_id, {
                "reason": "governance_strategy_not_same",
                "retry_strategy": str(guidance_retry_strategy),
                "note": "Hard-coded guidance skipped - retry_strategy does not authorize default guidance injection"
            })

    # Phase 2: CONSTRAINT-AWARE RETRY with governance authorization
    # Check governance-approved retry_strategy for constraint refinement authorization
    retry_strategy = None
    if governance_decision is not None:
        retry_strategy = getattr(governance_decision, 'retry_strategy', None)
    
    # Read constraint info for potential refinement (advisory context only)
    # Actual refinement authorization comes from governance retry_strategy
    signals = step.get("_validator_signals", {}) or {}
    extracted_constraints = step.get("_extracted_constraints", {})
    constraint_ok = signals.get("constraint_ok", True)
    current_retries = step.get("retries", 0)

    _structured_log("RETRY_STRATEGY_CHECK", workflow_id, step_id, {
        "current_retries": current_retries,
        "governance_retry_strategy": retry_strategy,
        "constraint_ok": constraint_ok,
        "extracted_constraints_present": bool(extracted_constraints),
        "validator_signals_present": bool(signals),
        "will_apply_constraint_retry": retry_strategy == "constraint_refined" and current_retries >= 1 and bool(extracted_constraints)
    })

    # Phase 2: Execute constraint-aware refinement ONLY if governance-authorized
    if retry_strategy == "constraint_refined" and current_retries >= 1 and extracted_constraints:
        fmt = extracted_constraints.get("format")
        retry_instruction = None

        if fmt == "count":
            retry_instruction = "Return ONLY the number."
        elif fmt == "words":
            retry_instruction = "Respond in words only."
        elif fmt == "list":
            retry_instruction = "Return the result as a list."
        elif fmt == "first_word":
            retry_instruction = "Return only the first word."
        elif fmt == "empty":
            retry_instruction = "Return nothing."

        if retry_instruction:
            # PREVENT STACKING: Always rebuild from _original_input
            input_before_mutation = step.get("input")
            original_input = step.get("_original_input", step["input"])
            step["input"] = f"{original_input}\n\nIMPORTANT: {retry_instruction}"

            _structured_log("RETRY_INPUT_MUTATED", workflow_id, step_id, {
                "input_before": input_before_mutation,
                "input_after": step["input"],
                "original_input": original_input,
                "retry_instruction": retry_instruction,
                "constraint_format": fmt,
                "constraint_violation": signals.get("constraint_violation"),
                "governance_authorized": True,
                "retry_strategy": retry_strategy
            })

            # DEBUG VISIBILITY: Expose retry modification details
            if step.get("retries", 0) >= 1:
                print("\n[RETRY MODIFICATION - GOVERNANCE AUTHORIZED]")
                print(f"Retry Strategy: {retry_strategy}")
                print("Original Input:")
                print(step.get("_original_input"))
                print("\nExtracted Constraints:")
                print(step.get("_extracted_constraints"))
                print("\nValidator Signals:")
                print(step.get("_validator_signals"))
                print("\nRetry Instruction:")
                print(retry_instruction)
                print("\nFinal Retry Input:")
                print(step["input"])
                print("[END RETRY MODIFICATION]\n")
    else:
        # Phase 2: Log when constraint refinement is NOT applied
        if not constraint_ok and extracted_constraints:
            _structured_log("RETRY_CONSTRAINT_SKIPPED", workflow_id, step_id, {
                "reason": "governance_strategy_not_constraint_refined",
                "governance_retry_strategy": retry_strategy,
                "constraint_ok": constraint_ok,
                "has_constraints": bool(extracted_constraints),
                "note": "Constraint violation present but governance did not authorize constraint_refined strategy"
            })

    # --- FORCE CLEAN RETRY ---
    # PRESERVE executed_input for deterministic retry (REQUIRED)
    cleared_execution_result = step.pop("execution_result", None)
    cleared_output = step.pop("output", None)

    _structured_log("RETRY_CLEANUP", workflow_id, step_id, {
        "cleared_execution_result": cleared_execution_result is not None,
        "cleared_output": cleared_output is not None,
        "final_input": step.get("input"),
        "final_retries": step.get("retries")
    })

    _structured_log("RETRY_HANDLER_EXIT", workflow_id, step_id, {
        "action": "RETRY",
        "final_retries": step.get("retries"),
        "final_input_preview": step.get("input", "")[:100]
    })

    return {"action": _normalize_action("RETRY")}


def handle_escalation(
    step: Dict[str, Any],
    workflow: Dict[str, Any],
    next_decision,
    exec_res: Dict,
    governance_decision=None
) -> Dict[str, Any]:
    """
    Handle escalation logic for a step.
    
    Governance has decided "escalate" or "fail" — this function executes that decision.
    
    Args:
        step: The step being processed
        workflow: The parent workflow
        next_decision: The governance decision ("escalate" or "fail")
        exec_res: The execution result from the step
        governance_decision: Full GovernanceDecision object with escalation metadata
            (escalation_level, authority_source) - Phase 1 propagation
    
    Returns:
        Dict with explicit action:
        - {"action": "BLOCKED", "result": failure_dict} when escalation occurs
        - {"action": "COMPLETE"} for non-escalation paths (no-op)
    
    State mutations (intentional - execution state management):
        - step["status"]: set to BLOCKED
        - workflow["status"]: set to BLOCKED
        - workflow["error"]: set to "max_retries_exceeded" or "system_error"
        - workflow["output"]: may be set from exec_res if None
    """
    workflow_id = workflow.get("id", "unknown")
    step_id = step.get("id", "unknown")
    
    # Phase 1: Governance metadata visibility - log governance-approved escalation metadata
    if governance_decision is not None:
        escalation_level = getattr(governance_decision, 'escalation_level', None)
        authority_source = getattr(governance_decision, 'authority_source', None)
        
        _structured_log("ESCALATION_GOVERNANCE_METADATA", workflow_id, step_id, {
            "governance_decision_type": type(governance_decision).__name__,
            "escalation_level": escalation_level,
            "authority_source": authority_source,
            "governance_action": getattr(governance_decision, 'action', None),
            "governance_reason": getattr(governance_decision, 'reason', None)
        })
    
    if next_decision not in ("escalate", "fail"):
        return {"action": _normalize_action("COMPLETE")}
    
    # CONTROL_MODEL RULE 7: escalate = max retries exceeded (non-terminal)
    # 'fail' reserved for system error (missing execution_result)
    from system.orchestrator.workflow_control import request_step_transition as _rst_ec, _update_workflow_state
    _rst_ec(step, "BLOCKED", "escalation", _internal=True)
    workflow_id = workflow.get("id", "unknown_workflow")
    _err = "max_retries_exceeded" if next_decision == "escalate" else "system_error"
    workflow["error"] = _err
    _update_workflow_state(workflow_id, "BLOCKED", _err)  # Authoritative registry ONLY
    
    # Ensure workflow has output for failure case
    if workflow.get("output") is None and exec_res is not None:
        workflow["output"] = exec_res
    
    # Extract failure reason for potential return
    execution_result = workflow.get("output")
    failure_reason = None
    if execution_result is not None and execution_result.get("status") == "failure":
        failure_reason = execution_result.get("reason")
        if workflow.get("output") is None:
            # Search for execution_result in steps
            for s in reversed(workflow.get("steps", [])):
                if s.get("execution_result") is not None:
                    workflow["output"] = s.get("execution_result")
                    failure_reason = s.get("execution_result", {}).get("reason")
                    break
    
    failure_result = {"status": "failure", "reason": failure_reason} if failure_reason else None
    return {"action": _normalize_action("BLOCKED"), "result": failure_result}


def get_escalation_status(
    step: Dict[str, Any],
    workflow: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Get current escalation status for reporting/debugging.
    
    Pure read-only function — no state mutation.
    """
    return {
        "step_id": step.get("id"),
        "step_status": step.get("status"),
        "workflow_status": workflow.get("status"),
        "retries": step.get("retries", 0),
        "max_retries": step.get("max_retries", 0),
        "error": workflow.get("error")
    }
