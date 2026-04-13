import json
import shlex

from system.entry.system_entry import system_entry
from system.orchestrator.workflow_validator import validate_workflow
from system.orchestrator.agent_registry import get_agent
from system.orchestrator.agent_executor import execute_agent
from system.orchestrator.agent_output_interpreter import interpret_agent_output
from system.orchestrator.decision_hook import evaluate_interpretation
from system.orchestrator.persistence import save_workflow
from system.memory.execution_memory import apply_memory, learn_from_attempts
from system.orchestrator.intent_validator import evaluate_intent

_TOOL_INDEX_PATH = "system/tool_index/tools.json"
with open(_TOOL_INDEX_PATH, "r", encoding="utf-8") as _f:
    _tool_index = json.load(_f)


def extract_numbers(text: str):
    return [int(x) for x in text.split() if x.isdigit()]


def run_workflow(workflow: dict, return_trace: bool = False):
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

    while workflow["status"] not in ["COMPLETED", "BLOCKED"]:
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

        agent_lookup = get_agent(step["agent"])

        if step.get("attempt_history"):
            last_attempt = step["attempt_history"][-1]
            source_input = last_attempt.get("input", step["input"])
            current_input = apply_memory(source_input)
        else:
            current_input = apply_memory(step["input"])
        inner_retries = 0
        inner_max = step["max_retries"]

        if "attempt_history" not in step:
            step["attempt_history"] = []

        while True:
            if agent_lookup["status"] == "success":
                agent = agent_lookup["agent"]
                result = execute_agent(agent, current_input)
            else:
                result = system_entry(current_input)

            _result_val = result.get("result")
            executed_input = (
                (_result_val.get("executed_input") if isinstance(_result_val, dict) else None)
                or result.get("executed_input")
            )

            if result["status"] == "success" and executed_input:
                try:
                    ei_parts = shlex.split(executed_input)
                except ValueError:
                    ei_parts = executed_input.split()
                ei_tool = ei_parts[0] if ei_parts else None
                ei_args = ei_parts[1:] if len(ei_parts) > 1 else []
                tool_def = _tool_index.get(ei_tool) if ei_tool else None
                if tool_def is not None:
                    expected_inputs = tool_def.get("inputs", {})
                    if len(ei_args) != len(expected_inputs):
                        step["status"] = "FAILED"
                        step["error"] = "invalid_argument_count"
                        step["retries"] += 1
                        step["attempt_history"].append({
                            "input": executed_input,
                            "status": "failure",
                            "reason": "invalid_argument_count"
                        })
                        inner_retries += 1
                        if inner_retries > inner_max:
                            break
                        failure_reason = "invalid_argument_count"
                        current_input = (
                            "Previous attempt failed.\n\n"
                            f"Original input:\n{step['input']}\n\n"
                            f"Previous attempt:\n{current_input}\n\n"
                            f"Failure reason:\n{failure_reason}\n\n"
                            "Fix the input and retry using USE_TOOL format.\n\n"
                            "STRICT RULES:\n"
                            "- DO NOT change any numbers\n"
                            "- DO NOT change any values\n"
                            "- ONLY fix formatting or syntax errors\n"
                            "- The corrected input must represent the SAME request"
                        )
                        continue
                    type_error = False
                    for arg, expected_type in zip(ei_args, expected_inputs.values()):
                        if expected_type == "number":
                            cleaned = arg.lstrip("-")
                            if not cleaned.isdigit():
                                type_error = True
                                break
                    if type_error:
                        step["status"] = "FAILED"
                        step["error"] = "invalid_argument_type"
                        step["retries"] += 1
                        step["attempt_history"].append({
                            "input": executed_input,
                            "status": "failure",
                            "reason": "invalid_argument_type"
                        })
                        inner_retries += 1
                        if inner_retries > inner_max:
                            break
                        failure_reason = "invalid_argument_type"
                        current_input = (
                            "Previous attempt failed.\n\n"
                            f"Original input:\n{step['input']}\n\n"
                            f"Previous attempt:\n{current_input}\n\n"
                            f"Failure reason:\n{failure_reason}\n\n"
                            "Fix the input and retry using USE_TOOL format.\n\n"
                            "STRICT RULES:\n"
                            "- DO NOT change any numbers\n"
                            "- DO NOT change any values\n"
                            "- ONLY fix formatting or syntax errors\n"
                            "- The corrected input must represent the SAME request"
                        )
                        continue


            if result["status"] == "success":
                original_numbers = extract_numbers(step["input"])
                executed_numbers = extract_numbers(executed_input or "")

                if original_numbers and executed_numbers:
                    _ = (original_numbers != executed_numbers)

                agent_output = result.get("result") or {}

                if not agent_output.get("executed_input"):
                    step["status"] = "COMPLETE"
                    step["output"] = agent_output
                    break

                _intent_tool = (agent_output.get("executed_input") or "").split()[0] if isinstance(agent_output, dict) else ""
                _intent_output = agent_output.get("output", "") if isinstance(agent_output, dict) else ""
                execution_result = agent_output.get("execution_result")

                _intent_decision = evaluate_intent(
                    step["input"],
                    _intent_tool,
                    execution_result,
                    _intent_output
                )

                if _intent_decision["decision"] == "retry":
                    step["status"] = "FAILED"
                    step["error"] = _intent_decision["reason"]
                    step["retries"] += 1
                    step["attempt_history"].append({
                        "input": executed_input,
                        "status": "failure",
                        "reason": _intent_decision["reason"]
                    })
                    inner_retries += 1
                    if inner_retries > inner_max:
                        break
                    failure_reason = _intent_decision["reason"]
                    current_input = (
                        "Previous attempt failed.\n\n"
                        f"Original input:\n{step['input']}\n\n"
                        f"Previous attempt:\n{current_input}\n\n"
                        f"Failure reason:\n{failure_reason}\n\n"
                        "Fix the input and retry using USE_TOOL format.\n\n"
                        "STRICT RULES:\n"
                        "- DO NOT change any numbers\n"
                        "- DO NOT change any values\n"
                        "- ONLY fix formatting or syntax errors\n"
                        "- The corrected input must represent the SAME request"
                    )
                    continue

                step["attempt_history"].append({
                    "input": executed_input,
                    "status": "success"
                })
                learn_from_attempts(step["attempt_history"])
                break

            step["attempt_history"].append({
                "input": executed_input,
                "status": "failure",
                "reason": result.get("reason", "unknown_error")
            })

            inner_retries += 1

            if inner_retries > inner_max:
                break

            failure_reason = result.get("reason", "unknown_error")
            current_input = (
                "Previous attempt failed.\n\n"
                f"Original input:\n{step['input']}\n\n"
                f"Previous attempt:\n{current_input}\n\n"
                f"Failure reason:\n{failure_reason}\n\n"
                "Fix the input and retry using USE_TOOL format.\n\n"
                "STRICT RULES:\n"
                "- DO NOT change any numbers\n"
                "- DO NOT change any values\n"
                "- ONLY fix formatting or syntax errors\n"
                "- The corrected input must represent the SAME request"
            )

            trace.append({
                "step_id": step["id"],
                "event": "step_inner_retry",
                "status": "RUNNING",
                "retries": inner_retries,
                "reason": failure_reason
            })

        interpretation = interpret_agent_output(result)
        step["interpreted"] = interpretation

        decision = evaluate_interpretation(interpretation)
        step["decision"] = decision

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
                step["output"] = result["result"]
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
