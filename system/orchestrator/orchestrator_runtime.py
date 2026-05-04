import json
import os
import shlex

DEBUG_VERBOSE = False

from system.entry.system_entry import system_entry
from system.orchestrator.workflow_validator import validate_workflow
from system.orchestrator.agent_executor import execute_agent
from system.orchestrator.agent_output_interpreter import interpret_agent_output
from system.orchestrator.decision_hook import evaluate_interpretation
from system.orchestrator.persistence import save_workflow
from system.orchestrator.orchestrator_planner import plan_workflow
from system.orchestrator.planner_output_validator import validate_planner_output
from system.orchestrator.planner_soft_guard import enforce_atomic_steps
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm


# === SAFETY CONSTRAINTS ===
MAX_STEPS_PER_WORKFLOW = 20
MAX_STEPS_PER_CYCLE = 1
from system.orchestrator.intent_validator import evaluate_intent
import system.orchestrator.governance as governance
from system.orchestrator import trace_collector
from system.orchestrator import escalation_controller
from system.orchestrator.conflict_detector import get_detector
from system.orchestrator.execution_scheduler import create_execution_group
from system.orchestrator.parallel_executor import execute_parallel_group, execute_sequential_group

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_TOOL_INDEX_PATH = os.path.join(_ROOT, "system", "tool_index", "tools.json")
with open(_TOOL_INDEX_PATH, "r", encoding="utf-8") as _f:
    _tool_index = json.load(_f)




def _ensure_step_metadata(step: dict) -> None:
    """
    Ensure step has required metadata fields for dynamic workflow support.
    Adds defaults if fields are missing (modifies step in-place).
    """
    if "created_at_runtime" not in step:
        step["created_at_runtime"] = False
    if "created_during_step" not in step:
        step["created_during_step"] = None


def observe_tool_call(tool_call: str) -> dict:
    issues = []

    if not isinstance(tool_call, str):
        issues.append("not_string")
        return {
            "tool_call": tool_call,
            "issues": issues,
            "issue_count": len(issues)
        }

    if not tool_call.startswith("USE_TOOL:"):
        issues.append("missing_prefix")

    if "|" in tool_call:
        issues.append("pipe_operator")

    if len(tool_call.strip()) == 0:
        issues.append("empty_call")

    return {
        "tool_call": tool_call,
        "issues": issues,
        "issue_count": len(issues)
    }



def add_step(workflow: dict, step_data: dict, parent_step_id: str = None) -> dict:
    """
    Add a new step to workflow at runtime.
    
    STRUCTURAL ONLY — Does NOT trigger execution or enforce runtime constraints.
    
    Args:
        workflow: The workflow dict to append step to
        step_data: Step definition (must include id, name, agent, input, etc.)
        parent_step_id: ID of step that triggered this step creation (optional)
        
    Returns:
        dict: Updated workflow with new step appended
        
    Rules:
    - Appends to workflow["steps"] list
    - Sets created_at_runtime = True
    - Sets created_during_step = parent_step_id
    - Does NOT modify existing steps
    - Does NOT reorder steps
    - Does NOT trigger execution
    - Does NOT enforce runtime constraints (enforced in runtime loop)
    """
    # Copy step_data to avoid modifying input
    new_step = dict(step_data)
    
    # Set runtime metadata
    new_step["created_at_runtime"] = True
    new_step["created_during_step"] = parent_step_id
    
    # Enforce STEP_SCHEMA_CONTRACT_V1 required fields with safe defaults
    new_step["type"] = new_step.get("type", "EXECUTE_API")
    # tool_call set by agent at execution time — runtime does NOT construct/modify it
    new_step["expected_outcome"] = new_step.get("expected_outcome", "Execution completed")
    new_step["risk"] = new_step.get("risk", "LOW")
    new_step["importance"] = new_step.get("importance", "MEDIUM")
    new_step["resource_targets"] = new_step.get("resource_targets", [])
    
    # Set runtime state fields
    new_step["status"] = new_step.get("status", "PENDING")
    new_step["retries"] = new_step.get("retries", 0)
    new_step["max_retries"] = new_step.get("max_retries", 2)
    
    # Ensure attempt_history exists
    if "attempt_history" not in new_step:
        new_step["attempt_history"] = []
    
    # Append to workflow steps
    if "steps" not in workflow:
        workflow["steps"] = []
    workflow["steps"].append(new_step)
    
    return workflow


def run_workflow(workflow: dict, return_trace: bool = False):
    # Ensure workflow["steps"] exists
    if "steps" not in workflow:
        workflow["steps"] = []

    # Ensure all existing steps have STEP_SCHEMA_CONTRACT_V1 fields
    for step in workflow.get("steps", []):
        _ensure_step_metadata(step)
        # Initialize schema fields with safe defaults
        if "type" not in step:
            step["type"] = "EXECUTE_API"
        # tool_call set by agent at execution time — runtime does NOT modify
        if "expected_outcome" not in step:
            step["expected_outcome"] = "Execution completed"
        if "risk" not in step:
            step["risk"] = "LOW"
        if "importance" not in step:
            step["importance"] = "MEDIUM"
        if "resource_targets" not in step:
            step["resource_targets"] = []
        # Initialize runtime state fields
        if "status" not in step:
            step["status"] = "PENDING"
        if "retries" not in step:
            step["retries"] = 0
        if "max_retries" not in step:
            step["max_retries"] = 3

    # Initialize workflow status if not set
    if "status" not in workflow:
        workflow["status"] = "ACTIVE"

    # === WORKFLOW CONTEXT INITIALIZATION (via Memory Controller) ===
    from system.orchestrator.memory_controller import get_context
    get_context(workflow)  # Ensures context exists
    
    validation = validate_workflow(workflow)
    if validation["status"] == "failure":
        workflow["output"] = {"status": "failure", "reason": validation["reason"]}
        return {"status": "failure", "reason": validation["reason"]}

    trace = []

    # === TRACE COLLECTOR INITIALIZATION (READ-ONLY OBSERVABILITY) ===
    trace_collector.create_collector(workflow.get("id", "unknown_workflow"))

    # === CONFLICT DETECTOR REGISTRATION (Phase 1A) ===
    conflict_detector = get_detector()
    conflict_detector.register_workflow(workflow.get("id", "unknown_workflow"))

    # === CHECKPOINT RESTORE (Phase 2C) — OBSERVATIONAL ONLY ===
    # Attempt to restore state from checkpoint BEFORE execution loop.
    # If checkpoint exists: restore step states (COMPLETED→skip, ACTIVE→FAILED, etc.)
    # If checkpoint missing or corrupt: start fresh (no effect on execution).
    # MUST NOT influence governance, scheduler, or execution logic.
    try:
        from system.orchestrator.checkpoint_manager import (
            load_checkpoint,
            restore_workflow_from_checkpoint,
        )
        _checkpoint = load_checkpoint(workflow.get("id", "unknown_workflow"))
        if _checkpoint is not None:
            restore_workflow_from_checkpoint(workflow, _checkpoint)
            print(f"[CHECKPOINT] Restored from checkpoint: {_checkpoint.get('last_completed_step_index', -1) + 1} step(s) recovered")
    except Exception:
        pass  # Checkpoint failure MUST NOT affect execution

    # === PERSISTENCE RESTORE (Phase 2D) — OBSERVATIONAL ONLY ===
    # Attempt to restore workflow state from persisted active workflow file.
    # If persisted state exists for this workflow: restore step states.
    # Normalize: ACTIVE (interrupted) → PENDING for re-evaluation.
    # MUST NOT influence governance, scheduler, or execution logic.
    try:
        from system.orchestrator.persistence import load_active_workflows
        _persisted_workflows = load_active_workflows()
        _wf_id = workflow.get("id", "unknown_workflow")
        _persisted = None
        for _pw in _persisted_workflows:
            if _pw.get("id") == _wf_id:
                _persisted = _pw
                break
        if _persisted is not None:
            # === PERSISTENCE GUARD (Identity Collision Fix) ===
            # Skip restore if persisted workflow has mismatched step IDs
            _persisted_step_ids = {s.get("id") for s in _persisted.get("steps", [])}
            _incoming_step_ids = {s.get("id") for s in workflow.get("steps", [])}
            if _persisted_step_ids != _incoming_step_ids:
                print(f"[PERSISTENCE] Skipped restore — step ID mismatch for {_wf_id}")
            else:
                _persisted_steps = {s.get("id"): s for s in _persisted.get("steps", [])}
                for step in workflow.get("steps", []):
                    _sid = step.get("id")
                    if _sid not in _persisted_steps:
                        continue
                    _ps = _persisted_steps[_sid]
                    _ps_status = _ps.get("status")
                    if _ps_status == "COMPLETED":
                        step["status"] = "COMPLETED"
                        step["execution_result"] = _ps.get("execution_result")
                        step["retries"] = _ps.get("retries", 0)
                    elif _ps_status == "FAILED":
                        step["status"] = "FAILED"
                        step["retries"] = _ps.get("retries", 0)
                    elif _ps_status == "BLOCKED":
                        step["status"] = "BLOCKED"
                        step["retries"] = _ps.get("retries", 0)
                        if _ps.get("blocked_reason"):
                            step["blocked_reason"] = _ps["blocked_reason"]
                    elif _ps_status == "ACTIVE":
                        # ACTIVE (interrupted) → PENDING for re-evaluation
                        step["status"] = "PENDING"
                        step["retries"] = _ps.get("retries", 0)
                print(f"[PERSISTENCE] Restored workflow {_wf_id} from persisted state")
        else:
            print(f"[PERSISTENCE] No persisted state for {_wf_id} — fresh start")
    except Exception:
        pass  # Persistence restore failure MUST NOT affect execution

    # === CONTEXT TRACKING FOR STEP-TO-STEP PASSING ===
    last_result = None

    # === SAFETY TRACKING VARIABLES ===
    # Track step creation per cycle (resets each iteration)
    steps_created_this_cycle = 0
    # Track recent outputs for loop detection
    _recent_outputs = []
    # Track hybrid (output, result) pairs for enhanced loop detection
    _recent_pairs = []

    loop_iteration = 0
    # === OVERRIDE-AWARE LOOP CONDITION (Phase 5 Fix) ===
    # Allow override to bypass BLOCKED termination
    # Loop continues if: NOT completed AND (not blocked OR override enabled)
    from system.orchestrator.user_control import get_override, is_paused
    from system.orchestrator.step_executor import execute_step
    from system.orchestrator.step_chainer import propagate_result

    while workflow["status"] != "COMPLETED" and not (
        workflow["status"] == "BLOCKED" and not get_override()
    ):
        loop_iteration += 1
        print(f"[LOOP TOP] Iteration {loop_iteration}, workflow_status: {workflow['status']}")
        if len(workflow.get("steps", [])) > MAX_STEPS_PER_WORKFLOW:
            workflow["status"] = "BLOCKED"
            workflow["error"] = "max_steps_exceeded"
            trace.append({
                "step_id": "workflow",
                "event": "workflow_blocked",
                "status": workflow["status"],
                "reason": "max_steps_exceeded",
                "retries": 0
            })
            break

        # === USER CONTROL: PAUSE CHECK (Phase 5) ===
        if is_paused():
            return {
                "status": "success",
                "result": {
                    "status": "paused",
                    "reason": "Execution paused by user"
                }
            }

        # === APPROVAL RESUME FLOW (Phase 1D — STATE_TRANSITIONS_CONTRACT_V1) ===
        # Before scheduling, check for approval-blocked steps.
        # Governance is the SOLE authority that decided BLOCK.
        # Runtime ONLY handles the approval interaction.
        # BLOCKED → ACTIVE transition per STATE_TRANSITIONS_CONTRACT_V1.
        for step in workflow.get("steps", []):
            if step.get("status") == "BLOCKED" and step.get("blocked_reason") == "approval_required":
                from system.orchestrator.user_approval import request_approval
                step_id = step.get("id", "unknown")

                # TRACE: APPROVAL_REQUIRED
                try:
                    trace_collector.record_transition(
                        step_id=step_id,
                        previous_status="BLOCKED",
                        new_status="BLOCKED",
                        reason="APPROVAL_REQUIRED"
                    )
                except Exception:
                    pass

                approved = request_approval(step)

                if approved:
                    # BLOCKED → ACTIVE (per STATE_TRANSITIONS_CONTRACT_V1)
                    step["status"] = "ACTIVE"
                    step.pop("blocked_reason", None)
                    step["_approval_resumed"] = True
                    # TRACE: APPROVAL_GRANTED
                    try:
                        trace_collector.record_transition(
                            step_id=step_id,
                            previous_status="BLOCKED",
                            new_status="ACTIVE",
                            reason="APPROVAL_GRANTED"
                        )
                    except Exception:
                        pass
                else:
                    # TRACE: APPROVAL_DENIED — step remains BLOCKED
                    try:
                        trace_collector.record_transition(
                            step_id=step_id,
                            previous_status="BLOCKED",
                            new_status="BLOCKED",
                            reason="APPROVAL_DENIED"
                        )
                    except Exception:
                        pass

        # === EXECUTION SCHEDULING (EXECUTION_SCHEDULING_CONTRACT_V1) ===
        # Build step_states map for scheduler
        step_states = {s.get("id"): s.get("status", "PENDING") for s in workflow.get("steps", [])}

        # Form NEXT execution group (scheduler derives groups dynamically)
        group = create_execution_group(
            workflow=workflow,
            step_states=step_states,
            conflict_detector=conflict_detector,
            workflow_id=workflow.get("id", "unknown_workflow")
        )

        if group is None:
            print("[SCHEDULER] No execution group formed - no pending steps or previous group incomplete")
            break

        print(f"[SCHEDULER] Group formed: {group['group_id']} type={group['group_type']} steps={group['steps']}")

        # === GROUP-BASED EXECUTION ===
        group_type = group.get("group_type", "SEQUENTIAL")

        if group_type == "PARALLEL" and len(group.get("steps", [])) > 1:
            # === PARALLEL GROUP EXECUTION ===
            group_results = execute_parallel_group(
                group=group,
                workflow=workflow,
                execute_step_fn=execute_step,
                governance_fn=governance.decide_next_action,
                propagate_fn=propagate_result,
                escalation_handler=escalation_controller,
                debug_verbose=DEBUG_VERBOSE
            )
        else:
            # === SEQUENTIAL GROUP EXECUTION ===
            group_results = execute_sequential_group(
                group=group,
                workflow=workflow,
                execute_step_fn=execute_step,
                governance_fn=governance.decide_next_action,
                propagate_fn=propagate_result,
                escalation_handler=escalation_controller,
                debug_verbose=DEBUG_VERBOSE
            )

        # === POST-GROUP PROCESSING ===
        # Process results from group execution
        for step_result in group_results:
            step_id = step_result.get("step_id")
            step_status = step_result.get("status")
            gov_decision = step_result.get("governance_decision")
            exec_res = step_result.get("execution_result")

            # Find the step object
            step = next((s for s in workflow["steps"] if s.get("id") == step_id), None)
            if not step:
                continue

            trace.append({
                "step_id": step_id,
                "event": f"step_{step_status.lower()}" if step_status else "step_unknown",
                "status": step_status,
                "retries": step.get("retries", 0)
            })

            # === OUTPUT CONTRACT: Update workflow output on completion ===
            if step_status == "COMPLETED" and exec_res:
                last_step = None
                for s in reversed(workflow.get("steps", [])):
                    if s.get("execution_result") is not None:
                        last_step = s
                        break
                workflow["output"] = governance.resolve_decision(
                    validator_output={},
                    execution_result=exec_res,
                    context={"last_step": last_step}
                )

        # === WORKFLOW STATE UPDATE (post-group boundary) ===
        step_statuses = [(s.get('id'), s.get('status')) for s in workflow["steps"]]
        print(f"[POST-GROUP CHECK] Step statuses: {step_statuses}")
        print(f"[POST-GROUP CHECK] Any BLOCKED: {any(s['status'] == 'BLOCKED' for s in workflow['steps'])}")
        print(f"[POST-GROUP CHECK] All COMPLETED: {all(s['status'] == 'COMPLETED' for s in workflow['steps'])}")

        if any(s["status"] == "BLOCKED" for s in workflow["steps"]):
            workflow["status"] = "BLOCKED"
            # === PERSIST BLOCKED STATE (Phase 2D) ===
            try:
                save_workflow(workflow)
            except Exception:
                pass
            trace.append({
                "step_id": "workflow",
                "event": "workflow_blocked",
                "status": workflow["status"],
                "retries": 0
            })
            execution_result = workflow.get("output")
            if execution_result is not None:
                if execution_result.get("status") == "failure":
                    if workflow.get("output") is None:
                        for s in reversed(workflow.get("steps", [])):
                            if s.get("execution_result") is not None:
                                workflow["output"] = s.get("execution_result")
                                break
                    return {"status": "failure", "reason": execution_result.get("reason")}
                break
            else:
                return {"status": "failure", "reason": "No execution_result"}
        elif all(s["status"] == "COMPLETED" for s in workflow["steps"]):
            workflow["status"] = "COMPLETED"
            trace.append({
                "step_id": "workflow",
                "event": "workflow_completed",
                "status": workflow["status"],
                "retries": 0
            })
            save_workflow(workflow)
            # === CLEANUP ACTIVE WORKFLOW FILE (Phase 2D) ===
            try:
                from system.orchestrator.persistence import delete_workflow
                delete_workflow(workflow.get("id", "unknown_workflow"))
            except Exception:
                pass
            execution_result = workflow.get("output")
            if execution_result is not None:
                if execution_result.get("status") == "failure":
                    if workflow.get("output") is None:
                        for s in reversed(workflow.get("steps", [])):
                            if s.get("execution_result") is not None:
                                workflow["output"] = s.get("execution_result")
                                break
                    return {"status": "failure", "reason": execution_result.get("reason")}
                break
            else:
                return {"status": "failure", "reason": "No execution_result"}
        else:
            workflow["status"] = "ACTIVE"
            # === PERSIST ACTIVE STATE (Phase 2D) ===
            try:
                save_workflow(workflow)
            except Exception:
                pass

    # === LOOP EXIT DEBUG ===
    print(f"[LOOP EXIT] Loop ended at iteration {loop_iteration}")
    print(f"[LOOP EXIT] workflow_status: {workflow['status']}")
    print(f"[LOOP EXIT] step statuses: {[(s.get('id'), s.get('status')) for s in workflow.get('steps', [])]}")
    
    save_workflow(workflow)
    # Guarantee output field exists
    if "output" not in workflow:
        workflow["output"] = None

    # FAILURE DETECTION GATE: Check for BLOCKED/FAILED steps BEFORE fallback
    # Prevents successful step result from masking later step failures
    for step in workflow.get("steps", []):
        exec_res = step.get("execution_result")
        
        if step.get("status") == "BLOCKED":
            # Use step's execution_result if available, otherwise generic error
            reason = exec_res.get("reason") if exec_res else workflow.get("error", "escalated")
            # Unregister workflow on blocked exit
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": reason}
        if step.get("status") not in ("COMPLETED",):
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": "step_failed"}
        # CRITICAL: Check execution_result even for COMPLETED steps
        # A step can complete but have a failed execution_result
        if exec_res and exec_res.get("status") == "failure":
            reason = exec_res.get("reason", "execution_failed")
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": reason}

    # FALLBACK: Only use SUCCESSFUL execution results from completed steps
    if workflow.get("output") is None:
        exec_res_fallback = None
        for s in reversed(workflow.get("steps", [])):
            # Only consider COMPLETED steps with successful execution
            if s.get("status") == "COMPLETED" and s.get("execution_result") is not None:
                exec_res = s.get("execution_result")
                if exec_res.get("status") == "success":
                    exec_res_fallback = exec_res
                    break
        if exec_res_fallback is not None:
            workflow["output"] = exec_res_fallback

    # FINAL VALIDATION GATE: Ensure all steps completed or escalated
    for step in workflow.get("steps", []):
        if step.get("status") == "BLOCKED":
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": "escalated"}
        if step.get("status") not in ("COMPLETED",):
            conflict_detector.unregister_workflow(workflow["id"])
            return {"status": "failure", "reason": "step_failed"}

    execution_result = workflow.get("output")
    print("[TRACE] final workflow output before return:", workflow.get("output"))

    # === CONFLICT DETECTOR UNREGISTRATION (Phase 1A) ===
    # Clean up workflow from active registry on completion
    conflict_detector.unregister_workflow(workflow["id"])

    # === CHECKPOINT CLEANUP (Phase 2C) ===
    # Delete checkpoint after workflow reaches terminal state.
    # Failure is silently ignored — MUST NOT affect execution.
    try:
        from system.orchestrator.checkpoint_manager import delete_checkpoint
        delete_checkpoint(workflow.get("id", "unknown_workflow"))
    except Exception:
        pass

    # === PERSISTENCE CLEANUP (Phase 2D) ===
    # Delete active workflow file after workflow reaches terminal state.
    # Failure is silently ignored — MUST NOT affect execution.
    if workflow.get("status") == "COMPLETED":
        try:
            from system.orchestrator.persistence import delete_workflow
            delete_workflow(workflow.get("id", "unknown_workflow"))
        except Exception:
            pass

    if execution_result is not None:
        if execution_result.get("status") == "failure":
            return {"status": "failure", "reason": execution_result.get("reason")}
        for step in workflow.get("steps", []):
            if step.get("status") != "COMPLETED":
                return {"status": "failure", "reason": "step_failed"}
        return {"status": "success", "result": execution_result, "trace": trace_collector.get_trace()}
    else:
        return {"status": "failure", "reason": "No execution_result"}


def execute_from_input(user_input: str) -> dict:
    """
    Entry point: user_input → planner → workflow → runtime execution.

    Connects the planner to the runtime without mixing their concerns.
    - Planner decides WHAT (creates workflow)
    - Runtime decides HOW (executes steps)
    """
    # Step 0: Task classification (ADVISORY ONLY - does not influence execution)
    from system.orchestrator.task_classifier import classify_task
    classification = classify_task(user_input)

    # Normalize classification to safe structure (ADVISORY ONLY - fail-safe)
    if not isinstance(classification, dict):
        classification = {}

    classification = {
        "classification": classification.get("classification"),
        "autonomy_level": classification.get("autonomy_level"),
        "approval_required": bool(classification.get("approval_required", False)),
        "reasoning": classification.get("reasoning"),
        "confidence": classification.get("confidence"),
    }

    # Step 1: Create workflow via planner (classification is advisory signal only)
    workflow_result = plan_workflow(user_input, classification=classification)

    # Step 2: Validate workflow creation
    if workflow_result.get("status") != "success":
        return {"status": "failure", "reason": "planner_failed"}

    # Step 3: Extract workflow
    workflow = workflow_result.get("workflow", {})

    # Store classification in workflow for observability (advisory only, no control impact)
    workflow["classification"] = classification

    # Step 3.0: Observational validation of planner output (read-only, no control flow)
    planner_steps = workflow.get("steps", [])
    planner_validation = validate_planner_output(planner_steps)
    if not planner_validation.get("valid", True):
        print("[PLANNER_VALIDATOR_OBSERVATION] issues detected:", planner_validation.get("issues", []))

    # Step 3.1: Constraint extraction REMOVED (Phase B)
    # Runtime does NOT use LLM for constraint extraction
    # Constraints must be explicitly provided in workflow or step
    constraints = workflow.get("constraints", [])

    # Step 3.2: Soft structural guard — detect and split collapsed multi-objective steps
    # Advisory structural correction only — does not affect governance or system_entry
    workflow = enforce_atomic_steps(workflow)

    # Step 3.5: Normalize planner output to executable format
    # Planner creates advisory workflows; runtime needs executable workflows
    if "name" not in workflow:
        workflow["name"] = workflow.get("goal", "auto_workflow")[:50]
    if "status" not in workflow:
        workflow["status"] = "ACTIVE"

    # Normalize steps to have STEP_SCHEMA_CONTRACT_V1 required fields
    for step in workflow.get("steps", []):
        if "type" not in step:
            step["type"] = "EXECUTE_API"
        # tool_call set by agent at execution time — runtime does NOT modify
        if "expected_outcome" not in step:
            step["expected_outcome"] = "Execution completed"
        if "risk" not in step:
            step["risk"] = "LOW"
        if "importance" not in step:
            step["importance"] = "MEDIUM"
        if "resource_targets" not in step:
            step["resource_targets"] = []
        if "status" not in step:
            step["status"] = "PENDING"
        if "retries" not in step:
            step["retries"] = 0
        if "max_retries" not in step:
            step["max_retries"] = 2
        if "input" not in step:
            step["input"] = step.get("purpose", user_input)

    # Step 4: Execute via runtime (preserves all existing logic)
    result = run_workflow(workflow)

    if result and result.get("status") == "success":
        execution_result = result.get("result")
    elif result and result.get("status") == "failure":
        # run_workflow detected a failure - preserve it
        return {"status": "failure", "reason": result.get("reason", "workflow_failed"), "trace": trace_collector.get_trace()}
    else:
        execution_result = workflow.get("output")

    governance_output = governance.resolve_decision(
        validator_output={},
        execution_result=execution_result,
        context={"last_step": None}
    )

    # Preserve original execution_result if governance returns None
    if governance_output is not None:
        execution_result = governance_output
    if execution_result is not None:
        if execution_result.get("status") == "failure":
            return {"status": "failure", "reason": execution_result.get("reason"), "trace": trace_collector.get_trace()}
        return {"status": "success", "result": execution_result, "trace": trace_collector.get_trace()}
    else:
        return {"status": "failure", "reason": "No execution_result", "trace": trace_collector.get_trace()}
