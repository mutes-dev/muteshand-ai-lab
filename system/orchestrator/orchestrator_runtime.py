import json
import shlex

from system.entry.system_entry import system_entry
from system.orchestrator.workflow_validator import validate_workflow
from system.orchestrator.agent_executor import execute_agent
from system.orchestrator.agent_output_interpreter import interpret_agent_output
from system.orchestrator.decision_hook import evaluate_interpretation
from system.orchestrator.persistence import save_workflow
from system.orchestrator.orchestrator_planner import create_workflow, plan_workflow
from system.orchestrator.llm_registry import get_llm
from system.orchestrator.llm_executor import execute_llm


# === SAFETY CONSTRAINTS ===
MAX_STEPS_PER_WORKFLOW = 20
MAX_STEPS_PER_CYCLE = 1
from system.memory.execution_memory import apply_memory, learn_from_attempts
from system.orchestrator.intent_validator import evaluate_intent

_TOOL_INDEX_PATH = "system/tool_index/tools.json"
with open(_TOOL_INDEX_PATH, "r", encoding="utf-8") as _f:
    _tool_index = json.load(_f)


def extract_numbers(text: str):
    return [int(x) for x in text.split() if x.isdigit()]


def _ensure_step_metadata(step: dict) -> None:
    """
    Ensure step has required metadata fields for dynamic workflow support.
    Adds defaults if fields are missing (modifies step in-place).
    """
    if "created_at_runtime" not in step:
        step["created_at_runtime"] = False
    if "created_during_step" not in step:
        step["created_during_step"] = None


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
        print(f"[constraints] {constraints}")
        return constraints
    except Exception:
        return []


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
    # Ensure all existing steps have metadata fields
    for step in workflow.get("steps", []):
        _ensure_step_metadata(step)
    
    # === WORKFLOW CONTEXT INITIALIZATION ===
    if "context" not in workflow:
        workflow["context"] = {
            "last_result": None,
            "step_history": []
        }
    
    validation = validate_workflow(workflow)
    if validation["status"] == "failure":
        if return_trace:
            return {
                "workflow": {
                    "status": "failure",
                    "reason": validation["reason"]
                },
                "trace": []
            }
        else:
            return {
                "status": "failure",
                "reason": validation["reason"]
            }

    trace = []

    # === CONTEXT TRACKING FOR STEP-TO-STEP PASSING ===
    last_result = None

    # === SAFETY TRACKING VARIABLES ===
    # Track step creation per cycle (resets each iteration)
    steps_created_this_cycle = 0
    # Track recent outputs for loop detection
    _recent_outputs = []
    # Track hybrid (output, result) pairs for enhanced loop detection
    _recent_pairs = []

    while workflow["status"] not in ["COMPLETED", "BLOCKED"]:
        # === MAX STEP LIMIT CHECK ===
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
        step = next(
            (
                s for s in workflow["steps"]
                if s["status"] == "PENDING"
                or (s["status"] == "FAILED" and s["retries"] < s["max_retries"])
            ),
            None
        )

        if step is None:
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

        if step["status"] == "PENDING":
            step["status"] = "RUNNING"
            trace.append({
                "step_id": step["id"],
                "event": "step_started",
                "status": step["status"],
                "retries": step["retries"]
            })
        elif step["status"] == "FAILED" and step["retries"] < step["max_retries"]:
            trace.append({
                "step_id": step["id"],
                "event": "step_retry",
                "status": step["status"],
                "retries": step["retries"]
            })
            step["status"] = "RUNNING"
            trace.append({
                "step_id": step["id"],
                "event": "step_started",
                "status": step["status"],
                "retries": step["retries"]
            })

        # === CONTROLLED STEP CHAINING (PASSIVE) ===
        # Chain previous step result to current step input (if no explicit args)
        last_result = workflow.get("context", {}).get("last_result")
        if last_result is not None and step.get("args") is None:
            # Type safety extraction
            if isinstance(last_result, dict):
                chained_value = last_result.get("result")
            else:
                chained_value = last_result
            step["args"] = chained_value

        if step.get("attempt_history"):
            last_attempt = step["attempt_history"][-1]
            source_input = last_attempt.get("input", step["input"])
            current_input = apply_memory(source_input)
        else:
            current_input = apply_memory(step["input"])

        if "attempt_history" not in step:
            step["attempt_history"] = []

        # Retry guidance for agent (separate from planner input)
        retry_guidance = None

        # CRITICAL FIX: Planner ALWAYS receives clean original input (ONCE per workflow step)
        planner_input = step["input"]

        workflow_plan = plan_workflow(planner_input)
        steps_to_execute = workflow_plan.get("steps", [current_input])

        final_result = None

        # === STEP-LEVEL EXECUTION WITH INDEPENDENT RETRY ===
        # Each sub-step has its own retry loop - successful steps are NOT re-executed
        for step_idx, step_input in enumerate(steps_to_execute):
            # Per-step retry tracking
            step_retries = 0
            step_max_retries = step.get("max_retries", 3)
            step_success = False
            step_retry_guidance = retry_guidance  # Inherit from parent step

            while step_retries <= step_max_retries and not step_success:
                # Prepare context for agent (ephemeral, per-step)
                agent_context = {"last_result": last_result} if last_result is not None else None

                step_result = execute_agent(
                    agent={
                        "name": "generic_agent",
                        "role": "tool_executor",
                        "scope": ["tools"]
                    },
                    input_data=step_input,
                    retry_guidance=step_retry_guidance,
                    context=agent_context
                )

                if step_result.get("status") == "success":
                    # Validate the successful step BEFORE updating last_result
                    _result_val = step_result.get("result")
                    executed_input = (
                        (_result_val.get("executed_input") if isinstance(_result_val, dict) else None)
                        or step_result.get("executed_input")
                    )

                    if executed_input:
                        # Perform validation on successful execution
                        try:
                            ei_parts = shlex.split(executed_input)
                        except ValueError:
                            ei_parts = executed_input.split()
                        ei_tool = ei_parts[0] if ei_parts else None
                        ei_args = ei_parts[1:] if len(ei_parts) > 1 else []
                        tool_def = _tool_index.get(ei_tool) if ei_tool else None

                        validation_passed = True

                        if tool_def is not None:
                            expected_inputs = tool_def.get("inputs", {})

                            # Argument count check
                            if len(ei_args) != len(expected_inputs):
                                validation_passed = False
                                if step_retries < step_max_retries:
                                    step_retry_guidance = (
                                        f"Previous attempt failed.\n\n"
                                        f"Failure reason: invalid_argument_count\n\n"
                                        f"The tool expects {len(expected_inputs)} arguments but received {len(ei_args)}.\n\n"
                                        "Fix the input and retry using USE_TOOL format.\n\n"
                                        "STRICT RULES:\n"
                                        "- DO NOT change any numbers\n"
                                        "- DO NOT change any values\n"
                                        "- ONLY fix formatting or syntax errors"
                                    )

                            # Argument type check
                            if validation_passed:
                                for arg, expected_type in zip(ei_args, expected_inputs.values()):
                                    if expected_type == "number":
                                        cleaned = arg.lstrip("-")
                                        if not cleaned.isdigit():
                                            validation_passed = False
                                            if step_retries < step_max_retries:
                                                step_retry_guidance = (
                                                    f"Previous attempt failed.\n\n"
                                                    f"Failure reason: invalid_argument_type\n\n"
                                                    "One or more arguments have incorrect type. Numbers are required.\n\n"
                                                    "Fix the input and retry using USE_TOOL format.\n\n"
                                                    "STRICT RULES:\n"
                                                    "- DO NOT change any numbers\n"
                                                    "- DO NOT change any values\n"
                                                    "- ONLY fix formatting or syntax errors"
                                                )
                                            break

                        if validation_passed:
                            # Intent validation (structural)
                            _executed_input = executed_input
                            _intent_tool = ei_tool
                            _intent_output = step_result.get("result", {}).get("output", "") if isinstance(step_result.get("result"), dict) else ""
                            execution_result = step_result.get("result", {}).get("execution_result") if isinstance(step_result.get("result"), dict) else None

                            print("\n# VALIDATOR INPUT")
                            print("user_input:", step_input)
                            print("candidate_output:", _intent_output)
                            print("constraints:", workflow.get("constraints"))
                            print("execution_result:", execution_result)

                            _intent_decision = evaluate_intent(
                                step_input,
                                _intent_tool,
                                execution_result,
                                _intent_output,
                                executed_input=_executed_input,
                                last_result=last_result
                            )
                            print("\n# VALIDATOR RESULT\n", _intent_decision)

                            if _intent_decision["decision"] == "retry":
                                validation_passed = False
                                if step_retries < step_max_retries:
                                    step_retry_guidance = (
                                        f"Previous attempt failed.\n\n"
                                        f"Failure reason: {_intent_decision['reason']}\n\n"
                                        "Fix the input and retry using USE_TOOL format.\n\n"
                                        "STRICT RULES:\n"
                                        "- DO NOT change any numbers\n"
                                        "- DO NOT change any values\n"
                                        "- ONLY fix formatting or syntax errors"
                                    )

                        if validation_passed:
                            # === UPDATE last_result ONLY AFTER FULL VALIDATION ===
                            try:
                                last_result = step_result.get("result", {}) \
                                                   .get("execution_result", {}) \
                                                   .get("result", None)
                            except Exception:
                                last_result = None

                            step_success = True
                            final_result = step_result
                        else:
                            step_retries += 1
                    else:
                        # No executed_input (non-tool execution) - still update last_result
                        try:
                            last_result = step_result.get("result", {}) \
                                               .get("execution_result", {}) \
                                               .get("result", None)
                        except Exception:
                            last_result = None

                        step_success = True
                        final_result = step_result
                else:
                    # Agent execution failed
                    step_retries += 1
                    if step_retries <= step_max_retries:
                        step_retry_guidance = (
                            f"Previous attempt failed.\n\n"
                            f"Failure reason: {step_result.get('reason', 'unknown_error')}\n\n"
                            "Fix the input and retry using USE_TOOL format.\n\n"
                            "STRICT RULES:\n"
                            "- DO NOT change any numbers\n"
                            "- DO NOT change any values\n"
                            "- ONLY fix formatting or syntax errors"
                        )

            if not step_success:
                # Step failed after max retries
                step["status"] = "FAILED"
                step["error"] = f"failed_after_{step_retries}_retries"
                final_result = step_result if step_result else {"status": "failure", "reason": "max_retries_exceeded"}
                break  # Exit the for loop, workflow stops here

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
        agent_result = result.get("result", {}) if result.get("status") == "success" else {}

        # Detect non-tool execution
        if not agent_result.get("executed_input"):
            # Skip interpretation — already valid output
            step["output"] = agent_result.get("output")
            step["decision"] = {
                "status": "success",
                "decision": {
                    "flag": "review_ok",
                    "reason": "no_tool_required"
                }
            }

        interpretation = interpret_agent_output(result)
        step["interpreted"] = interpretation

        decision = evaluate_interpretation(interpretation)
        step["decision"] = decision

        # === STEP RESULT PROPAGATION ===
        # Store execution results into step for reporting
        # Extract from nested agent_executor result structure
        agent_result = result.get("result", {}) if result.get("status") == "success" else {}
        step["output"] = agent_result.get("output")
        print("\n# STEP OUTPUT\n", step["output"])
        step["executed_input"] = agent_result.get("executed_input")
        step["execution_result"] = agent_result.get("execution_result")

        if decision.get("status") == "success":
            step["status"] = "COMPLETED"
            workflow["status"] = "COMPLETED"
            break

        if (
            isinstance(decision, dict) and
            decision.get("status") == "success" and
            isinstance(decision.get("decision"), dict) and
            decision["decision"].get("flag") == "review_failed"
        ):
            step["action_required"] = True

        if step["status"] not in ["FAILED", "BLOCKED"]:
            if result["status"] == "success":
                step["status"] = "COMPLETE"
                # === STATE PROPAGATION (PASSIVE) ===
                execution_result = result["result"]
                workflow["context"]["last_result"] = execution_result
                workflow["context"]["step_history"].append({
                    "step_id": step.get("id"),
                    "result": execution_result
                })

            # === NON-PROGRESS LOOP DETECTION ===
            # Track output for loop detection
            # Extract result value from execution_result for hybrid tracking
            exec_res = step.get("execution_result")
            result_value = None
            if exec_res is not None:
                result_value = exec_res.get("result")
            # Track hybrid (output, result) pairs
            _recent_pairs.append((step["output"], result_value))
            # Keep only last 3 pairs
            if len(_recent_pairs) > 3:
                _recent_pairs.pop(0)
            _recent_outputs.append(step["output"])
            # Keep only last 3 entries
            if len(_recent_outputs) > 3:
                _recent_outputs.pop(0)
            # Check for non-progress loop (3 identical consecutive pairs)
            if len(_recent_pairs) == 3 and all(p == _recent_pairs[0] for p in _recent_pairs):
                workflow["status"] = "BLOCKED"
                workflow["error"] = "non_progress_loop_detected"
                trace.append({
                    "step_id": step["id"],
                    "event": "step_blocked",
                    "status": step["status"],
                    "reason": "non_progress_loop_detected",
                    "retries": step["retries"]
                })
                trace.append({
                    "step_id": "workflow",
                    "event": "workflow_blocked",
                    "status": workflow["status"],
                    "retries": 0
                })
                if return_trace:
                    return {"workflow": workflow, "trace": trace}
                else:
                    return workflow

            trace.append({
                "step_id": step["id"],
                "event": "step_completed",
                "status": step["status"],
                "retries": step["retries"]
            })
        else:
            step["status"] = "FAILED"
            step["error"] = result["reason"]
            step["retries"] += 1
            trace.append({
                "step_id": step["id"],
                "event": "step_failed",
                "status": step["status"],
                "retries": step["retries"]
            })

        if step["status"] == "FAILED" and step["retries"] >= step["max_retries"]:
            step["status"] = "BLOCKED"
            trace.append({
                "step_id": step["id"],
                "event": "step_blocked",
                "status": step["status"],
                "retries": step["retries"]
            })
            workflow["status"] = "BLOCKED"
            trace.append({
                "step_id": "workflow",
                "event": "workflow_blocked",
                "status": workflow["status"],
                "retries": 0
            })
            if return_trace:
                return {"workflow": workflow, "trace": trace}
            else:
                return workflow

        if any(s["status"] == "BLOCKED" for s in workflow["steps"]):
            workflow["status"] = "BLOCKED"
            trace.append({
                "step_id": "workflow",
                "event": "workflow_blocked",
                "status": workflow["status"],
                "retries": 0
            })
            if return_trace:
                return {"workflow": workflow, "trace": trace}
            else:
                return workflow
        elif all(s["status"] == "COMPLETE" for s in workflow["steps"]):
            workflow["status"] = "COMPLETED"
            trace.append({
                "step_id": "workflow",
                "event": "workflow_completed",
                "status": workflow["status"],
                "retries": 0
            })
            save_workflow(workflow)
            if return_trace:
                return {"workflow": workflow, "trace": trace}
            else:
                return workflow
        else:
            workflow["status"] = "ACTIVE"

    save_workflow(workflow)
    if return_trace:
        return {"workflow": workflow, "trace": trace}
    else:
        return workflow


def execute_from_input(user_input: str) -> dict:
    """
    Entry point: user_input → planner → workflow → runtime execution.

    Connects the planner to the runtime without mixing their concerns.
    - Planner decides WHAT (creates workflow)
    - Runtime decides HOW (executes steps)
    """
    # Step 1: Create workflow via planner
    workflow_result = create_workflow(user_input)

    # Step 2: Validate workflow creation
    if workflow_result.get("status") != "success":
        return {
            "status": "failure",
            "error": "planner_failed"
        }

    # Step 3: Extract workflow
    workflow = workflow_result.get("workflow", {})

    # Step 3.1: Extract explicit constraints from user input
    constraints = extract_constraints_llm(user_input)
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
            step["input"] = user_input

    # Step 4: Execute via runtime (preserves all existing logic)
    result = run_workflow(workflow)

    # Step 5: Final output synthesis (LLM-based)
    workflow_steps = workflow.get("steps", [])
    original_user_input = user_input

    # STEP 1 — EXTRACT STEP RESULTS
    results_summary = []
    for i, step in enumerate(workflow_steps):
        exec_res = step.get("execution_result") or {}

        if exec_res.get("status") == "success":
            results_summary.append(f"Step {i+1}: result = {exec_res.get('result')}")
        elif step.get("output"):
            results_summary.append(f"Step {i+1}: {step.get('output')}")

    # STEP — BUILD VALID RESULTS (MOVED HERE)
    valid_results = []

    for step in workflow_steps:
        exec_res = step.get("execution_result") or {}
        if exec_res.get("status") == "success":
            valid_results.append(str(exec_res.get("result")))
    print("\n# VALID RESULTS\n", valid_results)

    print("\n# RESULTS SUMMARY\n", results_summary)

    # Get last step info for synth inputs
    last_step = workflow_steps[-1] if workflow_steps else {}
    print("\n# SYNTH INPUTS")
    print("valid_results:", valid_results)
    print("last_step_output:", last_step.get("output"))
    print("constraints:", workflow.get("constraints"))
    print("execution_result:", last_step.get("execution_result"))

    # STEP 2 — BUILD PROMPT
    prompt = f"""
You are a final answer synthesizer.

Your job:
Produce the best possible final response to the user's request using the provided step results.

---

CRITICAL RULES:

1. SOURCE OF TRUTH
- You MUST use ONLY the provided step results.
- You MUST NOT invent new information.

2. NO INFORMATION LOSS
- You MUST NOT remove or drop important content.
- If a step result already contains a complete answer, you MUST preserve it.
- DO NOT summarize unless explicitly requested.

3. COMPLETENESS
- If the step result fully satisfies the request, return it as-is or lightly refined.
- DO NOT shorten a complete answer.

4. CONSTRAINT COMPLIANCE
- You MUST ensure the final answer satisfies ALL constraints.

5. CONFLICT HANDLING
- If multiple results conflict:
    - choose the one that best satisfies the request AND constraints
    - DO NOT merge conflicting facts incorrectly

6. NATURAL OUTPUT
- Output should be clear and natural.
- Light formatting is allowed.
- DO NOT add explanations unless requested.

---

User request:
{original_user_input}

Constraints:
{workflow.get("constraints")}

Step results:
{chr(10).join(results_summary)}

---

Return ONLY the final answer.
"""

    # STEP 3 — CALL LLM
    provider_result = get_llm("ollama_llm")

    llm_output = None
    if provider_result.get("status") == "success":
        provider = provider_result["provider"]
        llm_result = execute_llm(provider, prompt)

        if llm_result.get("status") == "success":
            llm_output = llm_result.get("result", "").strip()
    print("\n# SYNTH RAW OUTPUT\n", llm_output)

    # STEP 4 — STRICT VALIDATION
    llm_output_clean = llm_output.strip() if llm_output else ""
    print("\n# LLM OUTPUT CLEAN\n", llm_output_clean)

    final_output = None

    # === VALIDATOR ENFORCEMENT ===
    last_step = workflow_steps[-1] if workflow_steps else {}

    validator_decision = (
        last_step.get("decision")
        or last_step.get("validation_result")
        or {}
    )

    exec_res = last_step.get("execution_result") or {}

    if exec_res.get("status") == "success":
        decision_type = validator_decision.get("decision") if isinstance(validator_decision, dict) else None

        if decision_type != "accept":
            print("[VALIDATOR ENFORCEMENT] overriding with execution_result")
            final_output = exec_res.get("result")

    if final_output is None:
        if llm_output_clean and llm_output_clean in valid_results:
            final_output = llm_output_clean

        elif valid_results:
            final_output = valid_results[-1]

        elif llm_output_clean:
            final_output = llm_output_clean

        else:
            final_output = last_step.get("output")

    fallback_used = llm_output_clean not in valid_results if llm_output_clean else True
    print("\n# FINAL OUTPUT TRACE")
    print("llm_output_clean:", llm_output_clean)
    print("valid_results:", valid_results)
    print("fallback_used:", fallback_used)
    print("final_output:", final_output)

    print("\n# FINAL CONSTRAINTS\n", workflow.get("constraints"))

    # === EXTRACT TRUE EXECUTION RESULT ===
    # Iterate steps in reverse order to find most recent execution_result
    true_result = None
    for step in reversed(workflow_steps):
        exec_res = step.get("execution_result")
        if exec_res is not None:
            true_result = exec_res.get("result")
            break

    # Step 6: Return structured result
    return {
        "status": workflow.get("status", "completed"),
        "steps": workflow.get("steps", []),
        "context": workflow.get("context", {}),
        "output": final_output,
        "result": true_result
    }
