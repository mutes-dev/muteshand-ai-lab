"""
PARALLEL EXECUTOR — Concurrent Step Execution

Complies with EXECUTION_SCHEDULING_CONTRACT_V1:
- Executes steps concurrently within parallel groups
- Calls execute_step ONLY (never system_entry directly)
- Waits for ALL steps before returning (barrier synchronization)
- Group does NOT complete until all steps terminal

Complies with ORCHESTRATOR_CONTRACT_V2:
- ALL execution goes through system_entry (via execute_step)
- Orchestrator MUST NOT execute tools directly
- Orchestrator MUST NOT bypass core

Complies with GOVERNANCE_CONTRACT:
- Governance evaluates EACH step independently
- No group-level governance override
- No batching of governance decisions

Complies with CHECKPOINT (Phase 2C):
- Checkpoint saved AFTER step terminal state
- Checkpoint failure does NOT affect execution
- Observational only

Complies with STATE_TRANSITIONS_CONTRACT_V1:
- PENDING -> ACTIVE (group starts)
- ACTIVE -> COMPLETED/FAILED/BLOCKED (governance decides)
- Multiple ACTIVE steps allowed ONLY in parallel group
"""

import concurrent.futures
import json
from typing import Any, Callable, Dict, List, Optional, Tuple
from system.orchestrator import trace_collector

# === LIVE STATE STREAMING (Phase 3) — OBSERVATIONAL ONLY ===
# Per HAND_ARCHITECTURE_V2: Streaming reflects state, never influences it
# Per CONTROL_MODEL: Events are advisory, non-authoritative
try:
    from system.interface import event_emitter as _event_emitter
except Exception:
    _event_emitter = None


def _structured_log(event_type, workflow_id, step_id, data):
    """Structured debug logger for runtime trace evidence."""
    log_entry = {
        "EVENT": event_type,
        "workflow_id": workflow_id,
        "step_id": step_id,
        "timestamp": __import__('datetime').datetime.now().isoformat(),
        "data": data
    }
    print(f"[RUNTIME_TRACE] {json.dumps(log_entry, default=str)}")

# === COOPERATIVE PAUSE ENFORCEMENT ===
# Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED is a blocking state
# Per architectural audit: pause enforcement belongs at execution boundaries
# Refresh authoritative state from runtime control registry before enforcing pause
def _check_workflow_pause(workflow_id: str) -> bool:
    """
    Check if workflow is paused using authoritative runtime control state.
    
    Refreshes state from workflow_control._get_workflow_state() to ensure
    authoritative check, not stale cached workflow object.
    
    Returns:
        True if workflow is PAUSED, False otherwise
    """
    try:
        from system.orchestrator.workflow_control import _get_workflow_state
        state = _get_workflow_state(workflow_id)
        if state and state.get("status") == "PAUSED":
            return True
    except Exception:
        # State check failure must not affect execution
        pass
    return False


def _is_workflow_terminated(workflow_id: str) -> bool:
    """
    Check if workflow has been terminalized using authoritative runtime control state.

    Per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1:
    Terminalization MUST terminate execution and retry workers.
    This is a cooperative, non-authoritative coordination check — execution loops
    call this at boundaries to detect when stop_workflow or natural terminalization
    has set the authoritative registry to a terminal state.

    Per STATE_TRANSITIONS_CONTRACT_V1:
    COMPLETED, FAILED, and CANCELLED are terminal states with no further transitions.

    Returns:
        True if workflow is in a terminal state (COMPLETED/FAILED/CANCELLED), False otherwise.
    """
    try:
        from system.orchestrator.workflow_control import _get_workflow_state
        state = _get_workflow_state(workflow_id)
        if state and state.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
            return True
    except Exception:
        # State check failure must not affect execution — fail open
        pass
    return False


def _execute_single_step(
    step: dict,
    workflow: dict,
    execute_step_fn: Callable,
    governance_fn: Callable,
    propagate_fn: Callable,
    escalation_handler: Any,
    debug_verbose: bool = False,
    bg_id: str = None
) -> dict:
    """
    Execute a single step through the full pipeline.

    This mirrors the per-step execution logic from orchestrator_runtime,
    delegating to the same execute_step function.

    Per ORCHESTRATOR_CONTRACT_V2:
    - Uses execute_step (which calls system_entry internally)
    - NEVER calls system_entry directly

    Per GOVERNANCE_CONTRACT:
    - Governance evaluates this step independently
    - No group-level decision logic

    Returns:
        dict with step execution outcome:
        {
            "step_id": str,
            "status": str,  # COMPLETED, FAILED, BLOCKED
            "execution_result": dict or None,
            "governance_decision": str
        }
    """
    step_id = step.get("id", "unknown")

    # === TERMINAL GUARD (PHASE-IIIA) ===
    # Per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1:
    # Terminalization MUST terminate execution workers.
    # Cooperative check: if workflow is already terminal (e.g. stop_workflow called),
    # do NOT proceed with step execution — return immediately.
    workflow_id = workflow.get("id", "unknown_workflow")
    if _is_workflow_terminated(workflow_id):
        return {
            "step_id": step_id,
            "status": step.get("status", "PENDING"),
            "execution_result": None,
            "governance_decision": "cancelled",
            "cancelled_reason": "workflow_terminated"
        }

    # TRACE: GROUP_STEP_STARTED
    try:
        previous_status = step.get("status", "PENDING")
        trace_collector.record_transition(
            step_id=step_id,
            previous_status=previous_status,
            new_status="ACTIVE",
            reason="GROUP_STEP_STARTED"
        )
    except Exception:
        pass

    # Activate step (PENDING/BLOCKED -> ACTIVE)
    # Per STATE_TRANSITIONS_CONTRACT_V1: RETRY is not a valid lifecycle state (PHASE-IA).
    # Retry candidates enter via PENDING state. BLOCKED enters via approval-resume path.
    from system.orchestrator.workflow_control import request_step_transition as _rst_pe
    if step.get("status") != "ACTIVE":
        _rst_pe(step, "ACTIVE", "group_step_started", _internal=True)
    step.pop("_approval_resumed", None)  # Clear approval-resume flag once executing
    step.pop("_retry_pending", None)     # Clear retry-pending flag once execution begins

    # === LIVE STREAMING: STEP STARTED (OBSERVATIONAL ONLY) ===
    # Per HAND_ARCHITECTURE_V2 Section 15: LIVE mode provides step-by-step visibility
    # CALL AFTER: step["status"] = "ACTIVE" is set
    # FAILURE-ISOLATED: Event emission failure must not affect execution
    if _event_emitter is not None:
        try:
            _wf_id = workflow.get("id", "unknown")
            _step_id = step.get("id", "unknown")
            _event_emitter.emit_step_started(
                workflow_id=_wf_id,
                step_id=_step_id,
                purpose=step.get("purpose", ""),
                step_type=step.get("type", "EXECUTE_API"),
                input_data=step.get("input")
            )
        except Exception:
            pass

    # === CONFLICT DETECTOR REGISTRATION (Phase 1A) ===
    from system.orchestrator.conflict_detector import get_detector
    conflict_detector = get_detector()
    conflict_detector.register_workflow(workflow.get("id", "unknown_workflow"))

    # === STEP IO: BUILD DEPENDENCY OUTPUTS (STEP_IO_CONTRACT_V1 Section 3) ===
    # Only provide outputs from explicitly declared dependencies.
    # No global state, no implicit access.
    from system.orchestrator.memory_controller import get_dependency_outputs
    _depends_on = step.get("depends_on", [])
    dependency_outputs = get_dependency_outputs(workflow, _depends_on)

    # === CONFLICT DETECTION (per step, within group) ===
    conflict = conflict_detector.detect_conflict(
        workflow.get("id", "unknown_workflow"), step
    )

    if conflict.get("conflict"):
        _rst_pe(step, "BLOCKED", "conflict_detected", _internal=True)
        step["_conflict"] = conflict
        try:
            trace_collector.record_transition(
                step_id=step_id,
                previous_status="ACTIVE",
                new_status="BLOCKED",
                reason=f"conflict_detected:{conflict.get('severity', 'UNKNOWN')}"
            )
        except Exception:
            pass
        return {
            "step_id": step_id,
            "status": "BLOCKED",
            "execution_result": None,
            "governance_decision": "block",
            "conflict": conflict
        }

    # === STALE EXECUTION PREVENTION (Phase 4A.1) ===
    # Per DEPENDENCY_MODEL_CONTRACT_V1 Section 10:
    # Re-check dependencies right before execution
    # Dependencies may have failed/been invalidated between scheduling and execution
    from system.orchestrator.execution_scheduler import _check_dependencies_satisfied
    step_states = {s.get("id"): s.get("status", "PENDING") for s in workflow.get("steps", [])}
    steps_map = {s.get("id"): s for s in workflow.get("steps", []) if s.get("id")}
    deps_satisfied, deps_reason = _check_dependencies_satisfied(step, step_states, steps_map)

    if not deps_satisfied:
        # Dependencies no longer satisfied - stale execution prevented
        _rst_pe(step, "BLOCKED", "stale_execution_prevented", _internal=True)
        step["blocked_reason"] = f"stale_execution_prevented:{deps_reason}"
        trace_collector.record_transition(
            step_id=step_id,
            previous_status="ACTIVE",
            new_status="BLOCKED",
            reason=f"stale_execution_prevented:{deps_reason}"
        )
        return {
            "step_id": step_id,
            "status": "BLOCKED",
            "execution_result": None,
            "governance_decision": "block",
            "blocked_reason": f"stale_execution_prevented:{deps_reason}"
        }

    # === STEP EXECUTION (via execute_step — calls system_entry internally) ===
    # Phase 1: Use governance-approved retry_guidance if stored on step from previous retry
    _retry_guidance = step.get("_governance_retry_guidance") if step.get("_governance_retry_guidance") else None
    exec_data = execute_step_fn(
        step=step,
        workflow=workflow,
        retry_guidance=_retry_guidance,
        debug_verbose=debug_verbose,
        dependency_outputs=dependency_outputs
    )

    # Handle blocked (approval denied)
    if exec_data.get("blocked"):
        _rst_pe(step, "BLOCKED", exec_data.get("blocked_reason", "approval_denied"), _internal=True)
        return {
            "step_id": step_id,
            "status": "BLOCKED",
            "execution_result": None,
            "governance_decision": "block",
            "blocked_reason": exec_data.get("blocked_reason", "User denied approval")
        }

    # Handle fail-fast (missing tool_call and purpose)
    execution_result = exec_data.get("execution_result")
    if execution_result and execution_result.get("reason") in ("missing_tool_call", "missing_tool_call_and_purpose"):
        step["execution_result"] = execution_result
        _rst_pe(step, "FAILED", "missing_tool_call", _internal=True)
        return {
            "step_id": step_id,
            "status": "FAILED",
            "execution_result": execution_result,
            "governance_decision": "fail"
        }

    # === ISSUE-098KP: Handle external_call_risk block (AG1 dynamic tool selection) ===
    # When AG1 selects an external-call tool but no accepted user-control request exists,
    # tool_selection_agent returns execution_result with status="blocked", reason="external_call_risk".
    # This must transition step and workflow to BLOCKED (not FAILED) and NOT count as retry.
    if execution_result and execution_result.get("status") == "blocked" and execution_result.get("reason") == "external_call_risk":
        # Transition step to BLOCKED
        _rst_pe(step, "BLOCKED", "external_call_risk", _internal=True)
        step["blocked_reason"] = "external_call_risk"
        step["execution_result"] = execution_result

        # Transition workflow to BLOCKED (per ISSUE-098KN pattern)
        from system.orchestrator.workflow_control import _update_workflow_state as _uws_ec_block
        _uws_ec_block(workflow.get("id", "unknown_workflow"), "BLOCKED", "external_call_risk", workflow_dict=workflow)

        # Persist workflow
        try:
            from system.orchestrator.persistence import save_workflow as _save_wf_ec
            _save_wf_ec(workflow)
        except Exception:
            pass

        # Trace
        try:
            trace_collector.record_transition(
                step_id=step_id,
                previous_status="ACTIVE",
                new_status="BLOCKED",
                reason="EXTERNAL_CALL_RISK_BLOCKED"
            )
        except Exception:
            pass

        return {
            "step_id": step_id,
            "status": "BLOCKED",
            "execution_result": execution_result,
            "governance_decision": "block",
            "blocked_reason": "external_call_risk"
        }

    validator_output = exec_data.get("validator_output", {})

    # === RESULT PROPAGATION (via propagate_result) ===
    step_result = exec_data.get("step_result")
    propagate_fn(
        step=step,
        execution_result=execution_result,
        step_result=step_result,
        debug_verbose=debug_verbose
    )

    # Extract execution_result for governance
    exec_res = step.get("execution_result")

    # RUNTIME TRACE: Pre-governance
    _structured_log("PARALLEL_EXEC_PRE_GOVERNANCE", workflow.get("id", "unknown"), step_id, {
        "exec_res": exec_res,
        "step_status": step.get("status"),
        "validator_output": validator_output,
        "retry_count": step.get("retries", 0)
    })

    # === GOVERNANCE DECISION (per step — GOVERNANCE_CONTRACT) ===
    next_decision = governance_fn(
        validator_output=validator_output,
        execution_result=exec_res,
        step=step,
        context={"workflow": workflow}
    )

    # RUNTIME TRACE: Post-governance
    _structured_log("PARALLEL_EXEC_POST_GOVERNANCE", workflow.get("id", "unknown"), step_id, {
        "next_decision": next_decision,
        "exec_res": exec_res,
        "step_status_after": step.get("status"),
        "retry_count_after": step.get("retries", 0)
    })

    # TRACE: governance decision
    try:
        trace_collector.record_governance(
            step_id=step_id,
            decision=next_decision,
            execution_result=exec_res,
            context={"step_status": step["status"], "retries": step.get("retries", 0)}
        )
    except Exception:
        pass

    # === STATE-BASED CANCELLATION GUARD (Phase 4A.1) ===
    # Per PLAN_CONTROL_CONTRACT_V1: ACTIVE step edit → step reset to PENDING
    # If step was edited during execution, it's no longer ACTIVE
    # DO NOT write stale results - discard instead
    if step.get("status") != "ACTIVE":
        # Step was edited/reset during execution; discard result
        trace_collector.record_transition(
            step_id=step_id,
            previous_status="ACTIVE",
            new_status=step.get("status", "UNKNOWN"),
            reason="state_based_cancellation:step_edited_during_execution"
        )
        return {
            "step_id": step_id,
            "status": step.get("status", "PENDING"),
            "execution_result": None,
            "governance_decision": "cancelled",
            "cancelled_reason": "step_no_longer_active"
        }

    # === STATE TRANSITION based on governance decision ===
    if next_decision == "complete":
        # CRITICAL ORDER: execution_result → status → registry update
        step["execution_result"] = exec_res
        _rst_pe(step, "COMPLETED", "governance_complete", _internal=True)
        # === STEP IO: STORE OUTPUT PER STEP (STEP_IO_CONTRACT_V1 Section 2) ===
        from system.orchestrator.memory_controller import set_step_output, append_step_history
        if exec_res is not None:
            set_step_output(workflow, step_id, exec_res)
        append_step_history(workflow, {
            "step_id": step_id,
            "result": exec_res
        })

        # === STEP_OUTPUTS PERSISTENCE (Phase 3F-XD) ===
        # Per STEP_IO_CONTRACT_V1 §2+STEP_OUTPUTS_REBUILD rationale:
        # save_workflow is normally called only on workflow-level state transitions.
        # If the process crashes between step completion and the next workflow-level
        # save, the in-memory step_outputs store is lost. On resurrection, PERSISTENCE
        # RESTORE rebuilds step_outputs from execution_result — but only if
        # execution_result was persisted. Calling save_workflow here ensures the
        # persisted workflow file always contains the latest execution_result for
        # every COMPLETED step, so rebuild has complete data after any crash point.
        # Failure MUST NOT affect execution.
        #
        # === TERMINAL GUARD (PHASE-IIIA) ===
        # Per SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1: terminal persistence
        # MUST NOT be overwritten by stale writes. If workflow is already terminal
        # (e.g. stop_workflow deleted the persistence file), skip this write.
        if not _is_workflow_terminated(workflow.get("id", "unknown_workflow")):
            try:
                from system.orchestrator.persistence import save_workflow as _save_wf_step
                _save_wf_step(workflow)
            except Exception:
                pass

        # === MEMORY WRITE — Pattern observation (Phase 3A) ===
        # Per MEMORY_STORAGE_CONTRACT_V1: write ONLY on successful completion
        # Per contract: NO writes on failure, retry, or single occurrence
        # Failure-isolated: MUST NOT affect execution
        try:
            from system.memory.preference_tracker import observe_execution
            _tool_name = None
            _executed_input = exec_data.get("executed_input")
            if _executed_input and isinstance(_executed_input, str):
                _parts = _executed_input.split()
                _tool_name = _parts[0] if _parts else None
            _step_type = step.get("type")
            _memory_written = observe_execution(
                tool_name=_tool_name or "",
                step_type=_step_type or "",
                execution_result=exec_res,
                step_purpose=step.get("purpose")
            )
            _mem_event = "MEMORY_WRITE" if _memory_written else "MEMORY_UPDATE"
            trace_collector.record_memory_event(
                event=_mem_event,
                key=_memory_written.get("key") if _memory_written else None,
                data={"tool": _tool_name, "step_type": _step_type,
                      "written": _memory_written is not None}
            )
        except Exception:
            pass

    elif next_decision == "block":
        _rst_pe(step, "BLOCKED", step.get("blocked_reason") or "approval_required", _internal=True)
        # Preserve blocked_reason set by governance (e.g. "approval_required")
        # Only set default if governance didn't provide one
        if not step.get("blocked_reason"):
            step["blocked_reason"] = "approval_required"

    elif next_decision == "retry":
        _structured_log("PARALLEL_EXEC_RETRY_PATH", workflow.get("id", "unknown"), step_id, {
            "decision": "retry",
            "exec_res_status": exec_res.get("status") if exec_res else None,
            "current_retries": step.get("retries", 0)
        })
        # === COOPERATIVE PAUSE ENFORCEMENT (Phase 3) ===
        # Check authoritative workflow state before retry execution
        # Per architectural audit: pause enforcement at execution boundaries
        workflow_id = workflow.get("id", "unknown_workflow")
        if _check_workflow_pause(workflow_id):
            # Workflow is paused - halt retry progression.
            # Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED is the valid pause state.
            # PAUSED_WAITING is not a valid lifecycle state (PHASE-IA contract gap closure).
            _rst_pe(step, "PAUSED", "workflow_paused_halt", _internal=True)
            return {
                "step_id": step_id,
                "status": "PAUSED",
                "execution_result": exec_res,
                "governance_decision": "retry",
                "pause_halted": True
            }

        # === STEP IO: INVALIDATE OUTPUTS ON RETRY (STEP_IO_CONTRACT_V1 Section 6) ===
        # Delete this step's output and all dependent step outputs before re-execution.
        from system.orchestrator.memory_controller import invalidate_step_outputs
        invalidate_step_outputs(workflow, step_id)
        # Delegate to escalation controller
        # Phase 1: Pass full GovernanceDecision for metadata visibility
        retry_result = escalation_handler.handle_retry(
            step=step,
            workflow=workflow,
            next_decision=next_decision,
            governance_decision=next_decision  # Full GovernanceDecision with retry metadata
        )
        if retry_result["action"] == "BLOCKED":
            # FIX B: Do not overwrite a step already marked FAILED by escalation_controller.
            # escalation_controller.handle_retry correctly sets FAILED on max_retries exceeded.
            # Preserving FAILED is contract-correct: FAILED means execution attempted and failed.
            if step.get("status") != "FAILED":
                _rst_pe(step, "BLOCKED", "retry_exhausted", _internal=True)
        # Per STATE_TRANSITIONS_CONTRACT_V1 §RETRY BEHAVIOR: state remains ACTIVE during
        # governance-internal retry (escalation_controller in-thread path).
        # This is the execution regeneration path — NOT the user retry path.
        # Step remains ACTIVE so the execution loop can re-dispatch it within this thread.

    elif next_decision in ("escalate", "fail"):
        # Standard escalation path — governance decision is authoritative
        esc_result = escalation_handler.handle_escalation(
            step=step,
            workflow=workflow,
            next_decision=next_decision,
            exec_res=exec_res,
            governance_decision=next_decision
        )
        if esc_result["action"] == "BLOCKED":
            _rst_pe(step, "BLOCKED", "escalation_blocked", _internal=True)
        elif esc_result["action"] == "COMPLETE":
            pass  # Step status set by escalation handler

    # === LIVE STREAMING: GOVERNANCE DECISION (OBSERVATIONAL ONLY) ===
    # Per HAND_ARCHITECTURE_V2 Section 15: LIVE mode shows governance decisions
    # CALL AFTER: governance decision is applied
    # FAILURE-ISOLATED: Event emission failure must not affect execution
    if _event_emitter is not None:
        try:
            _wf_id = workflow.get("id", "unknown")
            _step_id = step.get("id", "unknown")
            _exec_status = exec_res.get("status") if exec_res else None
            _event_emitter.emit_governance_decision(
                workflow_id=_wf_id,
                step_id=_step_id,
                decision=next_decision,
                reason=f"governance_decision_{next_decision}",
                execution_result_status=_exec_status
            )
        except Exception:
            pass

    # === LIVE STREAMING: STEP COMPLETED (OBSERVATIONAL ONLY) ===
    # Per HAND_ARCHITECTURE_V2 Section 15: LIVE mode shows step completion
    # CALL AFTER: step["status"] is set to final state
    # FAILURE-ISOLATED: Event emission failure must not affect execution
    if _event_emitter is not None:
        try:
            _wf_id = workflow.get("id", "unknown")
            _step_id = step.get("id", "unknown")
            _final_status = step.get("status", "UNKNOWN")
            _retries = step.get("retries", 0)
            _event_emitter.emit_step_completed(
                workflow_id=_wf_id,
                step_id=_step_id,
                status=_final_status,
                execution_result=exec_res,
                retries=_retries,
                purpose=step.get("purpose", "")
            )
        except Exception:
            pass

    # TRACE: GROUP_STEP_COMPLETED
    try:
        trace_collector.record_transition(
            step_id=step_id,
            previous_status="ACTIVE",
            new_status=step["status"],
            reason=f"GROUP_STEP_COMPLETED:governance={next_decision}"
        )
    except Exception:
        pass

    # Record step trace
    try:
        trace_collector.record_step(
            step_id=step_id,
            purpose=step.get("purpose", ""),
            step_input=step.get("input"),
            execution_result=exec_res,
            governance_decision=next_decision,
            retries=step.get("retries", 0),
            status=step["status"],
            validator_advisory=step.get("_validator_advisory"),
            validator_signals=step.get("_validator_signals"),
            agent_metadata=step.get("_agent_metadata")
        )
    except Exception:
        pass

    # === CHECKPOINT (Phase 2C) — OBSERVATIONAL ONLY ===
    # Save checkpoint AFTER step reaches terminal state.
    # Failure is silently ignored — MUST NOT affect execution.
    try:
        from system.orchestrator.checkpoint_manager import save_checkpoint
        save_checkpoint(workflow)
    except Exception:
        pass

    # Return result for this step
    _structured_log("PARALLEL_EXEC_STEP_COMPLETE", workflow.get("id", "unknown"), step_id, {
        "final_status": step["status"],
        "final_execution_result": exec_res,
        "governance_decision": next_decision,
        "final_retries": step.get("retries", 0)
    })

    return {
        "step_id": step_id,
        "status": step["status"],
        "execution_result": exec_res,
        "governance_decision": next_decision
    }


def execute_parallel_group(
    group: dict,
    workflow: dict,
    execute_step_fn: Callable,
    governance_fn: Callable,
    propagate_fn: Callable,
    escalation_handler: Any,
    debug_verbose: bool = False,
    bg_id: str = None
) -> List[dict]:
    """
    Execute all steps in a parallel group concurrently.

    Per EXECUTION_SCHEDULING_CONTRACT_V1 Section 4:
    - All steps transition to ACTIVE concurrently
    - Each step governed independently
    - Group completion = all steps terminal (COMPLETED or FAILED)
    - Group does NOT complete until all steps terminal
    - NO partial completion allowed

    Args:
        group: Execution group dict with step IDs
        workflow: The workflow dict
        execute_step_fn: Function to execute a single step
        governance_fn: Governance decision function
        propagate_fn: Result propagation function
        escalation_handler: Escalation controller module
        debug_verbose: Debug output flag

    Returns:
        List of step execution results
    """
    step_ids = group.get("steps", [])
    group_id = group.get("group_id", "unknown")

    # === COOPERATIVE PAUSE ENFORCEMENT (Phase 3) ===
    # Check authoritative workflow state before starting parallel group execution
    # Per architectural audit: pause enforcement at execution boundaries
    workflow_id = workflow.get("id", "unknown_workflow")
    if _check_workflow_pause(workflow_id):
        # Workflow is paused - halt group execution
        print(f"[PAUSE] Parallel group {group_id} halted - workflow is PAUSED")
        return []

    # === TERMINAL GUARD (PHASE-IIIA) ===
    # Per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1:
    # Terminalization MUST terminate execution workers.
    # If workflow is already terminal (e.g. stop_workflow), do NOT start group.
    if _is_workflow_terminated(workflow_id):
        print(f"[TERMINAL] Parallel group {group_id} halted - workflow is TERMINATED")
        return []

    # TRACE: GROUP_STARTED
    try:
        trace_collector.record_transition(
            step_id=group_id,
            previous_status="FORMED",
            new_status="ACTIVE",
            reason=f"GROUP_STARTED:type=PARALLEL:step_count={len(step_ids)}"
        )
    except Exception:
        pass

    # Resolve step objects from IDs
    steps_map = {s.get("id"): s for s in workflow.get("steps", [])}
    steps_to_run = [steps_map[sid] for sid in step_ids if sid in steps_map]

    if not steps_to_run:
        return []

    results = []

    # Execute steps concurrently using ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=len(steps_to_run)
    ) as executor:
        futures = {}
        for step in steps_to_run:
            future = executor.submit(
                _execute_single_step,
                step=step,
                workflow=workflow,
                execute_step_fn=execute_step_fn,
                governance_fn=governance_fn,
                propagate_fn=propagate_fn,
                escalation_handler=escalation_handler,
                debug_verbose=debug_verbose
            )
            futures[future] = step.get("id", "unknown")

        # Wait for ALL steps to complete (barrier synchronization)
        for future in concurrent.futures.as_completed(futures):
            step_id = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                # Step execution failure — distinguish orchestration vs execution failures
                step = steps_map.get(step_id)
                if step:
                    # Check if exception is from orchestration runtime (trace_collector, conflict_detector)
                    # vs actual execution failure
                    exception_type = type(e).__name__
                    exception_msg = str(e)
                    
                    # Known orchestration runtime exceptions
                    orchestration_runtime_exceptions = [
                        "KeyError",  # trace_collector or conflict_detector global state
                        "RuntimeError",  # dict modification during iteration
                        "AttributeError",  # missing global state
                    ]
                    
                    if exception_type in orchestration_runtime_exceptions:
                        # Orchestration runtime failure - mark as FAILED with specific reason
                        # This is a system failure, not an execution failure
                        _rst_pe(step, "FAILED", "orchestration_runtime_error", _internal=True)
                        step["_orchestration_runtime_failure"] = True
                        results.append({
                            "step_id": step_id,
                            "status": "FAILED",
                            "execution_result": {
                                "status": "failure",
                                "reason": f"orchestation_runtime_error:{exception_type}:{exception_msg}"
                            },
                            "governance_decision": "fail",
                            "_orchestration_runtime_failure": True
                        })
                    else:
                        # Execution failure - normal execution error
                        _rst_pe(step, "FAILED", "execution_error", _internal=True)
                        results.append({
                            "step_id": step_id,
                            "status": "FAILED",
                            "execution_result": {
                                "status": "failure",
                                "reason": f"execution_error:{exception_type}:{exception_msg}"
                            },
                            "governance_decision": "fail"
                        })
                else:
                    # Step not found - orchestration failure
                    results.append({
                        "step_id": step_id,
                        "status": "FAILED",
                        "execution_result": {
                            "status": "failure",
                            "reason": "step_not_found"
                        },
                        "governance_decision": "fail",
                        "_orchestration_runtime_failure": True
                    })

    # TRACE: PARALLEL_GROUP_SYNCHRONIZE (barrier reached)
    try:
        trace_collector.record_transition(
            step_id=group_id,
            previous_status="ACTIVE",
            new_status="SYNCHRONIZING",
            reason=f"PARALLEL_GROUP_SYNCHRONIZE:all_steps_terminal"
        )
    except Exception:
        pass

    # TRACE: GROUP_COMPLETED
    try:
        final_statuses = {r["step_id"]: r["status"] for r in results}
        trace_collector.record_transition(
            step_id=group_id,
            previous_status="SYNCHRONIZING",
            new_status="COMPLETED",
            reason=f"GROUP_COMPLETED:step_statuses={final_statuses}"
        )
    except Exception:
        pass

    return results


def execute_sequential_group(
    group: dict,
    workflow: dict,
    execute_step_fn: Callable,
    governance_fn: Callable,
    propagate_fn: Callable,
    escalation_handler: Any,
    debug_verbose: bool = False,
    post_step_callback: Callable = None
) -> List[dict]:
    """
    Execute all steps in a sequential group one at a time.

    Per EXECUTION_SCHEDULING_CONTRACT_V1 Section 3:
    - Steps execute in array order
    - step[i] completes before step[i+1] starts
    - Single ACTIVE step at any time

    Args:
        group: Execution group dict with step IDs
        workflow: The workflow dict
        execute_step_fn: Function to execute a single step
        governance_fn: Governance decision function
        propagate_fn: Result propagation function
        escalation_handler: Escalation controller module
        debug_verbose: Debug output flag

    Returns:
        List of step execution results
    """
    step_ids = group.get("steps", [])
    group_id = group.get("group_id", "unknown")

    # TRACE: GROUP_STARTED
    try:
        trace_collector.record_transition(
            step_id=group_id,
            previous_status="FORMED",
            new_status="ACTIVE",
            reason=f"GROUP_STARTED:type=SEQUENTIAL:step_count={len(step_ids)}"
        )
    except Exception:
        pass

    # Resolve step objects from IDs
    steps_map = {s.get("id"): s for s in workflow.get("steps", [])}
    results = []

    for step_id in step_ids:
        step = steps_map.get(step_id)
        if not step:
            continue

        # === COOPERATIVE PAUSE ENFORCEMENT (Phase 3) ===
        # Check authoritative workflow state before dispatching next step
        # Per architectural audit: pause enforcement at execution boundaries
        workflow_id = workflow.get("id", "unknown_workflow")
        if _check_workflow_pause(workflow_id):
            # Workflow is paused - halt sequential progression
            print(f"[PAUSE] Sequential group {group_id} halted before step {step_id} - workflow is PAUSED")
            break

        # === TERMINAL GUARD (PHASE-IIIA) ===
        # Per EXECUTION_RUNTIME_GOVERNANCE_CONTRACT_V1:
        # Terminalization MUST terminate execution workers.
        # If workflow is already terminal, do NOT dispatch next step.
        if _is_workflow_terminated(workflow_id):
            print(f"[TERMINAL] Sequential group {group_id} halted before step {step_id} - workflow is TERMINATED")
            break

        result = _execute_single_step(
            step=step,
            workflow=workflow,
            execute_step_fn=execute_step_fn,
            governance_fn=governance_fn,
            propagate_fn=propagate_fn,
            escalation_handler=escalation_handler,
            debug_verbose=debug_verbose
        )
        results.append(result)

        # Sequential: stop if step is not terminal-success
        # Next step starts only after current completes
        if result.get("status") not in ("COMPLETED",):
            break

    # TRACE: GROUP_COMPLETED
    try:
        final_statuses = {r["step_id"]: r["status"] for r in results}
        trace_collector.record_transition(
            step_id=group_id,
            previous_status="ACTIVE",
            new_status="COMPLETED",
            reason=f"GROUP_COMPLETED:step_statuses={final_statuses}"
        )
    except Exception:
        pass

    return results
