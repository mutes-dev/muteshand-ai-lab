import sys

from system.orchestrator.orchestrator_runtime import run_workflow, execute_from_input
from system.orchestrator.bootstrap import initialize_system
from system.tool_index.metadata_generator import run as run_metadata_generator


def build_workflow(user_input: str) -> dict:
    return {
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


def _print_result(result: dict):
    workflow_result = result

    print("DEBUG_CLI_OUTPUT:", workflow_result)
    print("\n=== FINAL RESULT ===")
    print(workflow_result.get("status"))

    steps = workflow_result.get("steps", [])

    for step in steps:
        print("\n--- STEP OUTPUT ---")
        print("Output:", step.get("output"))
        print("Decision:", step.get("decision"))

        if "action_required" in step:
            print("Action Required:", step.get("action_required"))


def ensure_metadata_ready():
    import json

    with open("system/tool_index/tools.json", "r") as f:
        tools = json.load(f)

    missing = [
        name for name, data in tools.items()
        if not data.get("description")
    ]

    if missing:
        print(f"⚠️ Missing metadata for {len(missing)} tools — generating...")
        run_metadata_generator()
    else:
        print("✅ Metadata ready")


def run_cli():
    initialize_system()
    ensure_metadata_ready()
    print("AI Lab CLI (type 'exit' to quit)\n")

    while True:
        user_input = input("> ")
        # DEBUG_TEMP_START
        print("[DEBUG_MAIN_INPUT]:", user_input)
        # DEBUG_TEMP_END

        if user_input.lower() in ["exit", "quit"]:
            print("Goodbye.")
            break

        if not user_input.strip():
            continue

        try:
            result = execute_from_input(user_input)
            _print_result(result)
            print()

        except Exception as e:
            print(f"[ERROR] {e}\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py \"your prompt here\"")
        return

    user_input = sys.argv[1]
    # DEBUG_TEMP_START
    print("[DEBUG_MAIN_INPUT]:", user_input)
    # DEBUG_TEMP_END

    initialize_system()
    ensure_metadata_ready()

    result = execute_from_input(user_input)
    _print_result(result)


if __name__ == "__main__":
    run_cli()
