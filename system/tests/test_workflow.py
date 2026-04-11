from system.orchestrator.agent_registry import register_agent
from system.orchestrator.orchestrator_runtime import run_workflow


def main():
    agent = {
        "name": "test_agent",
        "role": "Story writer",
        "scope": ["creative writing", "storytelling"]
    }

    registration_result = register_agent(agent)
    print("Agent Registration:", registration_result)

    workflow = {
        "id": "wf_001",
        "name": "test_workflow",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "step_1",
                "name": "test_step",
                "agent": "test_agent",
                "status": "PENDING",
                "retries": 0,
                "max_retries": 1,
                "input": None
            }
        ]
    }

    result = run_workflow(workflow, return_trace=True)
    print("Workflow Result:", result)


if __name__ == "__main__":
    main()
