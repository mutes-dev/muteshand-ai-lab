import json
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

_TOOL_INDEX_PATH = "system/tool_index/tools.json"
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
    # tool_call MUST be pre-validated — runtime does NOT construct/modify it
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
        # tool_call is set at creation — runtime does NOT modify
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
    from system.orchestrator.user_control import get_override
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
        
        # === STEP CREATION LIMIT CHECK (per cycle) ===
        # Reset at start of each cycle
        steps_created_this_cycle = 0
        # === SELECT NEXT STEP (ONLY PENDING - GOVERNANCE CONTROLS RETRY) ===
        pending_steps = [s for s in workflow["steps"] if s["status"] == "PENDING"]
        print(f"[STEP SELECT] Pending steps: {[(s.get('id'), s.get('status')) for s in pending_steps]}")
        step = next(
            (s for s in workflow["steps"] if s["status"] == "PENDING"),
            None
        )
        print(f"[STEP SELECT] Selected step: {step.get('id') if step else None}")

        if step is None:
            print("[STEP SELECT] No pending step found - breaking loop")
            break
        
        # === STEP CREATION LIMIT GUARD (future-safe) ===
        # Enforced before any dynamic step creation would occur
        if steps_created_this_cycle >= MAX_STEPS_PER_CYCLE:
            workflow["status"] = "BLOCKED"
            workflow["error"] = "step_creation_limit_exceeded"
            trace.append({
                "step_id": "workflow",
                "event": "workflow_blocked",
                "status": workflow["status"],
                "reason": "step_creation_limit_exceeded",
                "retries": 0
            })
            break

        trace.append({
            "step_id": step["id"],
            "event": "step_selected",
            "status": step["status"],
            "retries": step["retries"]
        })

        # Start execution
        step["status"] = "ACTIVE"
        trace.append({
            "step_id": step["id"],
            "event": "step_started",
            "status": step["status"],
            "retries": step["retries"]
        })

        # === CONTROLLED STEP CHAINING (PASSIVE) ===
        # === EXECUTION BOUNDARY ENFORCEMENT (Phase B) ===
        # Runtime NEVER modifies execution input
        # tool_call is set at step creation and used AS-IS
        # No operand injection, no purpose parsing, no chaining logic

        if step.get("attempt_history"):
            last_attempt = step["attempt_history"][-1]
            source_input = last_attempt.get("input", step["input"])
            current_input = source_input
        else:
            current_input = step["input"]

        if "attempt_history" not in step:
            step["attempt_history"] = []

        # Retry guidance for agent (separate from planner input)
        retry_guidance = None

        # CRITICAL FIX: Planner ALWAYS receives clean original input (ONCE per workflow step)
        planner_input = step["input"]
        steps_to_execute = [step]

        final_result = None

        # === SINGLE EXECUTION PER STEP (GOVERNANCE CONTROLS RETRY) ===
        for step_idx, step_input in enumerate(steps_to_execute):
            step_input = step

            # Initialize validator_output for this step (used in governance)
            validator_output = {}

            # === USER CONTROL: PAUSE CHECK (Phase 5) ===
            # MUST be non-blocking - returns immediately if paused
            from system.orchestrator.user_control import is_paused

            if is_paused():
                return {
                    "status": "success",
                    "result": {
                        "status": "paused",
                        "reason": "Execution paused by user"
                    }
                }

            # === STEP TOOL_CALL EXECUTION (DELEGATED TO step_executor) ===
            from system.orchestrator.step_executor import execute_step

            exec_data = execute_step(
                step=step,
                workflow=workflow,
                retry_guidance=retry_guidance,
                debug_verbose=DEBUG_VERBOSE
            )

            # Handle blocked (approval denied)
            if exec_data.get("blocked"):
                return {
                    "status": "success",
                    "result": {
                        "status": "blocked",
                        "reason": exec_data.get("blocked_reason", "User denied approval")
                    }
                }

            # Handle fail-fast (missing tool_call)
            execution_result = exec_data.get("execution_result")
            if execution_result and execution_result.get("reason") == "missing_tool_call":
                exec_res = execution_result
                step["execution_result"] = exec_res
                continue

            step_result = exec_data.get("step_result")
            executed_input = exec_data.get("executed_input")
            validator_output = exec_data.get("validator_output", {})
            last_result = exec_data.get("last_result")
            final_result = step_result

        result = final_result if final_result else {"status": "failure", "reason": "no_steps_executed"}
        executed_input = None
        if result and result.get("status") == "success":
            _result_val = result.get("result")
            executed_input = (
                (_result_val.get("executed_input") if isinstance(_result_val, dict) else None)
                or result.get("executed_input")
            )

        # === STEP RESULT PROCESSING (DELEGATED TO step_chainer) ===
        from system.orchestrator.step_chainer import propagate_result

        propagate_result(
            step=step,
            execution_result=execution_result,
            step_result=result,
            debug_verbose=DEBUG_VERBOSE
        )

        # Extract execution_result for governance decision
        exec_res = step.get("execution_result")

        # GOVERNANCE DECISION: Single source of truth for next action
        # Uses real validator_output from execution and real execution_result
        next_decision = governance.decide_next_action(
            validator_output=validator_output,
            execution_result=exec_res,
            step=step,
            context={"workflow": workflow}
        )

        # === TRACE CAPTURE: AFTER governance decision (READ-ONLY) ===
        try:
            trace_collector.record_governance(
                step_id=step["id"],
                decision=next_decision,
                execution_result=exec_res,
                context={"step_status": step["status"], "retries": step["retries"]}
            )
        except Exception:
            pass  # Trace failure must never affect execution

        # === BLOCK HANDLING (GOVERNANCE_CONTRACT) ===
        if next_decision == "block":
            step["status"] = "BLOCKED"
            workflow["status"] = "BLOCKED"
            step["blocked_reason"] = "approval_required"
            trace.append({
                "step_id": step["id"],
                "event": "step_blocked",
                "status": step["status"],
                "retries": step["retries"],
                "reason": "approval_required"
            })
            # BLOCK stops execution — user intervention required
            break

        # === RETRY HANDLING (DELEGATED TO ESCALATION CONTROLLER) ===
        if next_decision == "retry":
            result = escalation_controller.handle_retry(
                step=step,
                workflow=workflow,
                next_decision=next_decision
            )
            if result["action"] == "RETRY":
                if DEBUG_VERBOSE:
                    print("\n[DEBUG_RETRY_INPUT]:")
                    print(step["input"])
                continue
            elif result["action"] == "BLOCKED":
                # === USER CONTROL: OVERRIDE CHECK (Phase 5) ===
                # All BLOCKED states must pass through override
                from system.orchestrator.user_control import get_override
                print(f"[DEBUG OVERRIDE] action=BLOCKED, get_override()={get_override()}, workflow_status={workflow['status']}")
                if get_override():
                    print("[DEBUG OVERRIDE] OVERRIDE ACTIVE - attempting continue")
                    # Override enabled → skip termination and continue workflow
                    # BUT handle_retry has set workflow_status = BLOCKED!
                    # The loop condition will fail on next iteration
                    continue
                else:
                    print("[DEBUG OVERRIDE] no override - breaking")
                    break

        elif next_decision == "complete":
            step["status"] = "COMPLETED"
            # === STATE PROPAGATION (PASSIVE - via Memory Controller) ===
            # Store raw result value for clean chaining
            # ONLY update last_result on SUCCESS - failed execution must not corrupt chain
            from system.orchestrator.memory_controller import set_last_result, append_step_history
            if exec_res and exec_res.get("status") == "success":
                set_last_result(workflow, exec_res.get("result"))
            # DO NOT update last_result on failure - preserves clean chaining state
            append_step_history(workflow, {
                "step_id": step.get("id"),
                "result": exec_res
            })
            # === OUTPUT CONTRACT: execution_result IS the final output ===
            last_step = None
            for s in reversed(workflow.get("steps", [])):
                if s.get("execution_result") is not None:
                    last_step = s
                    break
            workflow["output"] = governance.resolve_decision(
                validator_output=validation if 'validation' in locals() else {},
                execution_result=exec_res,
                context={"last_step": last_step}
            )

            # === TRACE CAPTURE: AFTER step COMPLETED (READ-ONLY) ===
            try:
                trace_collector.record_step(
                    step_id=step["id"],
                    purpose=step.get("purpose", ""),
                    step_input=step.get("input"),
                    execution_result=exec_res,
                    governance_decision="complete",
                    retries=step["retries"],
                    status=step["status"],
                    validator_advisory=step.get("_validator_advisory"),
                    validator_signals=step.get("_validator_signals")
                )
            except Exception:
                pass  # Trace failure must never affect execution

            trace.append({
                "step_id": step["id"],
                "event": "step_completed",
                "status": step["status"],
                "retries": step["retries"]
            })

        # === ESCALATION HANDLING (DELEGATED TO ESCALATION CONTROLLER) ===
        elif next_decision in ("escalate", "fail"):
            # Delegate state mutations to escalation controller
            result = escalation_controller.handle_escalation(
                step=step,
                workflow=workflow,
                next_decision=next_decision,
                exec_res=exec_res
            )

            # === TRACE CAPTURE: AFTER step BLOCKED/ESCALATED (READ-ONLY) ===
            try:
                trace_collector.record_step(
                    step_id=step["id"],
                    purpose=step.get("purpose", ""),
                    step_input=step.get("input"),
                    execution_result=exec_res,
                    governance_decision=next_decision,
                    retries=step["retries"],
                    status=step["status"],
                    validator_advisory=step.get("_validator_advisory"),
                    validator_signals=step.get("_validator_signals")
                )
            except Exception:
                pass  # Trace failure must never affect execution

            trace.append({
                "step_id": step["id"],
                "event": "step_escalated",
                "status": step["status"],
                "retries": step["retries"]
            })
            trace.append({
                "step_id": "workflow",
                "event": "workflow_blocked",
                "status": workflow["status"],
                "retries": 0
            })

            # === USER CONTROL: OVERRIDE CHECK (Phase 5) ===
            # Override allows continuation when system would BLOCK
            # Does NOT change execution_result or governance
            from system.orchestrator.user_control import get_override

            if result["action"] == "BLOCKED" and get_override():
                # Override enabled - skip failure and continue
                continue
            elif result["action"] == "BLOCKED" and result.get("result"):
                return result["result"]
            elif result["action"] == "BLOCKED":
                break
            elif result["action"] == "COMPLETE":
                pass  # Continue to next step processing

        step_statuses = [(s.get('id'), s.get('status')) for s in workflow["steps"]]
        print(f"[POST-STEP CHECK] Step statuses: {step_statuses}")
        print(f"[POST-STEP CHECK] Any BLOCKED: {any(s['status'] == 'BLOCKED' for s in workflow['steps'])}")
        print(f"[POST-STEP CHECK] All COMPLETED: {all(s['status'] == 'COMPLETED' for s in workflow['steps'])}")
        
        if any(s["status"] == "BLOCKED" for s in workflow["steps"]):
            workflow["status"] = "BLOCKED"
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
            return {"status": "failure", "reason": reason}
        if step.get("status") not in ("COMPLETED",):
            return {"status": "failure", "reason": "step_failed"}
        # CRITICAL: Check execution_result even for COMPLETED steps
        # A step can complete but have a failed execution_result
        if exec_res and exec_res.get("status") == "failure":
            reason = exec_res.get("reason", "execution_failed")
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
            return {"status": "failure", "reason": "escalated"}
        if step.get("status") not in ("COMPLETED",):
            return {"status": "failure", "reason": "step_failed"}

    execution_result = workflow.get("output")
    print("[TRACE] final workflow output before return:", workflow.get("output"))
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
        # tool_call is set at step creation — runtime does NOT modify (Phase B)
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
