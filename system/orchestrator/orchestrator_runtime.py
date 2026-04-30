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


def extract_numbers(text: str):
    return [int(x) for x in text.split() if x.isdigit()]


def inject_result_into_purpose(purpose: str, value):
    return (
        purpose
        .replace("the result", str(value))
        .replace("result", str(value))
    )


def inject_result_into_purpose(purpose: str, value):
    return (
        purpose
        .replace("the result", str(value))
        .replace("result", str(value))
    )


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


def extract_constraints_llm(user_input: str) -> list:
    prompt = f"""
Extract explicit constraints from the user input.

A constraint is a requirement that MUST be satisfied in the final output.

IMPORTANT:
User input may contain BOTH instructions and constraints.
You MUST ignore general instructions but still extract constraints embedded inside them.

---

Examples:

Input: write a story that ends with the end
Output:
{{"constraints":[{{"type":"end_with","value":"the end"}}]}}

Input: must include the word cat
Output:
{{"constraints":[{{"type":"include","value":"cat"}}]}}

Input: write something funny but do not use numbers
Output:
{{"constraints":[{{"type":"exclude","value":"numbers"}}]}}

Input: write a poem
Output:
{{"constraints":[]}}

---

Rules:
- ONLY extract explicit constraints
- DO NOT infer or guess
- DO NOT rewrite the input
- IGNORE general instructions (like "write a story")
- BUT extract constraints embedded inside them
- Do NOT wrap JSON in quotes or markdown
- Output MUST be valid JSON
- Output MUST be on a single line
- Output MUST start with '{{' and end with '}}'

---

Return ONLY JSON in this exact format:

{{"constraints":[{{"type":"...","value":"..."}}]}}

If no constraints:

{{"constraints":[]}}

---

User input:
{user_input}
"""
    
    provider_result = get_llm("ollama_llm")
    if provider_result.get("status") != "success":
        return []
    
    provider = provider_result["provider"]
    result = execute_llm(provider, prompt)

    if result.get("status") != "success":
        return []

    raw_json = result.get("result", "{}")

    try:
        parsed = json.loads(raw_json)
        constraints = parsed.get("constraints", [])
        if DEBUG_VERBOSE:
            print(f"[constraints] {constraints}")
        return constraints
    except Exception:
        return []


def has_explicit_constraints(text: str) -> bool:
    keywords = ["do not", "without", "exclude", "avoid"]
    text_lower = text.lower()
    return any(k in text_lower for k in keywords)


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
    
    # Set safe defaults
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

    # Ensure all existing steps have metadata fields
    for step in workflow.get("steps", []):
        _ensure_step_metadata(step)
        # Initialize step status if not set
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
        step["status"] = "RUNNING"
        trace.append({
            "step_id": step["id"],
            "event": "step_started",
            "status": step["status"],
            "retries": step["retries"]
        })

        # === CONTROLLED STEP CHAINING (PASSIVE) ===
        # Chain previous step result to current step input (if no explicit args)
        from system.orchestrator.memory_controller import get_last_result
        last_result = get_last_result(workflow)

        # OPERAND COMPLETENESS CHECK: Inject last_result when execution would be invalid
        # Deterministic detection: count numeric operands, compare against operation requirements
        if step.get("args") is None:
            purpose = step.get("purpose", "")
            # Count numeric values in purpose (integers and decimals)
            import re
            numeric_operands = len(re.findall(r'\b\d+(?:\.\d+)?\b', purpose))

            # Minimal operand requirements for common operations
            operation_requirements = {
                "add": 2, "plus": 2, "sum": 2, "+": 2,
                "multiply": 2, "times": 2, "product": 2, "*": 2,
                "divide": 2, "divided by": 2, "/": 2,
                "subtract": 2, "minus": 2, "-": 2,
            }

            # Check if operation is indicated and operands are insufficient
            purpose_lower = purpose.lower()
            required_operands = None
            for op, req in operation_requirements.items():
                if op in purpose_lower:
                    required_operands = req
                    break

            # Inject ONLY when operation detected AND operands insufficient
            if required_operands is not None and numeric_operands < required_operands:
                if last_result is not None:
                    # Type safety extraction
                    if isinstance(last_result, dict) and "result" in last_result:
                        chained_value = last_result.get("result")
                    else:
                        chained_value = last_result
                    step["args"] = chained_value
                else:
                    # NEW: fallback when no valid chain value exists
                    step["args"] = 0

        # Fallback: Original chaining logic for explicit "the result" cases
        if last_result is not None and step.get("args") is None:
            # Type safety extraction (last_result should be raw value after FIX 1)
            if isinstance(last_result, dict) and "result" in last_result:
                chained_value = last_result.get("result")
            else:
                chained_value = last_result
            step["args"] = chained_value

        # executed_input will be set AFTER execution from actual tool call (line ~586)
        # DO NOT set it here - would capture planner's natural language instead of actual execution

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

            # === STRICT DETERMINISTIC INPUT SELECTION (PHASE 1.8) ===
            # Contract-safe: NO fallback to natural language for retry/chained
            # Governance decides outcomes; runtime reports deterministic failures
            is_retry = step.get("retries", 0) > 0
            executed_input = step.get("executed_input")
            args = step.get("args")

            if is_retry:
                # RETRY PATH: MUST use executed_input exclusively
                if executed_input:
                    agent_input = executed_input
                    if not agent_input.startswith("USE_TOOL:"):
                        agent_input = f"USE_TOOL: {agent_input}"
                else:
                    # CONTRACT-SAFE: Missing executed_input is execution failure
                    # Governance will decide next action (escalate/fail)
                    step_result = {
                        "status": "failure",
                        "result": {
                            "execution_result": {
                                "status": "failure",
                                "reason": "missing_executed_input"
                            }
                        }
                    }
                    # Skip to governance decision with failure result
                    exec_res = step_result["result"]["execution_result"]
                    step["execution_result"] = exec_res
                    # Trace the failure
                    try:
                        trace_collector.record_step_execution(
                            step_id=step["id"],
                            step_input=step.get("input"),
                            execution_result=exec_res,
                            governance_decision="deterministic_failure",
                            retries=step["retries"],
                            status=step["status"]
                        )
                    except Exception:
                        pass
                    # Let governance decide next action
                    continue
            elif args is not None:
                # CHAINED PATH: MUST use args injection (no natural language fallback)
                agent_input = inject_result_into_purpose(step["purpose"], args)
            else:
                # FIRST STEP: Natural language allowed (no prior execution)
                agent_input = step.get("purpose", step.get("input", ""))

            # === USER APPROVAL GATE (Phase 4) ===
            # Approval is a GATE, not a decision-maker
            # Does NOT modify governance, escalation, or execution_result
            from system.orchestrator.user_approval import requires_approval, request_approval

            if requires_approval(step, workflow):
                approved = request_approval(step)

                if not approved:
                    return {
                        "status": "success",
                        "result": {
                            "status": "blocked",
                            "reason": "User denied approval"
                        }
                    }

            step_result = execute_agent(
                agent={
                    "name": "generic_agent",
                    "role": "tool_executor",
                    "scope": ["tools"]
                },
                input_data=agent_input,
                retry_guidance=retry_guidance,
                context=None
            )
            print("[TRACE] step_result:", step_result)

            # Extract execution_result for validation
            _result_val = step_result.get("result")
            executed_input = (
                (_result_val.get("executed_input") if isinstance(_result_val, dict) else None)
                or step_result.get("executed_input")
            )
            execution_result = step_result.get("result", {}).get("execution_result") if isinstance(step_result.get("result"), dict) else None
            print("[TRACE] execution_result:", execution_result)
            output = step.get("output")

            # If no execution_result and no prior output, synthesize failure for governance
            if execution_result is None:
                if not (output and str(output).strip()):
                    execution_result = {"status": "failure", "reason": "no_output"}

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

                    print("\n# VALIDATOR INPUT")
                    print("user_input:", step_input)
                    print("candidate_output:", _intent_output)
                    print("constraints:", workflow.get("constraints"))
                    print("execution_result:", execution_result)

                    try:
                        _ei_args_for_intent = shlex.split(executed_input)[1:] if executed_input else []
                    except Exception:
                        _ei_args_for_intent = []
                    _intent_decision = evaluate_intent(
                        step_input["input"],
                        ei_tool,
                        _ei_args_for_intent,
                        _intent_output,
                        step_input.get("purpose"),
                        execution_result=execution_result,
                        executed_input=executed_input
                    )
                    print("\n# VALIDATOR RESULT\n", _intent_decision)
                    print("[TRACE] validator_output:", _intent_decision)

                    if _intent_decision.get("recommendation") == "retry":
                        validator_output = _intent_decision

                    # VALIDATOR OUTPUT — ADVISORY ONLY (NO CONTROL IMPACT)

                    if validator_output:
                        # Store advisory reason
                        step["_validator_advisory"] = validator_output.get("reason", "unknown")

                        # Store validator decision (for correlation tests)
                        step["_validator_decision"] = validator_output.get("recommendation")

                        # Store signals if present
                        if validator_output.get("signals"):
                            step["_validator_signals"] = validator_output.get("signals")

                    # Control flow and state mutation DISABLED per AUTHORITY_MODEL

                    # Validator signals must NOT influence execution

                    pass

                    if DEBUG_VERBOSE:
                        print("\n[DEBUG_VALIDATOR_SIGNALS]:")
                        print(_intent_decision.get("signals", {}))
                        print("--- END DEBUG_VALIDATOR_SIGNALS ---\n")

            # Update last_result from execution_result (governance decides action downstream)
            if execution_result and execution_result.get("status") == "success":
                try:
                    last_result = execution_result.get("result", None)
                except Exception:
                    last_result = None

            final_result = step_result

        result = final_result if final_result else {"status": "failure", "reason": "no_steps_executed"}
        executed_input = None
        if result and result.get("status") == "success":
            _result_val = result.get("result")
            executed_input = (
                (_result_val.get("executed_input") if isinstance(_result_val, dict) else None)
                or result.get("executed_input")
            )

        # === STEP RESULT PROCESSING ===
        # Update step metadata based on final result
        agent_result = result.get("result")
        tool_call = agent_result.get("reasoning") if isinstance(agent_result, dict) else agent_result

        has_tool_call = (
            isinstance(tool_call, str) and
            tool_call.startswith("USE_TOOL:")
        )

        if DEBUG_VERBOSE:
            print("\n[TOOL OBSERVER]")

        if DEBUG_VERBOSE:
            if has_tool_call:
                obs = observe_tool_call(tool_call)
                print(obs)
            else:
                print({
                    "skipped": True,
                    "reason": "no_tool_call",
                    "value": tool_call
                })
        if DEBUG_VERBOSE:
            print("TRACE agent_result:", agent_result)
            print("TRACE result:", result)

        # Unified propagation block
        if DEBUG_VERBOSE:
            print("TRACE entering propagation block")
        if isinstance(agent_result, dict):

            # execution_result propagation
            if DEBUG_VERBOSE:
                print("TRACE execution_result assigned:", agent_result.get("execution_result") if isinstance(agent_result, dict) else None)
            if agent_result.get("execution_result") is not None:
                step["execution_result"] = agent_result.get("execution_result")

            # output propagation
            execution_result = agent_result.get("execution_result")
            output = agent_result.get("output")
            if DEBUG_VERBOSE:
                print("TRACE output assigned:", output)

            # HARD RULE: execution_result is authoritative
            if execution_result and execution_result.get("status") == "success":
                step["output"] = execution_result.get("result")
            else:
                # Only use LLM output if NO tool executed
                step["output"] = output if output is not None else None

        exec_result = step.get("execution_result")
        agent_output = step.get("output")

        if exec_result and agent_output:
            expected = str(exec_result.get("result")).strip()
            actual = str(agent_output).strip()

            actual_tokens = actual.split()

            if expected not in actual_tokens:
                step["mismatch"] = True
            else:
                step["mismatch"] = False

        if "mismatch" not in step:
            step["mismatch"] = False

        if DEBUG_VERBOSE:
            print("TRACE step after propagation:", step)
        interpretation = interpret_agent_output(result)
        step["interpreted"] = interpretation

        # Keep interpretation for metadata but governance decides action
        decision = evaluate_interpretation(interpretation)
        step["decision"] = decision

        step["executed_input"] = agent_result.get("executed_input") if isinstance(agent_result, dict) else None

        # Ensure execution_result is always on step for governance
        if step.get("execution_result") is None and execution_result is not None:
            step["execution_result"] = execution_result

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

    # Step 3.1: Extract explicit constraints from user input (only if present)
    if has_explicit_constraints(user_input):
        constraints = extract_constraints_llm(user_input)
    else:
        constraints = []
    workflow["constraints"] = constraints

    # Step 3.5: Normalize planner output to executable format
    # Planner creates advisory workflows; runtime needs executable workflows
    if "name" not in workflow:
        workflow["name"] = workflow.get("goal", "auto_workflow")[:50]
    if "status" not in workflow:
        workflow["status"] = "ACTIVE"

    # Normalize steps to have required execution fields
    for step in workflow.get("steps", []):
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
