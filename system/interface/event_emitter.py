"""
EVENT EMITTER — LIVE STATE STREAMING (CONTRACT-SAFE)

Per HAND_ARCHITECTURE_V2:
- Streaming reflects execution state
- Never influences execution

Per CONTROL_MODEL.txt:
- All signals are advisory, optional, non-authoritative
- execution_result defines truth

Per TRACE_LOGGING_CONTRACT_V1:
- UI must not derive control logic from trace
- Use STATE for UI, not trace

COMPLIANCE:
- Wrapped in try/except — NEVER raises
- NEVER blocks execution
- NEVER returns anything
- Emits AFTER actual events (not before)

EVENT TYPES:
- step_started: Step began execution
- step_completed: Step finished (success or failure)
- governance_decision: Governance made a decision
- state_transition: Workflow/step state changed
- workflow_started: Workflow execution began
- workflow_completed: Workflow execution finished
"""

from typing import Any, Dict, Optional
from datetime import datetime

from system.interface.event_bus import publish_event


# Event type constants
EVENT_STEP_STARTED = "step_started"
EVENT_STEP_COMPLETED = "step_completed"
EVENT_GOVERNANCE_DECISION = "governance_decision"
EVENT_STATE_TRANSITION = "state_transition"
EVENT_WORKFLOW_STARTED = "workflow_started"
EVENT_WORKFLOW_COMPLETED = "workflow_completed"
EVENT_STEP_BLOCKED = "step_blocked"
EVENT_STEP_FAILED = "step_failed"
EVENT_STEP_RETRY = "step_retry"

# Per TRACE_LOGGING_CONTRACT_V1: Project-level events
EVENT_PROJECT_PAUSED = "PROJECT_PAUSED"
EVENT_PROJECT_RESUMED = "PROJECT_RESUMED"
EVENT_PROJECT_BLOCKED = "PROJECT_BLOCKED"
EVENT_PROJECT_FAILED = "PROJECT_FAILED"

# Per task requirement: MESSAGE event type for general messaging
EVENT_MESSAGE = "MESSAGE"


def _get_execution_generation(workflow_id: str) -> int:
    """
    Lookup current execution_generation from authoritative runtime registry.

    Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1:
    execution_generation increments when a new execution attempt invalidates
    stale runtime ownership. Events MUST carry the generation they were emitted under.

    FAILURE-ISOLATED: lazy import + try/except prevents circular dependencies.
    Returns 1 if lookup fails (safe default).
    """
    try:
        from system.orchestrator.workflow_control import _workflow_state_registry, _workflow_state_lock
        with _workflow_state_lock:
            return _workflow_state_registry.get(workflow_id, {}).get("execution_generation", 1)
    except Exception:
        return 1


def emit_event(event_type: str, workflow_id: str, data: Dict[str, Any]) -> None:
    """
    Emit an event to the event bus.

    CRITICAL RULES:
    - Wrapped in try/except — NEVER raises
    - NEVER blocks execution
    - NEVER returns anything
    - MUST be called AFTER actual event occurs
    - MUST NOT be called BEFORE execution_result is available

    Args:
        event_type: Type of event (use EVENT_* constants)
        workflow_id: The workflow identifier
        data: Event payload
    """
    try:
        # Per INCREMENTAL CHRONOLOGY HYDRATION:
        # Enrich event payload with authoritative execution_generation.
        # Backward-compatible: only added when not already present.
        enriched = {**data}
        if "execution_generation" not in enriched:
            enriched["execution_generation"] = _get_execution_generation(workflow_id)
        publish_event(workflow_id, event_type, enriched)
    except Exception:
        # FAILURE-ISOLATED: Event emission failure must not affect execution
        pass


def emit_step_started(workflow_id: str, step_id: str, purpose: str, 
                      step_type: str = "EXECUTE_API", input_data: Optional[str] = None) -> None:
    """
    Emit step_started event.
    
    CALL AFTER: step["status"] = "ACTIVE" is set
    """
    emit_event(EVENT_STEP_STARTED, workflow_id, {
        "step_id": step_id,
        "purpose": purpose,
        "step_type": step_type,
        "input": input_data,
        "timestamp": datetime.utcnow().isoformat()
    })


def emit_step_completed(workflow_id: str, step_id: str, status: str,
                        execution_result: Optional[Dict[str, Any]] = None,
                        retries: int = 0, purpose: Optional[str] = None) -> None:
    """
    Emit step_completed event.
    
    CALL AFTER: step["status"] = "COMPLETED" is set
    CALL AFTER: step["execution_result"] is populated
    
    Args:
        status: "COMPLETED", "FAILED", or "BLOCKED"
        execution_result: The execution result dict (status, result, reason)
    """
    data = {
        "step_id": step_id,
        "status": status,
        "retries": retries,
        "purpose": purpose,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Include execution result summary (not full trace)
    if execution_result:
        data["execution_status"] = execution_result.get("status")
        # Only include result summary for success, reason for failure
        if execution_result.get("status") == "success":
            result = execution_result.get("result")
            # Truncate for efficiency
            data["result_summary"] = str(result)[:100] if result is not None else None
        elif execution_result.get("status") == "failure":
            data["failure_reason"] = execution_result.get("reason")
    
    emit_event(EVENT_STEP_COMPLETED, workflow_id, data)


def emit_step_failed(workflow_id: str, step_id: str, reason: str,
                     execution_result: Optional[Dict[str, Any]] = None,
                     retries: int = 0) -> None:
    """
    Emit step_failed event.
    
    CALL AFTER: step["status"] = "FAILED" is set
    """
    data = {
        "step_id": step_id,
        "reason": reason,
        "retries": retries,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if execution_result:
        data["execution_status"] = execution_result.get("status")
        data["failure_reason"] = execution_result.get("reason")
    
    emit_event(EVENT_STEP_FAILED, workflow_id, data)


def emit_step_blocked(workflow_id: str, step_id: str, blocked_reason: str,
                      retries: int = 0) -> None:
    """
    Emit step_blocked event.
    
    CALL AFTER: step["status"] = "BLOCKED" is set
    """
    emit_event(EVENT_STEP_BLOCKED, workflow_id, {
        "step_id": step_id,
        "blocked_reason": blocked_reason,
        "retries": retries,
        "timestamp": datetime.utcnow().isoformat()
    })


def emit_step_retry(workflow_id: str, step_id: str, retry_count: int,
                    max_retries: int, reason: Optional[str] = None) -> None:
    """
    Emit step_retry event.
    
    CALL AFTER: step["retries"] is incremented
    """
    emit_event(EVENT_STEP_RETRY, workflow_id, {
        "step_id": step_id,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat()
    })


def emit_governance_decision(workflow_id: str, step_id: str, decision: str,
                             reason: Optional[str] = None,
                             execution_result_status: Optional[str] = None) -> None:
    """
    Emit governance_decision event.
    
    CALL AFTER: governance.decide_next_action() returns
    CALL AFTER: decision is applied to step
    
    Args:
        decision: "continue", "retry", "escalate", "complete", "fail", "block"
        reason: Why this decision was made
        execution_result_status: The execution result status that led to decision
    """
    emit_event(EVENT_GOVERNANCE_DECISION, workflow_id, {
        "step_id": step_id,
        "decision": decision,
        "reason": reason,
        "execution_result_status": execution_result_status,
        "timestamp": datetime.utcnow().isoformat()
    })


def emit_state_transition(workflow_id: str, step_id: Optional[str],
                          previous_state: str, new_state: str,
                          reason: Optional[str] = None) -> None:
    """
    Emit state_transition event.
    
    CALL AFTER: step["status"] or workflow["status"] is updated
    
    Args:
        step_id: Step identifier (None for workflow-level transitions)
        previous_state: Previous status value
        new_state: New status value
        reason: Why transition occurred
    """
    data = {
        "previous_state": previous_state,
        "new_state": new_state,
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    if step_id:
        data["step_id"] = step_id
    
    emit_event(EVENT_STATE_TRANSITION, workflow_id, data)


def emit_workflow_started(workflow_id: str, workflow_name: Optional[str] = None,
                          step_count: int = 0, input: Optional[str] = None) -> None:
    """
    Emit workflow_started event.
    
    CALL AFTER: workflow execution loop begins
    """
    emit_event(EVENT_WORKFLOW_STARTED, workflow_id, {
        "workflow_name": workflow_name,
        "step_count": step_count,
        "input": input,
        "timestamp": datetime.utcnow().isoformat()
    })


def emit_workflow_completed(workflow_id: str, status: str,
                            final_result: Optional[Dict[str, Any]] = None,
                            completed_steps: int = 0, failed_steps: int = 0) -> None:
    """
    Emit workflow_completed event.
    
    CALL AFTER: workflow["status"] = "COMPLETED" or "FAILED"
    CALL AFTER: workflow["output"] is set
    
    Args:
        status: "COMPLETED", "FAILED", or "BLOCKED"
        final_result: The workflow output/result
    """
    data = {
        "status": status,
        "completed_steps": completed_steps,
        "failed_steps": failed_steps,
        "timestamp": datetime.utcnow().isoformat()
    }

    if final_result:
        data["final_status"] = final_result.get("status")
        if final_result.get("status") == "failure":
            data["failure_reason"] = final_result.get("reason")
        elif final_result.get("status") == "success":
            result = final_result.get("result")
            data["result_summary"] = str(result)[:100] if result is not None else None

    emit_event(EVENT_WORKFLOW_COMPLETED, workflow_id, data)


def emit_project_paused(workflow_id: str, reason: Optional[str] = None) -> None:
    """
    Emit PROJECT_PAUSED event per TRACE_LOGGING_CONTRACT_V1.

    CALL AFTER: workflow["status"] = "PAUSED"
    """
    emit_event(EVENT_PROJECT_PAUSED, workflow_id, {
        "reason": reason or "user_pause",
        "timestamp": datetime.utcnow().isoformat()
    })


def emit_project_resumed(workflow_id: str, reason: Optional[str] = None) -> None:
    """
    Emit PROJECT_RESUMED event per TRACE_LOGGING_CONTRACT_V1.

    CALL AFTER: workflow["status"] = "ACTIVE" (from PAUSED)
    """
    emit_event(EVENT_PROJECT_RESUMED, workflow_id, {
        "reason": reason or "user_resume",
        "timestamp": datetime.utcnow().isoformat()
    })


def emit_project_failed(workflow_id: str, reason: Optional[str] = None) -> None:
    """
    Emit PROJECT_FAILED event per TRACE_LOGGING_CONTRACT_V1.

    CALL AFTER: workflow["status"] = "FAILED"
    """
    emit_event(EVENT_PROJECT_FAILED, workflow_id, {
        "reason": reason or "user_stop",
        "timestamp": datetime.utcnow().isoformat()
    })


def emit_message(workflow_id: str, step_id: Optional[str], message: str,
                 level: str = "INFO", data: Optional[Dict[str, Any]] = None) -> None:
    """
    Emit MESSAGE event per task requirement.

    Args:
        workflow_id: The workflow identifier
        step_id: Optional step identifier
        message: The message text
        level: Message level (INFO, WARNING, ERROR, DEBUG)
        data: Optional additional data
    """
    payload = {
        "message": message,
        "level": level,
        "timestamp": datetime.utcnow().isoformat()
    }
    if step_id:
        payload["step_id"] = step_id
    if data:
        payload["data"] = data

    emit_event(EVENT_MESSAGE, workflow_id, payload)
