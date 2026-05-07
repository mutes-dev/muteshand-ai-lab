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
from typing import Any, Callable, Dict, List, Optional, Tuple
from system.orchestrator import trace_collector

# === LIVE STATE STREAMING (Phase 3) — OBSERVATIONAL ONLY ===
# Per HAND_ARCHITECTURE_V2: Streaming reflects state, never influences it
# Per CONTROL_MODEL: Events are advisory, non-authoritative
try:
    from system.interface import event_emitter as _event_emitter
except Exception:
    _event_emitter = None


def _execute_single_step(
    step: dict,
    workflow: dict,
    execute_step_fn: Callable,
    governance_fn: Callable,
    propagate_fn: Callable,
    escalation_handler: Any,
    debug_verbose: bool = False
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

    # TRACE: GROUP_STEP_STARTED
    try:
        trace_collector.record_transition(
            step_id=step_id,
            previous_status="PENDING",
            new_status="ACTIVE",
            reason="GROUP_STEP_STARTED"
        )
    except Exception:
        pass

    # Activate step (PENDING/ACTIVE -> ACTIVE)
    step["status"] = "ACTIVE"
    step.pop("_approval_resumed", None)  # Clear approval-resume flag once executing

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
        step["status"] = "BLOCKED"
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

    # === STEP EXECUTION (via execute_step — calls system_entry internally) ===
    exec_data = execute_step_fn(
        step=step,
        workflow=workflow,
        retry_guidance=None,
        debug_verbose=debug_verbose,
        dependency_outputs=dependency_outputs
    )

    # Handle blocked (approval denied)
    if exec_data.get("blocked"):
        step["status"] = "BLOCKED"
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
        step["status"] = "FAILED"
        return {
            "step_id": step_id,
            "status": "FAILED",
            "execution_result": execution_result,
            "governance_decision": "fail"
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

    # === GOVERNANCE DECISION (per step — GOVERNANCE_CONTRACT) ===
    next_decision = governance_fn(
        validator_output=validator_output,
        execution_result=exec_res,
        step=step,
        context={"workflow": workflow}
    )

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

    # === STATE TRANSITION based on governance decision ===
    if next_decision == "complete":
        step["status"] = "COMPLETED"
        # === STEP IO: STORE OUTPUT PER STEP (STEP_IO_CONTRACT_V1 Section 2) ===
        from system.orchestrator.memory_controller import set_step_output, append_step_history
        if exec_res is not None:
            set_step_output(workflow, step_id, exec_res)
        append_step_history(workflow, {
            "step_id": step_id,
            "result": exec_res
        })

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
        step["status"] = "BLOCKED"
        # Preserve blocked_reason set by governance (e.g. "approval_required")
        # Only set default if governance didn't provide one
        if not step.get("blocked_reason"):
            step["blocked_reason"] = "approval_required"

    elif next_decision == "retry":
        # === STEP IO: INVALIDATE OUTPUTS ON RETRY (STEP_IO_CONTRACT_V1 Section 6) ===
        # Delete this step's output and all dependent step outputs before re-execution.
        from system.orchestrator.memory_controller import invalidate_step_outputs
        invalidate_step_outputs(workflow, step_id)
        # Delegate to escalation controller
        retry_result = escalation_handler.handle_retry(
            step=step,
            workflow=workflow,
            next_decision=next_decision
        )
        if retry_result["action"] == "BLOCKED":
            step["status"] = "BLOCKED"
        # If RETRY, step remains ACTIVE for potential re-execution
        # But within parallel group, we treat it as terminal for this round

    elif next_decision in ("escalate", "fail"):
        esc_result = escalation_handler.handle_escalation(
            step=step,
            workflow=workflow,
            next_decision=next_decision,
            exec_res=exec_res
        )
        if esc_result["action"] == "BLOCKED":
            step["status"] = "BLOCKED"
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
            validator_signals=step.get("_validator_signals")
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
    debug_verbose: bool = False
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
                # Step execution failure — mark as FAILED
                step = steps_map.get(step_id)
                if step:
                    step["status"] = "FAILED"
                results.append({
                    "step_id": step_id,
                    "status": "FAILED",
                    "execution_result": {
                        "status": "failure",
                        "reason": f"parallel_execution_error: {str(e)}"
                    },
                    "governance_decision": "fail"
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
    debug_verbose: bool = False
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
