"""
Orchestrator Internal Behavior Tests — run_workflow Entry

Tests retry behavior, max retries, and failure propagation using
direct run_workflow calls with controlled mocking.

Entry Point: system.orchestrator.orchestrator_runtime.run_workflow
Contract: FLAT (status + result/reason)
"""

import pytest
from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator.agent_registry import register_agent


def test_retry_failure_to_success(monkeypatch):
    """
    Test: failure → retry → success
    
    First call fails, second call succeeds.
    Validates retry mechanism and final success output.
    """
    call_counter = {"count": 0}
    
    def mock_system_entry(input_data):
        call_counter["count"] += 1
        if call_counter["count"] == 1:
            return {"status": "failure", "reason": "forced failure"}
        return {"status": "success", "result": 10}
    
    # Patch system_entry to control execution
    monkeypatch.setattr(
        "system.orchestrator.agent_executor.system_entry",
        mock_system_entry
    )
    
    # Register test agent
    register_agent({"name": "test_agent", "role": "executor", "scope": ["tools"]})
    
    # Workflow input
    workflow = {
        "id": "retry_success_wf",
        "name": "retry_success",
        "status": "ACTIVE",
        "steps": [{
            "id": "s1",
            "name": "step",
            "agent": "test_agent",
            "status": "PENDING",
            "retries": 0,
            "max_retries": 2,
            "input": "USE_TOOL: add_numbers 5 5",
            "purpose": "USE_TOOL: add_numbers 5 5"
        }]
    }
    
    # Execute
    result = run_workflow(workflow)
    
    # Print debug info
    print("CALL COUNT:", call_counter["count"])
    print("RESULT:", result)
    
    # VALIDATION
    # 1. Final output is success
    assert result["status"] == "success", f"Expected success, got {result}"
    
    # 2. Retry occurred (more than 1 call)
    assert call_counter["count"] > 1, f"Retry not triggered, only {call_counter['count']} call(s)"
    
    # 3. Respects max retries bound
    assert call_counter["count"] <= workflow["steps"][0]["max_retries"] + 1, \
        f"Exceeded max retries: {call_counter['count']} > {workflow['steps'][0]['max_retries'] + 1}"
    
    # 4. Flat contract structure
    assert "result" in result


def test_max_retries_exhausted_failure(monkeypatch):
    """
    Test: continuous failure → max retries exhausted → failure
    
    All calls fail. Validates failure output and retry bounds.
    """
    call_counter = {"count": 0}
    
    def mock_system_entry(input_data):
        call_counter["count"] += 1
        return {"status": "failure", "reason": "forced failure"}
    
    # Patch system_entry to always fail
    monkeypatch.setattr(
        "system.orchestrator.agent_executor.system_entry",
        mock_system_entry
    )
    
    # Register test agent
    register_agent({"name": "test_agent", "role": "executor", "scope": ["tools"]})
    
    # Workflow input
    workflow = {
        "id": "max_retry_wf",
        "name": "max_retry_test",
        "status": "ACTIVE",
        "steps": [{
            "id": "s1",
            "name": "step",
            "agent": "test_agent",
            "status": "PENDING",
            "retries": 0,
            "max_retries": 2,
            "input": "USE_TOOL: add_numbers 5 5",
            "purpose": "USE_TOOL: add_numbers 5 5"
        }]
    }
    
    # Execute
    result = run_workflow(workflow)
    
    # Print debug info
    print("CALL COUNT:", call_counter["count"])
    print("RESULT:", result)
    
    # VALIDATION
    # 1. Final output is failure
    assert result["status"] == "failure", f"Expected failure, got {result}"
    
    # 2. Retry count equals max_retries + 1 (initial + retries)
    assert call_counter["count"] == workflow["steps"][0]["max_retries"], \
        f"Expected {workflow['steps'][0]['max_retries'] + 1} calls, got {call_counter['count']}"
    
    # 3. Failure contract structure
    assert "reason" in result
    assert isinstance(result["reason"], str)
    assert len(result["reason"]) > 0


def test_failure_propagation_invalid_tool():
    """
    Test: invalid tool → failure with reason
    
    Uses real execution (no mocking) with invalid tool name.
    Validates failure contract is correctly returned.
    """
    # Register test agent
    register_agent({"name": "test_agent", "role": "executor", "scope": ["tools"]})
    
    # Workflow with nonexistent tool
    workflow = {
        "id": "failure_wf",
        "name": "failure_test",
        "status": "ACTIVE",
        "steps": [{
            "id": "s1",
            "name": "step",
            "agent": "test_agent",
            "status": "PENDING",
            "retries": 0,
            "max_retries": 2,
            "input": "USE_TOOL: nonexistent_tool_xyz 1 2",
            "purpose": "USE_TOOL: nonexistent_tool_xyz 1 2"
        }]
    }
    
    # Execute
    result = run_workflow(workflow)
    
    # Print debug info
    print("RESULT:", result)
    
    # VALIDATION
    # 1. Final output is failure
    assert result["status"] == "failure", f"Expected failure, got {result}"
    
    # 2. Failure contract has reason
    assert "reason" in result, f"Missing 'reason' field in {result}"
    
    # 3. Reason is string type
    assert isinstance(result["reason"], str), f"Reason not string: {type(result['reason'])}"
    
    # 4. Reason is non-empty
    assert len(result["reason"]) > 0, "Reason is empty string"
    
    # 5. No result field in failure
    assert "result" not in result, f"Failure should not have 'result' field: {result}"
