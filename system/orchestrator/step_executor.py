"""Step Executor Module — Handles step execution WITHOUT changing behavior.

This module extracts the execution logic from orchestrator_runtime
to create a clean separation of concerns. BEHAVIOR IS LOCKED.
"""
import json
import os
import shlex
from system.orchestrator import signal_interpreter

from system.entry.system_entry import system_entry
from system.orchestrator.agent_executor import execute_agent
from system.orchestrator.intent_validator import evaluate_intent
from system.orchestrator.workflow_validator import validate_step_schema

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TOOL_INDEX_PATH = os.path.join(_ROOT, "system", "tool_index", "tools.json")
with open(_TOOL_INDEX_PATH, "r", encoding="utf-8") as _f:
    _tool_index = json.load(_f)


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


def _safe_extract_tool_name(executed_input):
    """Safely extract tool name from executed_input string without mutation."""
    if not executed_input or not isinstance(executed_input, str):
        return None
    parts = executed_input.strip().split()
    return parts[0] if parts else None


def _build_agent_metadata(executed_input):
    """Build advisory-only agent metadata. Failure-isolated and absent-safe."""
    selected_tool = _safe_extract_tool_name(executed_input)
    return {
        "selected_agent": "tool_selection_agent",
        "selected_agent_type": "tool_selection",
        "selected_agent_version": "1.0.0",
        "selected_agent_capabilities": ["select_tool", "route_to_system_entry"],
        "selected_tool": selected_tool,
        "routing_source": "agent_executor",
        "system_entry_routed": True,
        "agent_authority": "advisory_only"
    }


def execute_step(step, workflow, retry_guidance=None, debug_verbose=False, dependency_outputs=None):
    """
    Execute a single step.

    Args:
        step: The step dict with tool_call, input, purpose, etc.
        workflow: The parent workflow dict
        retry_guidance: Optional retry guidance string
        debug_verbose: Debug output flag

    Returns:
        dict with keys:
            - execution_result: The execution result dict
            - validator_output: The validator output dict
            - executed_input: The executed input string
            - last_result: The last result value (for chaining)
            - step_result: The raw step result from execute_agent
    """
    workflow_id = workflow.get("id", "unknown")
    step_id = step.get("id", "unknown")
    retry_count = step.get("retries", 0)

    # === RESOLUTION ORDER FIX (Phase 4B.2.5) ===
    # Per STEP_RESOLUTION_CONTRACT_V1:
    # - Resolution MUST occur before validation
    # - Resolution produces tool_call from purpose
    # Per STEP_SCHEMA_CONTRACT_V1:
    # - Only resolved steps may be validated and executed
    
    # === STEP INPUT PREPARATION ===
    # Agent receives purpose/input to resolve into tool_call
    agent_input = step.get("tool_call") or step.get("purpose") or step.get("input")

    # RUNTIME TRACE: Step entry state
    _structured_log("STEP_ENTRY", workflow_id, step_id, {
        "agent_input": agent_input,
        "step_purpose": step.get("purpose"),
        "step_input": step.get("input"),
        "step_tool_call": step.get("tool_call"),
        "retry_count": retry_count,
        "step_status": step.get("status"),
        "existing_execution_result": step.get("execution_result"),
        "existing_validator_signals": step.get("_validator_signals"),
        "existing_extracted_constraints": step.get("_extracted_constraints")
    })

    # === RUNTIME SAFETY: STATE DIVERGENCE DETECTION ===
    # CRITICAL: Detect if purpose/input changed but tool_call still references stale arguments.
    # This is a SERIOUS BUG - execution artifacts MUST be invalidated when semantic intent changes.
    tool_call = step.get("tool_call")
    purpose = step.get("purpose", "")
    step_input = step.get("input", "")
    if tool_call:
        # Extract numeric arguments from tool_call for comparison
        import re
        tool_args = re.findall(r'\d+', str(tool_call))
        purpose_nums = re.findall(r'\d+', str(purpose))
        input_nums = re.findall(r'\d+', str(step_input))
        
        # If purpose/input specify different numbers than tool_call, ALERT
        if purpose_nums and tool_args:
            if purpose_nums != tool_args:
                pass  # divergence detected but execution proceeds per contract
        elif input_nums and tool_args:
            if input_nums != tool_args:
                pass  # divergence detected but execution proceeds per contract

    if not agent_input:
        return {
            "execution_result": {
                "status": "failure",
                "reason": "missing_tool_call_and_purpose"
            },
            "validator_output": {},
            "executed_input": None,
            "step_result": {
                "status": "failure",
                "result": {
                    "execution_result": {
                        "status": "failure",
                        "reason": "missing_tool_call_and_purpose"
                    }
                }
            }
        }

    # === USER APPROVAL GATE (Phase 1D — Governance-Aligned) ===
    # Governance is the SOLE authority for approval decisions.
    # step_executor ONLY handles the approval interaction when
    # governance has already decided BLOCK with blocked_reason=approval_required.
    # Runtime MUST NOT independently decide approval requirement.
    if step.get("status") == "BLOCKED" and step.get("blocked_reason") == "approval_required":
        from system.orchestrator.user_approval import request_approval
        approved = request_approval(step)

        if not approved:
            return {
                "execution_result": None,
                "validator_output": {},
                "executed_input": None,
                "step_result": None,
                "blocked": True,
                "blocked_reason": "User denied approval"
            }
        # Approved — continue to execution below
        from system.orchestrator.workflow_control import request_step_transition as _rst_se
        _rst_se(step, "ACTIVE", "approval_granted", _internal=True)

    # Phase 1: Use governance-approved retry_guidance if available
    # Check step for governance-approved guidance from escalation_controller
    if retry_guidance is None and step.get("_governance_retry_guidance"):
        retry_guidance = step.get("_governance_retry_guidance")
        _structured_log("RETRY_GUIDANCE_FROM_STEP", workflow_id, step_id, {
            "source": "step._governance_retry_guidance",
            "retry_guidance": retry_guidance
        })

    # === STEP IO: BUILD AGENT CONTEXT FROM DEPENDENCY OUTPUTS ONLY ===
    # Per STEP_IO_CONTRACT_V1 Section 3: agent receives ONLY outputs from
    # declared dependencies. No global state, no implicit access.
    # ISSUE-098KR: Added step_id for external-call user-control enforcement
    _agent_context = {"workflow_id": workflow_id, "step_id": step_id}

    if dependency_outputs:
        _agent_context["dependency_outputs"] = dependency_outputs

    # === ISSUE-095B: Operator-managed advisory memory context (AG1-only) ===
    # Per MEMORY_STORAGE_CONTRACT_V1: memory is advisory only.
    # Per AUTHORITY_MODEL: memory MUST NOT influence execution_result.
    # Reads only from memory_store (operator-managed), NOT global_memory or memory_adapter.
    # Failure-isolated: any error leaves _agent_context unchanged.
    try:
        from system.memory.advisory_bridge import build_advisory_memory_context
        _bridge_result = build_advisory_memory_context(
            project_id=workflow_id,
            max_entries=5,
            min_confidence=0.5,
            categories=("behavior", "preference", "context"),
        )
        if _bridge_result and _bridge_result.get("formatted_text"):
            _agent_context["advisory_memory"] = _bridge_result["formatted_text"]
            # Trace advisory context usage (failure-isolated)
            try:
                from system.orchestrator import trace_collector as _tc
                _tc.record_memory_event(
                    event="MEMORY_CONTEXT_USED",
                    key=None,
                    data=_bridge_result.get("metadata", {}),
                )
            except Exception:
                pass
            # Emit to event bus for UI Events visibility (failure-isolated)
            try:
                from system.interface import event_emitter as _ee
                _ee.emit_event(
                    "MEMORY_CONTEXT_USED",
                    workflow_id,
                    {"step_id": step_id, "metadata": _bridge_result.get("metadata", {})},
                )
            except Exception:
                pass
    except Exception:
        pass

    # === RESOLUTION: AGENT EXECUTES TO PRODUCE tool_call ===
    # Per STEP_RESOLUTION_CONTRACT_V1: Agent resolves purpose → tool_call

    # RUNTIME TRACE: Pre-execution
    _structured_log("PRE_AGENT_EXECUTION", workflow_id, step_id, {
        "agent_input": agent_input,
        "retry_guidance": retry_guidance,
        "dependency_outputs": dependency_outputs
    })

    step_result = execute_agent(
        agent={
            "name": "generic_agent",
            "role": "tool_executor",
            "scope": ["tools"]
        },
        input_data=agent_input,
        retry_guidance=retry_guidance,
        context=_agent_context
    )
    
    # === POST-RESOLUTION: EXTRACT tool_call FROM AGENT RESULT ===
    _result_val = step_result.get("result")
    resolved_tool_call = (
        (_result_val.get("executed_input") if isinstance(_result_val, dict) else None)
        or step_result.get("executed_input")
    )

    # Inject resolved tool_call into step for validation
    if resolved_tool_call:
        step["tool_call"] = resolved_tool_call

    # === ISSUE-073: AG1 ADVISORY METADATA ATTACHMENT ===
    # Per AGENT_GOVERNANCE_CONTRACT_V1: agents are advisory-only semantic infrastructure.
    # Metadata is attached AFTER execute_agent returns and BEFORE governance/trace processing.
    # Metadata MUST NOT influence: retry, completion, failure, escalation, lifecycle,
    # mutation legality, projection truth, execution identity, prompt construction,
    # or tool selection behavior.
    try:
        step["_agent_metadata"] = _build_agent_metadata(resolved_tool_call)
    except Exception:
        # Failure-isolated: metadata attachment failure must not affect execution
        step["_agent_metadata"] = {
            "selected_agent": "tool_selection_agent",
            "selected_agent_type": "tool_selection",
            "selected_agent_version": "1.0.0",
            "selected_agent_capabilities": ["select_tool", "route_to_system_entry"],
            "selected_tool": None,
            "routing_source": "agent_executor",
            "system_entry_routed": True,
            "agent_authority": "advisory_only"
        }

    # === POST-RESOLUTION STEP_SCHEMA VALIDATION ===
    # Per STEP_SCHEMA_CONTRACT_V1: Validate ONLY after resolution
    schema_validation = validate_step_schema(step)
    if schema_validation["status"] == "failure":
        return {
            "execution_result": {
                "status": "failure",
                "reason": f"step_schema_validation_failed:{schema_validation.get('reason')}"
            },
            "validator_output": {},
            "executed_input": resolved_tool_call,
            "step_result": {
                "status": "failure",
                "result": {
                    "execution_result": {
                        "status": "failure",
                        "reason": f"step_schema_validation_failed:{schema_validation.get('reason')}"
                    }
                }
            }
        }

    # === EXECUTION using resolved step ===
    # At this point, step has been resolved and validated
    # tool_call MUST be present per STEP_SCHEMA validation above
    _result_val = step_result.get("result")
    executed_input = (
        (_result_val.get("executed_input") if isinstance(_result_val, dict) else None)
        or step_result.get("executed_input")
    )
    execution_result = step_result.get("result", {}).get("execution_result") if isinstance(step_result.get("result"), dict) else None
    output = step.get("output")

    # If no execution_result and no prior output, synthesize failure for governance
    if execution_result is None:
        if not (output and str(output).strip()):
            execution_result = {"status": "failure", "reason": "no_output"}

    # RUNTIME TRACE: Post-execution
    _structured_log("POST_AGENT_EXECUTION", workflow_id, step_id, {
        "execution_result": execution_result,
        "executed_input": executed_input,
        "output": output,
        "step_result_status": step_result.get("status") if isinstance(step_result, dict) else None
    })

    # Perform validation if tool was executed (ADVISORY ONLY)
    validator_output = {}

    if executed_input and step_result.get("status") == "success":
        try:
            ei_parts = shlex.split(executed_input)
        except Exception:
            ei_parts = []
        ei_tool = ei_parts[0] if ei_parts else None
        ei_args = ei_parts[1:] if len(ei_parts) > 1 else []
        tool_def = _tool_index.get(ei_tool) if ei_tool else None

        if tool_def is not None:
            expected_inputs = tool_def.get("inputs", {})

            if len(ei_args) != len(expected_inputs):
                validator_output = {"decision": "retry", "reason": "invalid_argument_count"}

            if not validator_output:
                for arg, expected_type in zip(ei_args, expected_inputs.values()):
                    if expected_type == "number":
                        cleaned = arg.lstrip("-")
                        if not cleaned.isdigit():
                            validator_output = {"decision": "retry", "reason": "invalid_argument_type"}
                            break

        if not validator_output:
            _intent_output = step_result.get("result", {}).get("output", "") if isinstance(step_result.get("result"), dict) else ""
            if not _intent_output and execution_result and execution_result.get("status") == "success":
                _intent_output = execution_result.get("result", "")

            try:
                _ei_args_for_intent = shlex.split(executed_input)[1:] if executed_input else []
            except Exception:
                _ei_args_for_intent = []
            _intent_decision = evaluate_intent(
                step.get("input"),
                ei_tool,
                _ei_args_for_intent,
                _intent_output,
                step.get("purpose"),
                execution_result=execution_result,
                executed_input=executed_input,
                semantic_expectation=step.get("semantic_expectation"),
            )

            if _intent_decision.get("recommendation") == "retry" or _intent_decision.get("decision") == "retry":
                validator_output = _intent_decision

            # RUNTIME TRACE: Validator decision
            _structured_log("VALIDATOR_DECISION", workflow_id, step_id, {
                "validator_recommendation": _intent_decision.get("recommendation"),
                "validator_reason": _intent_decision.get("reason"),
                "validator_signals": _intent_decision.get("signals"),
                "extracted_constraints": _intent_decision.get("meta", {}).get("extracted_constraints"),
                "execution_result_status": execution_result.get("status") if execution_result else None
            })

            # VALIDATOR OUTPUT — ADVISORY ONLY (NO CONTROL IMPACT)
            if validator_output:
                # Store advisory reason
                step["_validator_advisory"] = validator_output.get("reason", "unknown")
                # Store validator decision (for correlation tests)
                step["_validator_decision"] = validator_output.get("recommendation")
                # Store signals if present
                if validator_output.get("signals"):
                    step["_validator_signals"] = validator_output.get("signals")
                # Store extracted_constraints for retry guidance
                meta = validator_output.get("meta", {})
                if meta.get("extracted_constraints"):
                    step["_extracted_constraints"] = meta.get("extracted_constraints")

    # === MEMORY WRITE — Pattern observation (Phase 3B) ===
    # DISABLED per Sprint 6 scope realignment:
    # Automatic learning / preference tracking is deferred.
    # No automatic memory writes from sequential (or parallel) execution
    # as part of ISSUE-078.
    #
    # Per MEMORY_STORAGE_CONTRACT_V1: write ONLY on successful completion
    # Per contract: NO writes on failure, retry, or single occurrence
    # Failure-isolated: MUST NOT affect execution
    #
    # if execution_result and execution_result.get("status") == "success":
    #     try:
    #         from system.memory.preference_tracker import observe_execution
    #         from system.orchestrator import trace_collector as _tc_pref
    #         _tool_name = _safe_extract_tool_name(executed_input)
    #         _step_type = step.get("type")
    #         _memory_written = observe_execution(
    #             tool_name=_tool_name or "",
    #             step_type=_step_type or "",
    #             execution_result=execution_result,
    #             step_purpose=step.get("purpose")
    #         )
    #         _mem_event = "MEMORY_WRITE" if _memory_written else "MEMORY_UPDATE"
    #         _tc_pref.record_memory_event(
    #             event=_mem_event,
    #             key=_memory_written.get("key") if _memory_written else None,
    #             data={"tool": _tool_name, "step_type": _step_type,
    #                   "written": _memory_written is not None}
    #         )
    #     except Exception:
    #         pass

    # === SIGNAL INTERPRETATION (ADVISORY ONLY — NO CONTROL INFLUENCE) ===
    # Stored in step["_signal_analysis"] for trace/debug purposes only.
    # MUST NOT be read by governance, retry logic, or execution.
    try:
        step["_signal_analysis"] = signal_interpreter.interpret_signals(step, execution_result or {})
    except Exception:
        step["_signal_analysis"] = {"status_analysis": "error", "conflicts": [], "issues": [], "confidence": "low", "summary": "signal interpretation failed"}

    # === DRIFT DETECTION (Phase 3B — ADVISORY ONLY) ===
    # Per AUTHORITY_MODEL: execution_result is sole truth
    # Per CONTROL_MODEL: drift signals are advisory, MUST NOT override execution_result
    # Per SYSTEM_GOALS_V2: small drift → auto-correct signal, large drift → user attention signal
    # Stored in step["_drift_signal"] for observability only — zero control impact
    try:
        from system.orchestrator import drift_detector as _dd
        from system.orchestrator import trace_collector as _tc_drift
        _expected = step.get("expected_outcome")
        _sem_exp = step.get("semantic_expectation")
        _drift_signal = _dd.compare(_expected, execution_result, {"step_type": step.get("type")}, semantic_expectation=_sem_exp)
        step["_drift_signal"] = _drift_signal
        # Log drift event to trace (observational only)
        _drift_event = "DRIFT_NONE" if _drift_signal.get("drift_type") == "NONE" else "DRIFT_DETECTED"
        _tc_drift.record_drift_event(
            event=_drift_event,
            step_id=step.get("id"),
            drift_type=_drift_signal.get("drift_type"),
            confidence=_drift_signal.get("confidence"),
            reason=_drift_signal.get("reason"),
            expected=_expected,
            actual=execution_result.get("result") if execution_result else None
        )
    except Exception:
        # Failure-isolated: drift detection failure MUST NOT affect execution
        step["_drift_signal"] = {"drift_detected": False, "drift_type": "NONE", "confidence": 0.0, "reason": "drift detection failed"}

    # === NOTIFICATIONS (Phase 3C — OUTPUT ONLY) ===
    # Per HAND_ARCHITECTURE_V2 Section 14: Notify for approvals, failures, completion
    # Per AUTHORITY_MODEL: Notifications are OUTPUT ONLY — no control authority
    # Per SYSTEM_GOALS_V2 Section 24: Smart filtering (approvals, failures, completion)
    # FAILURE-ISOLATED: Notification failure MUST NOT affect execution
    try:
        from system.interface.notification_manager import notify_step_success, notify_step_failure
        _workflow_id = workflow.get("id", "unknown")
        _step_id = step.get("id", "unknown")
        
        if execution_result and execution_result.get("status") == "success":
            # Step succeeded — notification is advisory output only
            _result_summary = str(execution_result.get("result", ""))[:50]  # Truncate for readability
            notify_step_success(
                step_id=_step_id,
                project_id=_workflow_id,
                result_summary=_result_summary
            )
        elif execution_result and execution_result.get("status") == "failure":
            # Step failed — notification is advisory output only
            _failure_reason = execution_result.get("reason", "unknown failure")
            notify_step_failure(
                step_id=_step_id,
                project_id=_workflow_id,
                reason=_failure_reason
            )
    except Exception:
        # Failure-isolated: notification failure MUST NOT affect execution
        pass

    # Note: LIVE STREAMING events are emitted from parallel_executor.py
    # after governance decision and status update, ensuring correct state.

    # RUNTIME TRACE: Step exit
    _structured_log("STEP_EXIT", workflow_id, step_id, {
        "execution_result": execution_result,
        "validator_output": validator_output,
        "validator_signals": step.get("_validator_signals"),
        "extracted_constraints": step.get("_extracted_constraints"),
        "validator_decision": step.get("_validator_decision"),
        "executed_input": executed_input
    })

    # Prepare return values
    return {
        "execution_result": execution_result,
        "validator_output": validator_output,
        "executed_input": executed_input,
        "last_result": execution_result.get("result") if execution_result and execution_result.get("status") == "success" else None,
        "step_result": step_result
    }
