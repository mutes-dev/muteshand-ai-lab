from system.entry.system_entry import system_entry
from system.orchestrator.workflow_validator import validate_workflow
from system.orchestrator.agent_registry import get_agent
from system.orchestrator.agent_executor import execute_agent
from system.orchestrator.agent_output_interpreter import interpret_agent_output
from system.orchestrator.decision_hook import evaluate_interpretation
from system.orchestrator.persistence import save_workflow


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

        if agent_lookup["status"] == "success":
            agent = agent_lookup["agent"]
            result = execute_agent(agent, step["input"])
        else:
            result = system_entry(step["input"])

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

            if step["retries"] >= step["max_retries"]:
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
