import sys

from system.orchestrator.orchestrator_runtime import run_workflow, execute_from_input
from system.orchestrator.bootstrap import initialize_system
from system.tool_index.metadata_generator import run as run_metadata_generator
from system.orchestrator.user_control import (
    pause,
    resume,
    set_override,
    get_override,
    is_paused
)


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


def _print_result(result: dict, show_full_trace: bool = False):
    workflow_result = result

    # Preserve existing debug output (not removed per safety rules)
    print("DEBUG_CLI_OUTPUT:", workflow_result)

    # Extract result value safely
    result_value = workflow_result.get("result")
    if isinstance(result_value, dict):
        result_value = result_value.get("result", result_value)

    # Clean output (PRIMARY)
    print("\n=== RESULT ===")
    print(result_value if result_value is not None else workflow_result.get("status"))

    # === CLASSIFICATION VISIBILITY (Phase 5.1) ===
    # Display classification if available (read-only, observational only)
    if isinstance(workflow_result, dict):
        classification = workflow_result.get("classification")
        if classification:
            print("\n=== CLASSIFICATION ===")
            print(classification)

    # Trace-based step rendering (SAFE FALLBACK)
    trace = workflow_result.get("trace")
    if trace and isinstance(trace, dict):
        steps = trace.get("steps", [])
        if isinstance(steps, list) and steps:
            print("\n=== STEPS ===")
            step_num = 1
            for step in steps:
                exec_res = step.get("execution_result", {}) if isinstance(step, dict) else {}
                if isinstance(exec_res, dict) and exec_res.get("status") == "success":
                    output = exec_res.get("result")
                    purpose = step.get("purpose", "Unknown") if isinstance(step, dict) else "Unknown"
                    print(f"{step_num}. {purpose} → {output}")
                    step_num += 1

        # Full trace dump (OPTIONAL --trace flag)
        if show_full_trace:
            print("\n=== FULL TRACE ===")
            print(trace)


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

        # === CLI CONTROL COMMANDS (Phase 5.1) ===
        command = user_input.strip().lower()

        if command == "pause":
            pause()
            print("⏸ System paused")
            continue

        elif command == "resume":
            resume()
            print("▶️ System resumed")
            continue

        elif command == "override on":
            set_override(True)
            print("🚀 Override enabled")
            continue

        elif command == "override off":
            set_override(False)
            print("🛑 Override disabled")
            continue

        elif command == "status":
            print({
                "paused": is_paused(),
                "override": get_override()
            })
            continue

        try:
            result = execute_from_input(user_input)
            _print_result(result, show_full_trace=False)
            print()

        except Exception as e:
            print(f"[ERROR] {e}\n")


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py \"your prompt here\" [--trace]")
        return

    # Check for --trace flag (safe extraction)
    show_full_trace = "--trace" in sys.argv
    cli_args = [a for a in sys.argv[1:] if a != "--trace"]

    if not cli_args:
        print("Usage: python main.py \"your prompt here\" [--trace]")
        return

    user_input = cli_args[0]
    # DEBUG_TEMP_START
    print("[DEBUG_MAIN_INPUT]:", user_input)
    # DEBUG_TEMP_END

    initialize_system()
    ensure_metadata_ready()

    result = execute_from_input(user_input)
    _print_result(result, show_full_trace=show_full_trace)


if __name__ == "__main__":
    run_cli()
