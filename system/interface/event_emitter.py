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

# ── Sprint 9B: Live observability event types ────────────────────────────────
EVENT_PLANNING_STARTED = "planning_started"
EVENT_PLANNING_RETRY = "planning_retry"
EVENT_PLANNING_COMPLETED = "planning_completed"
EVENT_PLANNING_FAILED = "planning_failed"

EVENT_TOOL_SELECTION_STARTED = "tool_selection_started"
EVENT_TOOL_SELECTED = "tool_selected"
EVENT_TOOL_SELECTION_FAILED = "tool_selection_failed"

EVENT_FORMATTER_CALL = "formatter_call"
EVENT_VALIDATOR_CALL = "validator_call"

# ── Sprint 9D-3: Detailed planning telemetry event types ─────────────────────
EVENT_PLANNING_LLM_STARTED = "planning_llm_started"
EVENT_PLANNING_LLM_COMPLETED = "planning_llm_completed"
EVENT_PLANNING_DEPENDENCIES_RESOLVED = "planning_dependencies_resolved"
EVENT_PLANNING_COMPILER_PASS = "planning_compiler_pass"
EVENT_PLANNING_VALIDATION_PASSED = "planning_validation_passed"

# ── Sprint 10 AGENT-001C: Capability route observability event types ──────────
EVENT_CAPABILITY_ROUTE_ATTEMPTED = "capability_route_attempted"
EVENT_CAPABILITY_ROUTE_ACCEPTED = "capability_route_accepted"
EVENT_CAPABILITY_ROUTE_FALLBACK = "capability_route_fallback"
EVENT_CAPABILITY_ROUTE_ERROR = "capability_route_error"

# ── AGENT-001J-FIX1: Approval and user-control refresh signal event types ─────
# Per NOTIFICATION_CONTRACT_V1 + LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
# These are NON-AUTHORITATIVE refresh signals only.
# Trace recording (trace_collector) remains the authoritative append-only record.
# Frontend uses these to trigger projection/panel refetch — not as lifecycle truth.
EVENT_APPROVAL_CREATED = "approval_created"
EVENT_APPROVAL_RESOLVED = "approval_resolved"
EVENT_USER_CONTROL_CREATED = "user_control_created"
EVENT_USER_CONTROL_RESOLVED = "user_control_resolved"


# ── Sprint 9D-3B: Transient planning-stage cache for stream response ───────────
# In-memory only. Non-authoritative. No persistence. No lifecycle mutation.
# Written by emit_planning_* functions; read by api.py stream_workflow_id.
# FAILURE-ISOLATED: any error is silently absorbed.
_planning_stage_cache: Dict[str, str] = {}


def get_planning_stage(workflow_id: Optional[str]) -> Optional[str]:
    """
    Return the latest planning stage for a workflow_id.

    Safe accessor for api.py stream_workflow_id. Returns None if unknown.
    """
    if not workflow_id:
        return None
    try:
        return _planning_stage_cache.get(workflow_id)
    except Exception:
        return None


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


def emit_planning_started(workflow_id: str, attempt: int = 0, prompt_version: str = None) -> None:
    """
    Emit planning_started event.

    CALL AFTER: planner begins LLM call.
    """
    data = {
        "attempt": attempt,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if prompt_version:
        data["prompt_version"] = prompt_version
    emit_event(EVENT_PLANNING_STARTED, workflow_id, data)


def emit_planning_retry(workflow_id: str, attempt: int, reason: str = None) -> None:
    """
    Emit planning_retry event.

    CALL AFTER: planner decides to retry due to LLM failure or validation failure.
    """
    data = {
        "attempt": attempt,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if reason:
        data["reason"] = reason
    emit_event(EVENT_PLANNING_RETRY, workflow_id, data)


def emit_planning_completed(workflow_id: str, step_count: int, prompt_version: str = None) -> None:
    """
    Emit planning_completed event.

    CALL AFTER: planner successfully produces valid steps.
    """
    data = {
        "step_count": step_count,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if prompt_version:
        data["prompt_version"] = prompt_version
    emit_event(EVENT_PLANNING_COMPLETED, workflow_id, data)


def emit_planning_failed(workflow_id: str, reason: str) -> None:
    """
    Emit planning_failed event.

    CALL AFTER: planner exhausts all retries or hits unrecoverable error.
    """
    emit_event(EVENT_PLANNING_FAILED, workflow_id, {
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat(),
    })


def emit_tool_selection_started(workflow_id: str, step_id: str, input_data: str = None) -> None:
    """
    Emit tool_selection_started event.

    CALL AFTER: AG1 begins tool selection for a step.
    """
    data = {
        "step_id": step_id,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if input_data:
        data["input_preview"] = str(input_data)[:200]
    emit_event(EVENT_TOOL_SELECTION_STARTED, workflow_id, data)


def emit_tool_selected(workflow_id: str, step_id: str, selected_tool: str,
                       provider: str = None, model: str = None) -> None:
    """
    Emit tool_selected event.

    CALL AFTER: AG1 successfully selects a tool.
    """
    data = {
        "step_id": step_id,
        "selected_tool": selected_tool,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if provider:
        data["provider"] = provider
    if model:
        data["model"] = model
    emit_event(EVENT_TOOL_SELECTED, workflow_id, data)


def emit_tool_selection_failed(workflow_id: str, step_id: str, reason: str) -> None:
    """
    Emit tool_selection_failed event.

    CALL AFTER: AG1 fails to select a valid tool.
    """
    emit_event(EVENT_TOOL_SELECTION_FAILED, workflow_id, {
        "step_id": step_id,
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat(),
    })


def emit_formatter_call(workflow_id: str, tool_name: str = None, status: str = None) -> None:
    """
    Emit formatter_call event.

    CALL AFTER: formatter LLM call completes.
    """
    data = {
        "timestamp": datetime.utcnow().isoformat(),
    }
    if tool_name:
        data["tool_name"] = tool_name
    if status:
        data["status"] = status
    emit_event(EVENT_FORMATTER_CALL, workflow_id, data)


def emit_validator_call(workflow_id: str, status: str = None, constraint_count: int = None) -> None:
    """
    Emit validator_call event.

    CALL AFTER: validator LLM call completes.
    """
    data = {
        "timestamp": datetime.utcnow().isoformat(),
    }
    if status:
        data["status"] = status
    if constraint_count is not None:
        data["constraint_count"] = constraint_count
    emit_event(EVENT_VALIDATOR_CALL, workflow_id, data)


def emit_planning_llm_started(workflow_id: str, attempt: int = None, provider: str = None, model: str = None, prompt_version: str = None) -> None:
    """
    Emit planning_llm_started event.

    CALL AFTER: planner LLM call begins.
    """
    data = {
        "timestamp": datetime.utcnow().isoformat(),
    }
    if attempt is not None:
        data["attempt"] = attempt
    if provider:
        data["provider"] = provider
    if model:
        data["model"] = model
    if prompt_version:
        data["prompt_version"] = prompt_version
    emit_event(EVENT_PLANNING_LLM_STARTED, workflow_id, data)
    try:
        _planning_stage_cache[workflow_id] = EVENT_PLANNING_LLM_STARTED
    except Exception:
        pass


def emit_planning_llm_completed(workflow_id: str, attempt: int = None, status: str = None, duration_ms: float = None, response_len: int = None) -> None:
    """
    Emit planning_llm_completed event.

    CALL AFTER: planner LLM call returns.
    """
    data = {
        "timestamp": datetime.utcnow().isoformat(),
    }
    if attempt is not None:
        data["attempt"] = attempt
    if status:
        data["status"] = status
    if duration_ms is not None:
        data["duration_ms"] = round(duration_ms, 2)
    if response_len is not None:
        data["response_len"] = response_len
    emit_event(EVENT_PLANNING_LLM_COMPLETED, workflow_id, data)
    try:
        _planning_stage_cache[workflow_id] = EVENT_PLANNING_LLM_COMPLETED
    except Exception:
        pass


def emit_planning_dependencies_resolved(workflow_id: str, step_count: int = None, dependency_count: int = None) -> None:
    """
    Emit planning_dependencies_resolved event.

    CALL AFTER: dependency resolution completes successfully.
    """
    data = {
        "timestamp": datetime.utcnow().isoformat(),
    }
    if step_count is not None:
        data["step_count"] = step_count
    if dependency_count is not None:
        data["dependency_count"] = dependency_count
    emit_event(EVENT_PLANNING_DEPENDENCIES_RESOLVED, workflow_id, data)
    try:
        _planning_stage_cache[workflow_id] = EVENT_PLANNING_DEPENDENCIES_RESOLVED
    except Exception:
        pass


def emit_planning_compiler_pass(workflow_id: str, phase: str = None, repairs_count: int = None) -> None:
    """
    Emit planning_compiler_pass event.

    CALL AFTER: each planning compiler pass completes.
    """
    data = {
        "timestamp": datetime.utcnow().isoformat(),
    }
    if phase:
        data["phase"] = phase
    if repairs_count is not None:
        data["repairs_count"] = repairs_count
    emit_event(EVENT_PLANNING_COMPILER_PASS, workflow_id, data)
    try:
        _planning_stage_cache[workflow_id] = EVENT_PLANNING_COMPILER_PASS
    except Exception:
        pass


def emit_planning_validation_passed(workflow_id: str, warning_count: int = None) -> None:
    """
    Emit planning_validation_passed event.

    CALL AFTER: workflow validation succeeds.
    """
    data = {
        "timestamp": datetime.utcnow().isoformat(),
    }
    if warning_count is not None:
        data["warning_count"] = warning_count
    emit_event(EVENT_PLANNING_VALIDATION_PASSED, workflow_id, data)
    try:
        _planning_stage_cache[workflow_id] = EVENT_PLANNING_VALIDATION_PASSED
    except Exception:
        pass


# ── Sprint 10 AGENT-001C: Capability route observability emitters ────────────

def emit_capability_route_attempted(workflow_id: str, capability_id: str = None,
                                    route_confidence: float = 0.0,
                                    route_reason_code: str = None,
                                    user_input_preview: str = None) -> None:
    """
    Emit capability_route_attempted event.

    CALL AFTER: capability router begins route evaluation.
    FAILURE-ISOLATED: any error is silently absorbed.
    """
    data = {
        "timestamp": datetime.utcnow().isoformat(),
    }
    if capability_id is not None:
        data["capability_id"] = capability_id
    if route_confidence is not None:
        data["route_confidence"] = route_confidence
    if route_reason_code is not None:
        data["route_reason_code"] = route_reason_code
    if user_input_preview is not None:
        data["user_input_preview"] = str(user_input_preview)[:200]
    emit_event(EVENT_CAPABILITY_ROUTE_ATTEMPTED, workflow_id, data)


def emit_capability_route_accepted(workflow_id: str, capability_id: str,
                                   route_confidence: float, route_reason_code: str,
                                   candidate_workflow_emitted: bool = False,
                                   compiler_handoff_status: str = None,
                                   compiler_repairs_applied: str = None) -> None:
    """
    Emit capability_route_accepted event.

    CALL AFTER: capability route is accepted and compiler handoff completes.
    FAILURE-ISOLATED: any error is silently absorbed.
    """
    data = {
        "capability_id": capability_id,
        "route_confidence": route_confidence,
        "route_reason_code": route_reason_code,
        "candidate_workflow_emitted": candidate_workflow_emitted,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if compiler_handoff_status is not None:
        data["compiler_handoff_status"] = compiler_handoff_status
    if compiler_repairs_applied is not None:
        data["compiler_repairs_applied"] = compiler_repairs_applied
    emit_event(EVENT_CAPABILITY_ROUTE_ACCEPTED, workflow_id, data)


def emit_capability_route_fallback(workflow_id: str, capability_id: str = None,
                                   route_confidence: float = 0.0,
                                   route_reason_code: str = None,
                                   fallback_reason: str = None) -> None:
    """
    Emit capability_route_fallback event.

    CALL AFTER: capability router decides to fall back to planner.
    FAILURE-ISOLATED: any error is silently absorbed.
    """
    data = {
        "timestamp": datetime.utcnow().isoformat(),
    }
    if capability_id is not None:
        data["capability_id"] = capability_id
    if route_confidence is not None:
        data["route_confidence"] = route_confidence
    if route_reason_code is not None:
        data["route_reason_code"] = route_reason_code
    if fallback_reason is not None:
        data["fallback_reason"] = fallback_reason
    emit_event(EVENT_CAPABILITY_ROUTE_FALLBACK, workflow_id, data)


def emit_capability_route_error(workflow_id: str, capability_id: str = None,
                                error: str = None, fallback_reason: str = None) -> None:
    """
    Emit capability_route_error event.

    CALL AFTER: capability routing encounters an unhandled exception.
    FAILURE-ISOLATED: any error is silently absorbed.
    """
    data = {
        "timestamp": datetime.utcnow().isoformat(),
    }
    if capability_id is not None:
        data["capability_id"] = capability_id
    if error is not None:
        data["error"] = str(error)[:500]
    if fallback_reason is not None:
        data["fallback_reason"] = fallback_reason
    emit_event(EVENT_CAPABILITY_ROUTE_ERROR, workflow_id, data)


# ── AGENT-001J-FIX1: Approval and user-control refresh signal emitters ────────
# Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1 + NOTIFICATION_CONTRACT_V1:
# These events are NON-AUTHORITATIVE refresh hints only.
# Trace recording (trace_collector) remains the authoritative append-only record.
# FAILURE-ISOLATED: any error is silently absorbed.

def emit_approval_created(workflow_id: str, approval_id: str,
                          step_id: Optional[str] = None,
                          risk_level: str = "MEDIUM",
                          reason: Optional[str] = None) -> None:
    """
    Emit approval_created refresh signal.

    CALL AFTER: create_approval_request() registers the request.
    NON-AUTHORITATIVE: frontend uses this to trigger panel/projection refetch.
    """
    data = {
        "approval_id": approval_id,
        "risk_level": risk_level,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if step_id is not None:
        data["step_id"] = step_id
    if reason is not None:
        data["reason"] = reason
    emit_event(EVENT_APPROVAL_CREATED, workflow_id, data)


def emit_approval_resolved(workflow_id: str, approval_id: str,
                           decision: str,
                           step_id: Optional[str] = None) -> None:
    """
    Emit approval_resolved refresh signal.

    CALL AFTER: resolve_approval() resolves the Future.
    NON-AUTHORITATIVE: frontend uses this to trigger panel/projection refetch.

    Args:
        decision: "APPROVED" or "REJECTED"
    """
    data = {
        "approval_id": approval_id,
        "decision": decision,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if step_id is not None:
        data["step_id"] = step_id
    emit_event(EVENT_APPROVAL_RESOLVED, workflow_id, data)


def emit_user_control_created(workflow_id: str, control_id: str,
                              step_id: Optional[str] = None,
                              requested_action: Optional[str] = None,
                              risk_level: str = "MEDIUM") -> None:
    """
    Emit user_control_created refresh signal.

    CALL AFTER: create_user_control_request() registers the request.
    NON-AUTHORITATIVE: frontend uses this to trigger panel/projection refetch.
    """
    data = {
        "control_id": control_id,
        "risk_level": risk_level,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if step_id is not None:
        data["step_id"] = step_id
    if requested_action is not None:
        data["requested_action"] = requested_action
    emit_event(EVENT_USER_CONTROL_CREATED, workflow_id, data)


def emit_user_control_resolved(workflow_id: str, control_id: str,
                               decision: str,
                               step_id: Optional[str] = None,
                               requested_action: Optional[str] = None) -> None:
    """
    Emit user_control_resolved refresh signal.

    CALL AFTER: resolve_user_control_request() resolves the Future.
    NON-AUTHORITATIVE: frontend uses this to trigger panel/projection refetch.

    Args:
        decision: "ACCEPTED" or "REJECTED"
    """
    data = {
        "control_id": control_id,
        "decision": decision,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if step_id is not None:
        data["step_id"] = step_id
    if requested_action is not None:
        data["requested_action"] = requested_action
    emit_event(EVENT_USER_CONTROL_RESOLVED, workflow_id, data)
