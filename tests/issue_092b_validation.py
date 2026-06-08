"""
ISSUE-092B Controlled Failure Validation
Simulates planner returning planner_empty_steps and validates downstream behavior.
"""
import sys
sys.path.insert(0, r"e:\MutesHand")

import threading
from unittest.mock import patch

# Patch plan_workflow before import to avoid side effects
def mock_plan_workflow(*args, **kwargs):
    return {"status": "failure", "reason": "planner_empty_steps"}

with patch("system.orchestrator.orchestrator_runtime.plan_workflow", mock_plan_workflow):
    from system.orchestrator.orchestrator_runtime import execute_from_input

    stream_registry = {}
    stream_lock = threading.Lock()
    bg_id = "test_bg_092b"
    pre_wf_id = "test_wf_092b"

    # Pre-register stream entry as /execute/stream does in production
    stream_registry[bg_id] = {
        "bg_id": bg_id,
        "workflow_id": pre_wf_id,
        "status": "QUEUED",
        "result": None,
        "error": None,
    }

    result = execute_from_input(
        user_input="Hi I am Bryan",
        bg_id=bg_id,
        stream_registry=stream_registry,
        stream_registry_lock=stream_lock,
        pre_generated_workflow_id=pre_wf_id,
    )

    print("=== ISSUE-092B CONTROLLED VALIDATION RESULT ===")
    print(f"result status: {result.get('status')}")
    print(f"result reason: {result.get('reason')}")
    print(f"result failure_reason: {result.get('failure_reason')}")
    print(f"result steps: {result.get('steps')}")
    print(f"result retry_target_step_id: {result.get('retry_target_step_id')}")
    print(f"result failed_step_id: {result.get('failed_step_id')}")
    print(f"result retry_eligible: {result.get('retry_eligible')}")
    print(f"result failed_recoverable: {result.get('failed_recoverable')}")
    print(f"result retry_disabled_reason: {result.get('retry_disabled_reason')}")
    print(f"result failure_display_message: {result.get('failure_display_message')}")

    # Validate assertions
    errors = []
    if result.get("status") != "FAILED":
        errors.append(f"Expected status FAILED, got {result.get('status')}")
    if result.get("reason") != "planner_empty_steps":
        errors.append(f"Expected reason planner_empty_steps, got {result.get('reason')}")
    if result.get("failure_reason") != "planner_empty_steps":
        errors.append(f"Expected failure_reason planner_empty_steps, got {result.get('failure_reason')}")
    if result.get("steps") != []:
        errors.append(f"Expected steps [], got {result.get('steps')}")
    if result.get("retry_target_step_id") is not None:
        errors.append(f"Expected retry_target_step_id null, got {result.get('retry_target_step_id')}")
    if result.get("failed_step_id") is not None:
        errors.append(f"Expected failed_step_id null, got {result.get('failed_step_id')}")
    if result.get("retry_eligible") is not False:
        errors.append(f"Expected retry_eligible False, got {result.get('retry_eligible')}")
    if result.get("failed_recoverable") is not False:
        errors.append(f"Expected failed_recoverable False, got {result.get('failed_recoverable')}")
    if not result.get("failure_display_message"):
        errors.append(f"Expected failure_display_message populated, got {result.get('failure_display_message')}")

    # Stream registry assertions
    reg_entry = stream_registry.get(bg_id, {})
    print(f"\nstream_registry status: {reg_entry.get('status')}")
    print(f"stream_registry error: {reg_entry.get('error')}")
    print(f"stream_registry result status: {reg_entry.get('result', {}).get('status')}")
    print(f"stream_registry result reason: {reg_entry.get('result', {}).get('reason')}")

    if reg_entry.get("status") != "FAILED":
        errors.append(f"Expected registry status FAILED, got {reg_entry.get('status')}")
    if reg_entry.get("error") != "planner_empty_steps":
        errors.append(f"Expected registry error planner_empty_steps, got {reg_entry.get('error')}")
    reg_result = reg_entry.get("result", {})
    if reg_result.get("status") != "FAILED":
        errors.append(f"Expected registry result status FAILED, got {reg_result.get('status')}")
    if reg_result.get("reason") != "planner_empty_steps":
        errors.append(f"Expected registry result reason planner_empty_steps, got {reg_result.get('reason')}")

    if errors:
        print("\nFAILURES:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\nALL ASSERTIONS PASSED")
        sys.exit(0)
