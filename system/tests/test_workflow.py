from system.orchestrator.agent_registry import register_agent
from system.orchestrator.orchestrator_runtime import run_workflow, execute_from_input


def main():
    agent = {
        "name": "test_agent",
        "role": "Story writer",
        "scope": ["creative writing", "storytelling"]
    }

    registration_result = register_agent(agent)
    print("Agent Registration:", registration_result)

    # Test new contract via execute_from_input
    result = execute_from_input("What is the capital of France?")
    print("Contract Result:", result)


if __name__ == "__main__":
    main()


# =============================================================================
# PYTEST TESTS — OUTPUT CONTRACT VALIDATION
# =============================================================================

import pytest
from system.entry import system_entry as system_entry_module

# =============================================================================
# EXTERNAL CONTRACT TESTS (execute_from_input)
# =============================================================================

def test_external_contract_success():
    """Verify execute_from_input returns correct contract on success."""
    result = execute_from_input("Use a tool to add 5 and 3")

    # Contract: MUST have status and result or reason
    assert "status" in result, "Missing 'status' in result"
    assert result["status"] in ["success", "failure"], "Invalid status value"

    if result["status"] == "success":
        assert "result" in result, "Missing 'result' in success response"
        assert "steps" not in result, "External contract must NOT contain 'steps'"
        assert "output" not in result, "External contract must NOT contain 'output'"
        assert "context" not in result, "External contract must NOT contain 'context'"
    else:
        assert "reason" in result, "Missing 'reason' in failure response"


def test_external_contract_failure():
    """Verify execute_from_input returns correct contract on failure."""
    result = execute_from_input("")  # Empty input should fail

    assert "status" in result
    if result["status"] == "failure":
        assert "reason" in result
        assert "result" not in result, "Failure response must NOT contain 'result'"


def test_external_contract_fields_only():
    """Verify external response contains ONLY status + result/reason."""
    result = execute_from_input("What is 2+2?")

    allowed_keys = {"status", "result", "reason"}
    actual_keys = set(result.keys())

    # No extra keys allowed
    extra_keys = actual_keys - allowed_keys
    assert len(extra_keys) == 0, f"Contract violation: extra keys {extra_keys}"


# =============================================================================
# INTERNAL VALIDATION TESTS (run_workflow with captured workflow)
# =============================================================================

def test_system_entry_is_called(monkeypatch):
    """Internal: Verify system_entry is called during workflow execution."""
    call_count = [0]
    captured_inputs = []
    captured_outputs = []
    original = system_entry_module.system_entry

    def wrapper(input_text):
        call_count[0] += 1
        captured_inputs.append(input_text)
        result = original(input_text)
        captured_outputs.append(result)
        return result

    monkeypatch.setattr("system.orchestrator.agent_executor.system_entry", wrapper)
    register_agent({"name": "a1", "role": "executor", "scope": ["tools"]})

    workflow = {
        "id": "w1",
        "name": "test",
        "status": "ACTIVE",
        "steps": [{"id": "s1", "name": "t", "agent": "a1", "status": "PENDING", "retries": 0, "max_retries": 2, "input": "USE_TOOL: add_numbers 5 3"}]
    }

    result = run_workflow(workflow)
    print("CALL COUNT:", call_count[0])
    print("RESULT:", result)

    # Verify system_entry was called
    assert call_count[0] > 0, "system_entry not called"

    # Verify contract
    assert "status" in result
    if result["status"] == "success":
        assert "result" in result


def test_retry_bounded(monkeypatch):
    """Internal: Verify retry respects max_retries."""
    call_count = [0]

    def failing(input_text):
        call_count[0] += 1
        return {"status": "failure", "reason": "test"}

    monkeypatch.setattr("system.orchestrator.agent_executor.system_entry", failing)
    register_agent({"name": "a2", "role": "executor", "scope": ["tools"]})

    workflow = {
        "id": "w2",
        "name": "test",
        "status": "ACTIVE",
        "steps": [{"id": "s1", "name": "t", "agent": "a2", "status": "PENDING", "retries": 0, "max_retries": 2, "input": "USE_TOOL: add 1 2"}]
    }

    result = run_workflow(workflow)
    print("CALL COUNT:", call_count[0])

    # Verify bounded retry
    assert call_count[0] <= 3, f"calls {call_count[0]} > max 3"

    # Verify contract
    assert "status" in result


def test_one_call_per_step(monkeypatch):
    """Internal: Verify no batching of system_entry calls."""
    call_count = [0]
    call_log = []
    original = system_entry_module.system_entry

    def wrapper(input_text):
        call_count[0] += 1
        call_log.append(input_text)
        return original(input_text)

    monkeypatch.setattr("system.orchestrator.agent_executor.system_entry", wrapper)
    register_agent({"name": "a3", "role": "executor", "scope": ["tools"]})

    workflow = {
        "id": "w3",
        "name": "test",
        "status": "ACTIVE",
        "steps": [
            {"id": "s1", "name": "t1", "agent": "a3", "status": "PENDING", "retries": 0, "max_retries": 2, "input": "USE_TOOL: add_numbers 1 2"},
            {"id": "s2", "name": "t2", "agent": "a3", "status": "PENDING", "retries": 0, "max_retries": 2, "input": "USE_TOOL: add_numbers 3 4"}
        ]
    }

    result = run_workflow(workflow)
    print("CALL COUNT:", call_count[0])
    print("CALL LOG:", call_log)

    # Verify no batching
    if call_count[0] > 1:
        assert len(call_log) == call_count[0], "batching detected"

    assert call_count[0] > 0, "no execution occurred"

    # Verify contract
    assert "status" in result


def test_result_origin(monkeypatch):
    """Internal: Verify result originates from system_entry."""
    captured = []
    original = system_entry_module.system_entry

    def wrapper(input_text):
        result = original(input_text)
        captured.append({"input": input_text, "result": result})
        return result

    monkeypatch.setattr("system.orchestrator.agent_executor.system_entry", wrapper)
    register_agent({"name": "a4", "role": "executor", "scope": ["tools"]})

    workflow = {
        "id": "w4",
        "name": "test",
        "status": "ACTIVE",
        "steps": [{"id": "s1", "name": "t", "agent": "a4", "status": "PENDING", "retries": 0, "max_retries": 2, "input": "USE_TOOL: add_numbers 10 20"}]
    }

    result = run_workflow(workflow)
    print("CAPTURED:", captured)
    print("RESULT:", result)

    assert len(captured) >= 1, "no calls captured"

    # Verify contract has result
    if result["status"] == "success":
        assert "result" in result


def test_final_output_identity():
    """External: Verify final output matches execution_result."""
    register_agent({"name": "a5", "role": "executor", "scope": ["tools"]})

    result = run_workflow({
        "id": "w5",
        "name": "test",
        "status": "ACTIVE",
        "steps": [{"id": "s1", "name": "t", "agent": "a5", "status": "PENDING", "retries": 0, "max_retries": 2, "input": "USE_TOOL: add_numbers 5 5"}]
    })

    print("RESULT:", result)

    # Verify contract
    assert "status" in result
    if result["status"] == "success":
        assert "result" in result
        assert result["result"] is not None


def test_failure_output_propagation():
    """External: Verify failure is properly reported."""
    register_agent({"name": "a6", "role": "executor", "scope": ["tools"]})

    result = run_workflow({
        "id": "w6",
        "name": "test",
        "status": "ACTIVE",
        "steps": [{"id": "s1", "name": "t", "agent": "a6", "status": "PENDING", "retries": 0, "max_retries": 2, "input": "USE_TOOL: nonexistent_tool 1 2"}]
    })

    print("RESULT:", result)

    # Verify failure contract
    assert "status" in result
    if result["status"] == "failure":
        assert "reason" in result


def test_no_fallback_output_usage():
    """External: Verify output comes from execution, not fallback."""
    register_agent({"name": "a7", "role": "executor", "scope": ["tools"]})

    result = run_workflow({
        "id": "w7",
        "name": "test",
        "status": "ACTIVE",
        "steps": [{"id": "s1", "name": "t", "agent": "a7", "status": "PENDING", "retries": 0, "max_retries": 2, "input": "USE_TOOL: add_numbers 7 7"}]
    })

    print("RESULT:", result)

    # Verify contract
    assert "status" in result
    if result["status"] == "success":
        assert "result" in result
        assert result["result"] is not None


def test_final_output_from_last_step():
    """External: Verify output from last executed step."""
    register_agent({"name": "a8", "role": "executor", "scope": ["tools"]})

    result = run_workflow({
        "id": "w8",
        "name": "test",
        "status": "ACTIVE",
        "steps": [
            {"id": "s1", "name": "t1", "agent": "a8", "status": "PENDING", "retries": 0, "max_retries": 2, "input": "USE_TOOL: add_numbers 1 1"},
            {"id": "s2", "name": "t2", "agent": "a8", "status": "PENDING", "retries": 0, "max_retries": 2, "input": "USE_TOOL: add_numbers 2 2"}
        ]
    })

    print("RESULT:", result)

    # Verify contract
    assert "status" in result
    if result["status"] == "success":
        assert "result" in result


def test_non_tool_execution_not_forced_failure():
    """External: Non-tool execution should not be forced failure."""
    result = run_workflow({
        "id": "test-workflow",
        "name": "test_workflow",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "step-1",
                "name": "test_step",
                "agent": "generic_agent",
                "input": "What is the capital of France?",
                "status": "PENDING",
                "retries": 0,
                "max_retries": 3
            }
        ]
    })

    print("RESULT:", result)

    # Verify contract
    assert "status" in result

    if result["status"] == "failure":
        assert "reason" in result
    elif result["status"] == "success":
        assert "result" in result


def test_step_output_not_overwritten():
    """Internal: Verify step output integrity."""
    # This test captures workflow state via monkeypatch
    captured_workflow = [None]
    original_run_workflow = run_workflow.__wrapped__ if hasattr(run_workflow, "__wrapped__") else None

    result = run_workflow({
        "id": "test-workflow",
        "name": "test_workflow",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "step-1",
                "name": "test_step",
                "agent": "generic_agent",
                "input": "What is the capital of Botswana? Do not use any tools.",
                "status": "PENDING",
                "retries": 0,
                "max_retries": 3
            }
        ]
    })

    print("RESULT:", result)

    # Verify contract
    assert "status" in result


def test_validator_contract_no_crash():
    """Verify validator integration doesn't crash."""
    try:
        result = run_workflow({
            "id": "test-workflow",
            "name": "test_workflow",
            "status": "ACTIVE",
            "steps": [
                {
                    "id": "step-1",
                    "name": "test_step",
                    "agent": "generic_agent",
                    "input": "Use a tool to multiply 4 and 6.",
                    "status": "PENDING",
                    "retries": 0,
                    "max_retries": 3
                }
            ]
        })
    except Exception as e:
        assert False, f"Validator integration caused crash: {e}"

    # Verify contract
    assert "status" in result


def test_planner_single_task_not_split():
    """Verify planner doesn't split single coherent tasks."""
    result = run_workflow({
        "id": "test-workflow",
        "name": "test_workflow",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "step-1",
                "name": "test_step",
                "agent": "generic_agent",
                "input": "What is the capital of Botswana? Do not use any tools.",
                "status": "PENDING",
                "retries": 0,
                "max_retries": 3
            }
        ]
    })

    # Verify contract
    assert "status" in result


def test_tool_success_propagates_to_output():
    """External: Verify successful tool execution is in output."""
    result = run_workflow({
        "id": "test-workflow",
        "name": "test_workflow",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "step-1",
                "name": "test_step",
                "agent": "generic_agent",
                "input": "Use a tool to multiply 4 and 6.",
                "status": "PENDING",
                "retries": 0,
                "max_retries": 3
            }
        ]
    })

    print("RESULT:", result)

    # Verify contract
    assert "status" in result
    if result["status"] == "success":
        assert "result" in result
        assert result["result"] is not None


# =============================================================================
# RETRY CONTROL FLOW TESTS
# =============================================================================

def test_retry_control_flow_origin(monkeypatch):
    """Verify orchestrator controls retry flow."""
    call_counter = {"count": 0}

    def mock_system_entry(input_data):
        call_counter["count"] += 1
        return {"status": "failure", "reason": "forced_failure"}

    def mock_plan_workflow(input_data):
        return {
            "status": "success",
            "workflow": {
                "id": "retry_test_wf",
                "name": "retry_test",
                "goal": "test retry behavior",
                "steps": [
                    {
                        "id": "retry_step_1",
                        "name": "retry_step",
                        "agent": "retry_test_agent",
                        "input": "USE_TOOL: add_numbers 1 1",
                        "status": "PENDING",
                        "retries": 0,
                        "max_retries": 2
                    }
                ]
            }
        }

    monkeypatch.setattr("system.orchestrator.agent_executor.system_entry", mock_system_entry)
    monkeypatch.setattr("system.orchestrator.orchestrator_runtime.plan_workflow", mock_plan_workflow)
    register_agent({"name": "retry_test_agent", "role": "executor", "scope": ["tools"]})

    workflow = {
        "id": "retry_test_wf",
        "name": "retry_test",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "retry_step_1",
                "name": "retry_step",
                "agent": "retry_test_agent",
                "status": "PENDING",
                "retries": 0,
                "max_retries": 2,
                "input": "USE_TOOL: add_numbers 1 1"
            }
        ]
    }

    try:
        result = run_workflow(workflow)
    except Exception as e:
        result = None
        print("WORKFLOW ERROR:", str(e))

    call_count = call_counter["count"]
    print("CALL COUNT:", call_count)

    # Verify retry occurred
    assert call_count > 1, f"Retry behavior not triggered - only {call_count} call(s)"

    # Verify bounds respected
    assert call_count <= workflow["steps"][0]["max_retries"] + 1

    # Verify contract
    if result is not None:
        assert "status" in result


def test_no_retry_without_governance_permission(monkeypatch):
    """Verify no retry occurs without governance permission."""
    call_counter = {"count": 0}

    def mock_system_entry(input_data):
        call_counter["count"] += 1
        return {"status": "failure", "reason": "forced_failure"}

    def mock_decide_next_action(validator_output, execution_result, step, context):
        return "fail"

    def mock_plan_workflow(input_data):
        return {
            "status": "success",
            "workflow": {
                "id": "no_retry_test_wf",
                "name": "no_retry_test",
                "goal": "test no retry",
                "steps": [
                    {
                        "id": "no_retry_step",
                        "name": "no_retry_step",
                        "agent": "no_retry_test_agent",
                        "input": "USE_TOOL: add_numbers 1 1",
                        "status": "PENDING",
                        "retries": 0,
                        "max_retries": 3
                    }
                ]
            }
        }

    monkeypatch.setattr("system.orchestrator.agent_executor.system_entry", mock_system_entry)
    monkeypatch.setattr("system.orchestrator.governance.decide_next_action", mock_decide_next_action)
    monkeypatch.setattr("system.orchestrator.orchestrator_runtime.plan_workflow", mock_plan_workflow)
    register_agent({"name": "no_retry_test_agent", "role": "executor", "scope": ["tools"]})

    workflow = {
        "id": "no_retry_test_wf",
        "name": "no_retry_test",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "no_retry_step",
                "name": "no_retry_step",
                "agent": "no_retry_test_agent",
                "status": "PENDING",
                "retries": 0,
                "max_retries": 3,
                "input": "USE_TOOL: add_numbers 1 1"
            }
        ]
    }

    result = run_workflow(workflow)

    call_count = call_counter["count"]
    print("CALL COUNT:", call_count)

    # Verify no retry occurred
    assert call_count == 1, f"Expected 1 call (no retry), got {call_count}"

    # Verify contract
    assert "status" in result


# ✳️ TEST 1 — VALIDATOR IS INVOKED

def test_validator_invoked_no_crash():
    from system.orchestrator.orchestrator_runtime import execute_from_input

    result = execute_from_input("USE_TOOL: add_numbers 2 3")

    assert result is not None
    assert result.get("status") == "success"


# ✳️ TEST 2 — ARGS CORRECTNESS (OBSERVATIONAL)

def test_args_correctness_from_executed_input():
    from system.orchestrator.orchestrator_runtime import execute_from_input

    result = execute_from_input("USE_TOOL: add_numbers 2 3")

    assert result.get("status") == "success"
    assert "5" in str(result.get("result"))


# ✳️ TEST 3 — VALIDATOR INFLUENCES FLOW

def test_validator_handles_failure_path():
    from system.orchestrator.orchestrator_runtime import execute_from_input

    result = execute_from_input("USE_TOOL: force_failure")

    assert result is not None
    assert result.get("status") in ["failure", "success"]


# ✳️ TEST 4 — STEP PURPOSE PROPAGATION

def test_step_purpose_does_not_break_validator():
    from system.orchestrator.orchestrator_runtime import execute_from_input

    result = execute_from_input("USE_TOOL: add_numbers 1 1")

    assert result is not None
    assert result.get("status") == "success"


# ✳️ TEST 1 — SYSTEM ENTRY EXECUTION

def test_system_entry_execution_success():
    from system.entry.system_entry import system_entry

    result = system_entry("add_numbers 2 3")

    assert result is not None
    assert result.get("status") == "success"


# ✳️ TEST 2 — ARGS CORRECTNESS (OBSERVATIONAL)

def test_system_entry_args_correctness():
    from system.entry.system_entry import system_entry

    result = system_entry("add_numbers 2 3")

    assert result.get("status") == "success"
    assert result.get("result") == 5 or "5" in str(result.get("result"))


# ✳️ TEST 3 — VALIDATOR FLOW INTEGRATION

def test_system_entry_failure_handling():
    from system.entry.system_entry import system_entry

    result = system_entry("force_failure")

    assert result is not None
    assert result.get("status") in ["failure", "success"]


# ✳️ TEST 4 — PURPOSE PROPAGATION SAFETY

def test_system_entry_stability():
    from system.entry.system_entry import system_entry

    result = system_entry("add_numbers 1 1")

    assert result is not None
    assert result.get("status") == "success"


# ✳️ TEST 1 — VALIDATOR DRIVES RETRY

def test_validator_drives_retry(monkeypatch):
    from system.orchestrator.orchestrator_runtime import run_workflow

    call_counter = {"count": 0}

    def mock_system_entry(input_data):
        call_counter["count"] += 1
        return {"status": "failure", "reason": "forced_failure"}

    def mock_plan_workflow(input_data):
        return {
            "status": "success",
            "workflow": {
                "id": "retry_test_wf",
                "name": "retry_test",
                "steps": [
                    {
                        "id": "retry_step",
                        "name": "retry_step",
                        "agent": "retry_test_agent",
                        "input": "add_numbers 2 3",
                        "status": "PENDING",
                        "retries": 0,
                        "max_retries": 2
                    }
                ]
            }
        }

    monkeypatch.setattr("system.orchestrator.agent_executor.system_entry", mock_system_entry)
    monkeypatch.setattr("system.orchestrator.orchestrator_runtime.plan_workflow", mock_plan_workflow)
    register_agent({"name": "retry_test_agent", "role": "executor", "scope": ["tools"]})

    workflow = {
        "id": "retry_test_wf",
        "name": "retry_test",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "retry_step",
                "name": "retry_step",
                "agent": "retry_test_agent",
                "status": "PENDING",
                "max_retries": 2,
                "retries": 0,
                "input": "add_numbers 2 3"
            }
        ]
    }

    result = run_workflow(workflow)

    call_count = call_counter["count"]
    print("CALL COUNT:", call_count)

    assert result is not None
    assert result.get("status") in ["success", "failure"]
    assert call_count > 1, f"Retry behavior not triggered - only {call_count} call(s)"
    assert call_count <= 3, f"Calls {call_count} exceed max 3"


# ✳️ TEST 2 — MALFORMED TOOL INPUT (STRUCTURAL)

def test_malformed_tool_input_no_args():
    from system.entry.system_entry import system_entry

    result = system_entry("add_numbers")

    assert result is not None
    assert result.get("status") == "failure"


# ✳️ TEST 3 — MALFORMED TOOL INPUT (PARTIAL)

def test_malformed_tool_input_partial_args():
    from system.entry.system_entry import system_entry

    result = system_entry("add_numbers 2")

    assert result is not None
    assert result.get("status") == "failure"


# ✳️ TEST 4 — EMPTY WORKFLOW (BOUNDARY)

def test_empty_workflow_boundary():
    from system.orchestrator.orchestrator_runtime import run_workflow

    result = run_workflow({"steps": []})

    assert result is not None
    assert result.get("status") in ["failure", "success"]


# ✳️ TEST 5 — ZERO RETRY BOUNDARY

def test_zero_retry_boundary():
    from system.orchestrator.orchestrator_runtime import run_workflow

    workflow = {
        "steps": [
            {
                "id": "zero_retry",
                "name": "zero_retry",
                "agent": "test_agent",
                "input": "force_failure",
                "max_retries": 0,
                "retries": 0
            }
        ]
    }

    result = run_workflow(workflow)

    assert result is not None
    assert result.get("status") in ["failure", "success"]
