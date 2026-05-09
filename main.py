import sys
import uuid

from system.orchestrator.orchestrator_runtime import run_workflow, execute_from_input
from system.orchestrator.bootstrap import initialize_system
from system.tool_index.metadata_generator import run as run_metadata_generator
from system.orchestrator.workflow_control import (
    pause_workflow,
    resume_workflow,
)
from system.orchestrator.user_control import (
    set_override,
    get_override,
)
from system.runtime.background_manager import BackgroundManager


def _extract_tool_call(user_input: str) -> str:
    """Extract valid tool_call from user input."""
    if not user_input:
        return "finalize_output 'empty input'"
    # Use input directly as tool call if it looks like one (starts with tool name)
    parts = user_input.strip().split()
    if len(parts) >= 1:
        # Return as-is — system_entry will parse
        return user_input.strip()
    return f"finalize_output '{user_input}'"


def build_workflow(user_input: str) -> dict:
    tool_call = _extract_tool_call(user_input)
    return {
        "id": f"cli_workflow_{uuid.uuid4().hex[:8]}",
        "name": "cli_execution",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "name": "cli_step",
                "purpose": user_input,
                "tool_call": tool_call,
                "expected_outcome": "Execution completed",
                "risk": "LOW",
                "importance": "MEDIUM",
                "resource_targets": [],
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

    # Extract result value safely — prefer new execution_result field (flat), fallback to legacy nested result
    execution_result = workflow_result.get("execution_result")
    if isinstance(execution_result, dict):
        result_value = execution_result.get("result")
    else:
        result_value = None
    if result_value is None:
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


# === BACKGROUND MANAGER (Phase 2B) ===
# Global instance — persists across CLI loop iterations
_bg_manager = BackgroundManager()

# === WORKFLOW CONTEXT (Phase 4A.2) ===
# Tracks current workflow_id for workflow-scoped control
current_workflow_id = None


def run_cli():
    global current_workflow_id
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
            if current_workflow_id:
                result = pause_workflow(current_workflow_id)
                if result.get("status") == "success":
                    print(f"⏸ Workflow {current_workflow_id} paused")
                else:
                    print(f"⚠️ Pause failed: {result.get('reason')}")
            else:
                print("⚠️ No active workflow to pause")
            continue

        elif command == "resume":
            if current_workflow_id:
                result = resume_workflow(current_workflow_id)
                if result.get("status") == "success":
                    print(f"▶️ Workflow {current_workflow_id} resumed")
                else:
                    print(f"⚠️ Resume failed: {result.get('reason')}")
            else:
                print("⚠️ No active workflow to resume")
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
            # Status now workflow-scoped (Phase 4A.2)
            status_info = {
                "override": get_override()
            }
            if current_workflow_id:
                status_info["current_workflow"] = current_workflow_id
            else:
                status_info["current_workflow"] = None
            print(status_info)
            continue

        # === BACKGROUND EXECUTION COMMANDS (Phase 2B) ===

        elif command.startswith("bg "):
            # Start workflow in background: bg <user_input>
            bg_input = user_input.strip()[3:].strip()
            if not bg_input:
                print("[BG] Usage: bg <your prompt>")
                continue
            workflow_id = _bg_manager.start_workflow(execute_from_input, bg_input)
            print(f"[BG] Workflow started: {workflow_id}")
            print(f"[BG] Use 'status {workflow_id}' to check progress")
            continue

        elif command.startswith("status "):
            # Query specific workflow status: status <workflow_id>
            parts = user_input.strip().split(maxsplit=1)
            if len(parts) < 2:
                print("[BG] Usage: status <workflow_id>")
                continue
            wf_id = parts[1].strip()
            wf_status = _bg_manager.get_status(wf_id)
            if wf_status is None:
                print(f"[BG] Workflow {wf_id} not found")
            else:
                print(f"[BG] Workflow: {wf_status['workflow_id']}")
                print(f"  Status:    {wf_status['status']}")
                print(f"  Started:   {wf_status['started_at']}")
                print(f"  Completed: {wf_status['completed_at'] or 'running'}")
                if wf_status['error']:
                    print(f"  Error:     {wf_status['error']}")
                if wf_status['result'] is not None:
                    print(f"  Result:    {wf_status['result']}")
            continue

        elif command == "workflows":
            # List all tracked workflows
            wf_list = _bg_manager.list_workflows()
            if not wf_list:
                print("[BG] No workflows tracked")
            else:
                print(f"[BG] {len(wf_list)} workflow(s):")
                for wf in wf_list:
                    print(f"  {wf['workflow_id'][:8]}... {wf['status']} (started: {wf['started_at']})")
            continue

        elif command.startswith("wait "):
            # Block until workflow completes: wait <workflow_id>
            parts = user_input.strip().split(maxsplit=1)
            if len(parts) < 2:
                print("[BG] Usage: wait <workflow_id>")
                continue
            wf_id = parts[1].strip()
            print(f"[BG] Waiting for {wf_id}...")
            wf_status = _bg_manager.wait_for(wf_id, timeout=300)
            if wf_status is None:
                print(f"[BG] Workflow {wf_id} not found")
            else:
                print(f"[BG] Workflow {wf_status['status']}")
                if wf_status['result'] is not None:
                    _print_result(wf_status['result'], show_full_trace=False)
            continue

        # === DEFAULT: SYNCHRONOUS EXECUTION (unchanged) ===
        try:
            result = execute_from_input(user_input)
            # Capture workflow_id for control actions (Phase 4A.2)
            current_workflow_id = result.get("workflow_id")
            if current_workflow_id:
                print(f"[CLI] Workflow ID: {current_workflow_id}")
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
    # Capture workflow_id for control actions (Phase 4A.2)
    current_workflow_id = result.get("workflow_id")
    if current_workflow_id:
        print(f"[CLI] Workflow ID: {current_workflow_id}")
    _print_result(result, show_full_trace=show_full_trace)


if __name__ == "__main__":
    run_cli()
