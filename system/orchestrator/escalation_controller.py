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
    next_decision: str
) -> Dict[str, Any]:
    """
    Handle retry logic for a step.
    
    Governance has decided "retry" — this function executes that decision.
    
    Args:
        step: The step being processed
        workflow: The parent workflow
        next_decision: The governance decision (should be "retry")
    
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
        step["status"] = "FAILED"
        # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Runtime registry is sole authority
        from system.orchestrator.workflow_control import _update_workflow_state
        workflow_id_inner = workflow.get("id", "unknown_workflow")
        workflow["status"] = "BLOCKED"  # Compatibility mirror
        workflow["error"] = "max_retries_exceeded"
        _update_workflow_state(workflow_id_inner, "BLOCKED", "max_retries_exceeded")  # Authoritative registry

        _structured_log("RETRY_HANDLER_BLOCKED", workflow_id, step_id, {
            "reason": "max_retries_exceeded",
            "retries": step["retries"],
            "max_retries": step.get("max_retries", 3)
        })

        return {"action": _normalize_action("BLOCKED")}

    # Prepare for retry - state remains ACTIVE (per STATE_TRANSITIONS_CONTRACT_V1: RETRY does NOT change state)
    # retry_count distinguishes retry from new execution
    # while preserving execution continuity semantics
    step["status"] = "ACTIVE"
    # === FIX B: STATE INVARIANT — ACTIVE MUST NOT carry blocked_reason (Phase 1B) ===
    # Per DEPENDENCY_MODEL_CONTRACT_V1: a step cannot be simultaneously ACTIVE and
    # dependency-blocked.  blocked_reason is only valid on BLOCKED steps.
    step.pop("blocked_reason", None)
    # Mark as retry-pending so scheduler excludes this step from the active_steps
    # boundary guard (which blocks new group formation) while still allowing it to
    # be picked up as a candidate for re-dispatch.
    step["_retry_pending"] = True

    # CONTROL_MODEL RULE 6: retry guidance is execution-driven only
    # Validator reason MUST NOT influence retry content
    retry_guidance = (
        "The previous attempt did not complete successfully.\n"
        "Review the operation and arguments, then try again."
    )

    # Inject retry guidance ONCE (prevent stacking)
    if step.get("retries", 0) == 1:
        input_before_guidance = step["input"]
        step["input"] = f"{step['input']}\n\n{retry_guidance}"
        _structured_log("RETRY_GUIDANCE_INJECTED", workflow_id, step_id, {
            "input_before": input_before_guidance,
            "input_after": step["input"],
            "guidance": retry_guidance
        })

    # CONSTRAINT-AWARE RETRY: Build constraint instruction AFTER retries incremented
    # Only apply on retry attempts (retries >= 1), never on first attempt
    signals = step.get("_validator_signals", {}) or {}
    extracted_constraints = step.get("_extracted_constraints", {})
    constraint_ok = signals.get("constraint_ok", True)
    current_retries = step.get("retries", 0)

    _structured_log("RETRY_CONSTRAINT_CHECK", workflow_id, step_id, {
        "current_retries": current_retries,
        "constraint_ok": constraint_ok,
        "extracted_constraints": extracted_constraints,
        "validator_signals": signals,
        "will_apply_constraint_retry": current_retries >= 1 and not constraint_ok and bool(extracted_constraints)
    })

    if current_retries >= 1 and not constraint_ok and extracted_constraints:
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
                "constraint_violation": signals.get("constraint_violation")
            })

            # DEBUG VISIBILITY: Expose retry modification details
            if step.get("retries", 0) >= 1:
                print("\n[RETRY MODIFICATION]")
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
    next_decision: str,
    exec_res: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Handle escalation logic for a step.
    
    Governance has decided "escalate" or "fail" — this function executes that decision.
    
    Args:
        step: The step being processed
        workflow: The parent workflow
        next_decision: The governance decision ("escalate" or "fail")
        exec_res: The execution result from the step
    
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
    if next_decision not in ("escalate", "fail"):
        return {"action": _normalize_action("COMPLETE")}
    
    # CONTROL_MODEL RULE 7: escalate = max retries exceeded (non-terminal)
    # 'fail' reserved for system error (missing execution_result)
    step["status"] = "BLOCKED"
    # Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Runtime registry is sole authority
    from system.orchestrator.workflow_control import _update_workflow_state
    workflow_id = workflow.get("id", "unknown_workflow")
    workflow["status"] = "BLOCKED"  # Compatibility mirror
    workflow["error"] = "max_retries_exceeded" if next_decision == "escalate" else "system_error"
    _update_workflow_state(workflow_id, "BLOCKED", workflow["error"])  # Authoritative registry
    
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
