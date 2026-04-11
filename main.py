import sys

from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator.bootstrap import initialize_system


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py \"your prompt here\"")
        return

    user_input = sys.argv[1]

    initialize_system()

    workflow = {
        "id": "cli_workflow",
        "name": "cli_execution",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "step_1",
                "name": "cli_step",
                "agent": "default_agent",
                "status": "PENDING",
                "retries": 0,
                "max_retries": 1,
                "input": user_input
            }
        ]
    }

    result = run_workflow(workflow, return_trace=True)

    if isinstance(result, dict) and "workflow" in result:
        workflow_result = result["workflow"]
    else:
        workflow_result = result

    print("\n=== FINAL RESULT ===")
    print(workflow_result.get("status"))

    steps = workflow_result.get("steps", [])

    for step in steps:
        print("\n--- STEP OUTPUT ---")
        print("Output:", step.get("output"))
        print("Decision:", step.get("decision"))

        if "action_required" in step:
            print("Action Required:", step.get("action_required"))


if __name__ == "__main__":
    main()
