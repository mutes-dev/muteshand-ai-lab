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
    if next_decision != "retry":
        return {"action": _normalize_action("COMPLETE")}
    
    step["retries"] += 1
    
    # Max retries check: convert retry to escalation
    if step["retries"] >= step["max_retries"]:
        step["status"] = "FAILED"
        workflow["status"] = "BLOCKED"
        workflow["error"] = "max_retries_exceeded"
        return {"action": _normalize_action("BLOCKED")}
    
    # Prepare for retry
    step["status"] = "PENDING"
    
    # CONTROL_MODEL RULE 6: retry guidance is execution-driven only
    # Validator reason MUST NOT influence retry content
    retry_guidance = (
        "The previous attempt did not complete successfully.\n"
        "Review the operation and arguments, then try again."
    )
    
    # Inject retry guidance ONCE (prevent stacking)
    if step.get("retries", 0) == 1:
        step["input"] = f"{step['input']}\n\n{retry_guidance}"
    
    # --- FORCE CLEAN RETRY ---
    # PRESERVE executed_input for deterministic retry (REQUIRED)
    step.pop("execution_result", None)
    step.pop("output", None)
    
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
    workflow["status"] = "BLOCKED"
    workflow["error"] = "max_retries_exceeded" if next_decision == "escalate" else "system_error"
    
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
