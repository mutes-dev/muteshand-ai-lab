from system.orchestrator.orchestrator_runtime import run_workflow


def run_scheduler(workflows: list) -> list:
    results = []

    for workflow in workflows:
        result = run_workflow(workflow)
        results.append({
            "workflow_id": workflow.get("id"),
            "result": result
        })

    return results
