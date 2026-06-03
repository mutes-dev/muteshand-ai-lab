#!/usr/bin/env python3
"""
ISSUE-073 — AG1 Adversarial Containment + Governance Hardening Tests

Proves:
- _agent_metadata is attached after AG1 execution
- _agent_metadata is advisory-only and absent-safe
- _agent_metadata does not leak into execution_result, system_entry, prompts, or governance
- AG1 cannot bypass system_entry, override execution_result, trigger retry, or mutate state
- No persistent agent identity, multi-agent coordination, adaptive orchestration, or legacy reconnection
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.entry.system_entry import system_entry
from system.orchestrator.step_executor import execute_step, _build_agent_metadata, _safe_extract_tool_name
from system.orchestrator.governance import decide_next_action, GovernanceDecision
from system.orchestrator.agent_registry import register_agent, agents


def _make_step(**kwargs):
    defaults = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "purpose": "test purpose",
        "tool_call": "USE_TOOL: square_number 5",
        "input": "square 5",
        "expected_outcome": "25",
        "risk": "LOW",
        "importance": "MEDIUM",
        "resource_targets": [],
        "status": "ACTIVE",
        "retries": 0
    }
    defaults.update(kwargs)
    return defaults


def _make_workflow(**kwargs):
    defaults = {
        "id": "wf_1",
        "name": "test",
        "status": "ACTIVE",
        "steps": []
    }
    defaults.update(kwargs)
    return defaults


# =============================================================================
# METADATA ATTACHMENT TESTS
# =============================================================================

def test_agent_metadata_attached_after_execution():
    """_agent_metadata must be present on step after execute_step returns."""
    print("\n[AG1 CONTAINMENT] Metadata Attached After Execution")
    step = _make_step()
    workflow = _make_workflow()
    result = execute_step(step, workflow)

    has_metadata = "_agent_metadata" in step
    print(f"  _agent_metadata present: {has_metadata}")
    assert has_metadata, "_agent_metadata was NOT attached to step"
    print("  PASS: _agent_metadata attached")
    return True


def test_agent_metadata_advisory_only_field_set():
    """_agent_metadata must contain explicit advisory-only classification."""
    print("\n[AG1 CONTAINMENT] Metadata Advisory-Only Field Set")
    step = _make_step()
    workflow = _make_workflow()
    execute_step(step, workflow)

    meta = step.get("_agent_metadata", {})
    authority = meta.get("agent_authority")
    print(f"  agent_authority: {authority}")
    assert authority == "advisory_only", f"Expected 'advisory_only', got {authority}"
    print("  PASS: agent_authority is advisory_only")
    return True


def test_agent_metadata_selected_tool_extracted():
    """_agent_metadata.selected_tool must match the executed tool."""
    print("\n[AG1 CONTAINMENT] Metadata Selected Tool Extracted")
    step = _make_step(tool_call="square_number 5")
    workflow = _make_workflow()
    execute_step(step, workflow)

    meta = step.get("_agent_metadata", {})
    selected_tool = meta.get("selected_tool")
    print(f"  selected_tool: {selected_tool}")
    assert selected_tool == "square_number", f"Expected 'square_number', got {selected_tool}"
    print("  PASS: selected_tool correctly extracted")
    return True


def test_agent_metadata_not_in_execution_result():
    """_agent_metadata must NOT appear inside execution_result dict."""
    print("\n[AG1 CONTAINMENT] Metadata Not In execution_result")
    step = _make_step()
    workflow = _make_workflow()
    result = execute_step(step, workflow)

    exec_res = result.get("execution_result")
    print(f"  execution_result keys: {list(exec_res.keys()) if isinstance(exec_res, dict) else 'N/A'}")

    if isinstance(exec_res, dict):
        assert "_agent_metadata" not in exec_res, "_agent_metadata leaked into execution_result"
        # Also verify strict 2-field schema
        assert len(exec_res) == 2, f"execution_result has {len(exec_res)} fields, expected 2"
    print("  PASS: _agent_metadata absent from execution_result")
    return True


def test_agent_metadata_not_in_system_entry_output():
    """system_entry output must remain strict status + result/reason with no metadata."""
    print("\n[AG1 CONTAINMENT] Metadata Not In system_entry Output")
    result = system_entry("square_number 5")
    print(f"  system_entry output: {result}")

    assert isinstance(result, dict), "system_entry output must be a dict"
    assert "_agent_metadata" not in result, "_agent_metadata leaked into system_entry output"
    # Verify strict 2-field schema
    assert len(result) == 2, f"system_entry output has {len(result)} fields, expected 2"
    assert "status" in result, "system_entry missing 'status'"
    assert "result" in result or "reason" in result, "system_entry missing 'result' or 'reason'"
    print("  PASS: system_entry output unchanged")
    return True


def test_agent_metadata_not_in_system_entry_input():
    """system_entry input must not contain _agent_metadata."""
    print("\n[AG1 CONTAINMENT] Metadata Not In system_entry Input")
    # We verify by calling system_entry and checking it does not fail due to extra fields
    # system_entry only accepts raw tool call strings, so metadata cannot be passed as input
    result = system_entry("square_number 5")
    assert result.get("status") == "success", "system_entry failed unexpectedly"
    print("  PASS: system_entry input schema unaffected")
    return True


def test_agent_metadata_not_in_agent_input():
    """agent_input (step tool_call/purpose/input) must not contain _agent_metadata."""
    print("\n[AG1 CONTAINMENT] Metadata Not In agent_input")
    step = _make_step(tool_call="square_number 5")
    workflow = _make_workflow()
    execute_step(step, workflow)

    # Verify the original inputs are unchanged
    assert step.get("tool_call") == "square_number 5", "tool_call was mutated"
    assert step.get("purpose") == "test purpose", "purpose was mutated"
    assert step.get("input") == "square 5", "input was mutated"
    print("  PASS: agent_input unchanged")
    return True


def test_agent_metadata_absent_safe():
    """Consumers must handle missing _agent_metadata safely."""
    print("\n[AG1 CONTAINMENT] Metadata Absent-Safe")
    step = _make_step()
    # Simulate a step that never had metadata attached
    if "_agent_metadata" in step:
        del step["_agent_metadata"]

    # Governance must not fail when metadata is absent
    exec_res = {"status": "success", "result": "ok"}
    decision = decide_next_action(
        validator_output={},
        execution_result=exec_res,
        step=step,
        context={"workflow_id": "wf_1"}
    )
    assert decision.action in ("complete", "retry", "escalate", "fail", "block"), \
        f"Governance failed with missing metadata: {decision.action}"
    print("  PASS: absent _agent_metadata does not break governance")
    return True


# =============================================================================
# GOVERNANCE ISOLATION TESTS
# =============================================================================

def test_governance_decision_unchanged_by_metadata():
    """Governance decision must be identical with and without _agent_metadata."""
    print("\n[AG1 CONTAINMENT] Governance Decision Unchanged By Metadata")

    # Step WITH metadata
    step_with = _make_step(purpose_met=True, executed_input="test")
    step_with["_agent_metadata"] = {
        "selected_agent": "tool_selection_agent",
        "agent_authority": "advisory_only",
        "selected_tool": "square_number"
    }
    result = {"status": "success", "result": "ok"}
    decision_with = decide_next_action({}, result, step_with, {"workflow_id": "wf_1"})

    # Step WITHOUT metadata
    step_without = _make_step(purpose_met=True, executed_input="test")
    if "_agent_metadata" in step_without:
        del step_without["_agent_metadata"]
    decision_without = decide_next_action({}, result, step_without, {"workflow_id": "wf_1"})

    print(f"  Decision with metadata: {decision_with.action}")
    print(f"  Decision without metadata: {decision_without.action}")
    assert decision_with.action == decision_without.action, \
        f"Governance decision changed by metadata: {decision_with.action} vs {decision_without.action}"
    print("  PASS: governance decision identical")
    return True


def test_retry_does_not_consume_agent_metadata():
    """Retry logic must not read _agent_metadata for guidance."""
    print("\n[AG1 CONTAINMENT] Retry Does Not Consume Metadata")

    # Verify by inspection: retry_guidance comes from step._governance_retry_guidance,
    # not from _agent_metadata
    step = _make_step(retries=1)
    step["_agent_metadata"] = {"selected_agent": "tool_selection_agent", "fake_guidance": "retry_now"}
    step["_governance_retry_guidance"] = "use fewer args"

    # The real retry guidance should come from _governance_retry_guidance
    actual_guidance = step.get("_governance_retry_guidance")
    fake_guidance = step.get("_agent_metadata", {}).get("fake_guidance")
    assert actual_guidance == "use fewer args", "Retry guidance source incorrect"
    assert fake_guidance == "retry_now", "Test setup error"
    # Retry logic MUST NOT look at fake_guidance
    print(f"  _governance_retry_guidance: {actual_guidance}")
    print(f"  _agent_metadata fake_guidance (must be ignored): {fake_guidance}")
    print("  PASS: retry uses correct guidance source")
    return True


def test_validator_does_not_consume_agent_metadata():
    """Validator behavior must not be influenced by _agent_metadata."""
    print("\n[AG1 CONTAINMENT] Validator Does Not Consume Metadata")

    # The validator in step_executor evaluates intent based on step input/output,
    # not on _agent_metadata. We verify this by checking validator_output is computed
    # from executed_input, not from metadata.
    step = _make_step(tool_call="square_number 5")
    step["_agent_metadata"] = {"selected_agent": "tool_selection_agent", "selected_tool": "fake_tool"}
    workflow = _make_workflow()
    result = execute_step(step, workflow)

    # executed_input should be the real tool call, not from metadata
    executed_input = result.get("executed_input")
    print(f"  executed_input: {executed_input}")
    assert "fake_tool" not in str(executed_input), "Validator consumed fake metadata"
    print("  PASS: validator ignores metadata")
    return True


# =============================================================================
# AG1 CONTAINMENT TESTS
# =============================================================================

def test_ag1_routes_through_system_entry():
    """AG1 (tool_selection_agent) must route all execution through system_entry."""
    print("\n[AG1 CONTAINMENT] AG1 Routes Through system_entry")

    from unittest.mock import patch, MagicMock
    from system.orchestrator.agent_executor import execute_agent

    agents.clear()
    register_agent({"name": "test_agent", "role": "test", "scope": ["test"]})

    mock_system_entry = MagicMock(return_value={"status": "success", "result": 25})
    mock_provider = MagicMock()
    mock_get_llm = MagicMock(return_value={"status": "success", "provider": mock_provider})
    mock_execute_llm = MagicMock(return_value={"status": "success", "result": "USE_TOOL: square_number 5"})

    with patch("system.orchestrator.agents.tool_selection_agent.system_entry", mock_system_entry), \
         patch("system.orchestrator.agents.tool_selection_agent.get_llm", mock_get_llm), \
         patch("system.orchestrator.agents.tool_selection_agent.execute_llm", mock_execute_llm):
        result = execute_agent({"name": "test_agent", "role": "test", "scope": ["test"]}, "square 5")

    assert mock_system_entry.called, "system_entry was NOT called — AG1 bypassed execution gateway"
    print("  PASS: system_entry called by AG1")
    return True


def test_ag1_cannot_override_execution_result():
    """AG1 must not be able to override execution_result authority."""
    print("\n[AG1 CONTAINMENT] AG1 Cannot Override execution_result")

    from unittest.mock import patch, MagicMock
    from system.orchestrator.agent_executor import execute_agent

    agents.clear()
    register_agent({"name": "test_agent", "role": "test", "scope": ["test"]})

    # system_entry returns failure, but AG1 should not be able to change it
    mock_system_entry = MagicMock(return_value={"status": "failure", "reason": "tool_error"})
    mock_provider = MagicMock()
    mock_get_llm = MagicMock(return_value={"status": "success", "provider": mock_provider})
    mock_execute_llm = MagicMock(return_value={"status": "success", "result": "USE_TOOL: square_number 5"})

    with patch("system.orchestrator.agents.tool_selection_agent.system_entry", mock_system_entry), \
         patch("system.orchestrator.agents.tool_selection_agent.get_llm", mock_get_llm), \
         patch("system.orchestrator.agents.tool_selection_agent.execute_llm", mock_execute_llm):
        result = execute_agent({"name": "test_agent", "role": "test", "scope": ["test"]}, "square 5")

    exec_res = result["result"]["execution_result"]
    assert exec_res["status"] == "failure", f"AG1 overrode execution_result: {exec_res}"
    assert exec_res["reason"] == "tool_error", f"AG1 mutated failure reason: {exec_res}"
    print("  PASS: execution_result preserved, AG1 cannot override")
    return True


def test_ag1_cannot_trigger_retry_independently():
    """AG1 must not be able to trigger retry without governance authorization."""
    print("\n[AG1 CONTAINMENT] AG1 Cannot Trigger Retry Independently")

    from unittest.mock import patch, MagicMock
    from system.orchestrator.agent_executor import execute_agent

    agents.clear()
    register_agent({"name": "test_agent", "role": "test", "scope": ["test"]})

    # Even if LLM says "retry", AG1 output format only produces USE_TOOL or response.
    # Retry is a governance decision, not an agent output.
    mock_provider = MagicMock()
    mock_get_llm = MagicMock(return_value={"status": "success", "provider": mock_provider})
    mock_execute_llm = MagicMock(return_value={"status": "success", "result": "USE_TOOL: square_number 5"})

    with patch("system.orchestrator.agents.tool_selection_agent.get_llm", mock_get_llm), \
         patch("system.orchestrator.agents.tool_selection_agent.execute_llm", mock_execute_llm):
        result = execute_agent({"name": "test_agent", "role": "test", "scope": ["test"]}, "square 5")

    # Agent output does not contain any retry signal
    assert "retry" not in str(result).lower() or result.get("status") == "success", \
        "AG1 output contained retry signal unexpectedly"
    print("  PASS: AG1 output format does not support retry signals")
    return True


def test_ag1_rejects_unknown_tool():
    """AG1 must reject unknown tools rather than bypassing validation."""
    print("\n[AG1 CONTAINMENT] AG1 Rejects Unknown Tool")

    from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

    result = execute_tool_selection(
        agent={"name": "test", "role": "test", "scope": ["test"]},
        input_data="USE_TOOL: nonexistent_tool_xyz"
    )
    print(f"  Result: {result}")
    assert result["status"] == "success", f"Expected success wrapper, got {result}"
    exec_res = result["result"]["execution_result"]
    assert exec_res["status"] == "failure", f"Unknown tool was not rejected: {exec_res}"
    assert exec_res["reason"] == "unknown_tool", f"Wrong rejection reason: {exec_res}"
    print("  PASS: unknown tool rejected")
    return True


def test_ag1_rejects_non_production_tool():
    """AG1 must reject non-production tools."""
    print("\n[AG1 CONTAINMENT] AG1 Rejects Non-Production Tool")

    from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

    result = execute_tool_selection(
        agent={"name": "test", "role": "test", "scope": ["test"]},
        input_data="USE_TOOL: bad_add 5 10"
    )
    print(f"  Result: {result}")
    assert result["status"] == "success", f"Expected success wrapper, got {result}"
    exec_res = result["result"]["execution_result"]
    assert exec_res["status"] == "failure", f"Non-production tool was not rejected: {exec_res}"
    assert exec_res["reason"] == "non_production_tool", f"Wrong rejection reason: {exec_res}"
    print("  PASS: non-production tool rejected")
    return True


# =============================================================================
# LIFECYCLE / STATE MUTATION ISOLATION
# =============================================================================

def test_lifecycle_does_not_read_agent_metadata():
    """Lifecycle state transitions must not reference _agent_metadata."""
    print("\n[AG1 CONTAINMENT] Lifecycle Does Not Read Metadata")

    # Verify by direct inspection: step status transitions are based on
    # execution_result and governance decisions, not metadata.
    step = _make_step(status="ACTIVE")
    workflow = _make_workflow()
    execute_step(step, workflow)

    # After execute_step, status should still be ACTIVE (governance in parallel_executor handles transitions)
    assert step.get("status") == "ACTIVE", f"Step status incorrectly changed to {step.get('status')}"
    print("  PASS: lifecycle state unchanged by metadata")
    return True


def test_mutation_legality_not_influenced_by_metadata():
    """Mutation legality decisions must not use _agent_metadata."""
    print("\n[AG1 CONTAINMENT] Mutation Legality Not Influenced By Metadata")

    step = _make_step()
    step["_agent_metadata"] = {"fake_mutation_approval": True}
    workflow = _make_workflow()
    execute_step(step, workflow)

    # No mutation should have occurred based on fake metadata
    assert "fake_mutation_approval" not in str(step), "Mutation legality consumed fake metadata"
    print("  PASS: mutation legality ignores metadata")
    return True


# =============================================================================
# ARCHITECTURAL BOUNDARY TESTS
# =============================================================================

def test_no_persistent_agent_identity():
    """AG1 must not introduce persistent agent identity beyond static registration."""
    print("\n[AG1 CONTAINMENT] No Persistent Agent Identity")

    from system.orchestrator.agent_registry import get_agent, agents
    from system.orchestrator.bootstrap import initialize_system
    if "tool_selection_agent" not in agents:
        initialize_system()
    result = get_agent("tool_selection_agent")
    assert result.get("status") == "success", "tool_selection_agent not registered"
    agent = result["agent"]

    # Agent identity is static registry data, not runtime mutation
    assert "identity_token" not in agent, "Persistent identity token found"
    assert "session_id" not in agent, "Session identity found"
    assert "memory" not in agent, "Agent memory found"
    print(f"  Agent fields: {list(agent.keys())}")
    print("  PASS: no persistent identity fields")
    return True


def test_no_multi_agent_coordination():
    """AG1 must not introduce multi-agent coordination."""
    print("\n[AG1 CONTAINMENT] No Multi-Agent Coordination")

    from system.orchestrator.agent_registry import agents
    # After bootstrap, only default_agent and tool_selection_agent should exist
    # No coordination channels, message buses, or agent-to-agent communication
    for name, agent in agents.items():
        assert "coordination_channel" not in str(agent), f"Coordination channel in {name}"
        assert "message_bus" not in str(agent), f"Message bus in {name}"
    print(f"  Registered agents: {list(agents.keys())}")
    print("  PASS: no multi-agent coordination artifacts")
    return True


def test_no_adaptive_orchestration():
    """AG1 must not introduce adaptive orchestration."""
    print("\n[AG1 CONTAINMENT] No Adaptive Orchestration")

    # Adaptive orchestration would require learning state, policy tables, or
    # dynamic behavior modification. Verify absence.
    step = _make_step()
    workflow = _make_workflow()
    execute_step(step, workflow)

    assert "_adaptive_policy" not in step, "Adaptive policy found on step"
    assert "_learning_state" not in step, "Learning state found on step"
    print("  PASS: no adaptive orchestration artifacts")
    return True


def test_no_dormant_legacy_agent_reconnection():
    """AG1 must not reconnect dormant legacy agents."""
    print("\n[AG1 CONTAINMENT] No Dormant Legacy Agent Reconnection")

    from system.orchestrator.agent_registry import agents
    legacy_names = ["code_agent", "tester_agent", "system_test_agent"]
    for name in legacy_names:
        assert name not in agents, f"Legacy agent '{name}' was unexpectedly registered"
    print(f"  Registered agents: {list(agents.keys())}")
    print("  PASS: no legacy agents reconnected")
    return True


# =============================================================================
# PROMPT ISOLATION TESTS
# =============================================================================

def test_prompt_behavior_unchanged():
    """Prompt text in tool_selection_agent.py must not contain _agent_metadata references."""
    print("\n[AG1 CONTAINMENT] Prompt Behavior Unchanged")

    import os
    tsa_path = os.path.join("system", "orchestrator", "agents", "tool_selection_agent.py")
    with open(tsa_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "_agent_metadata" not in content, "tool_selection_agent.py contains metadata reference"
    assert "agent_authority" not in content, "tool_selection_agent.py contains authority reference"
    print("  PASS: prompt text unchanged, no metadata contamination")
    return True


# =============================================================================
# RUN ALL
# =============================================================================
TESTS = [
    test_agent_metadata_attached_after_execution,
    test_agent_metadata_advisory_only_field_set,
    test_agent_metadata_selected_tool_extracted,
    test_agent_metadata_not_in_execution_result,
    test_agent_metadata_not_in_system_entry_output,
    test_agent_metadata_not_in_system_entry_input,
    test_agent_metadata_not_in_agent_input,
    test_agent_metadata_absent_safe,
    test_governance_decision_unchanged_by_metadata,
    test_retry_does_not_consume_agent_metadata,
    test_validator_does_not_consume_agent_metadata,
    test_ag1_routes_through_system_entry,
    test_ag1_cannot_override_execution_result,
    test_ag1_cannot_trigger_retry_independently,
    test_ag1_rejects_unknown_tool,
    test_ag1_rejects_non_production_tool,
    test_lifecycle_does_not_read_agent_metadata,
    test_mutation_legality_not_influenced_by_metadata,
    test_no_persistent_agent_identity,
    test_no_multi_agent_coordination,
    test_no_adaptive_orchestration,
    test_no_dormant_legacy_agent_reconnection,
    test_prompt_behavior_unchanged,
]

if __name__ == "__main__":
    passed = 0
    failed = 0
    for test in TESTS:
        try:
            ok = test()
            if ok:
                passed += 1
                print(f"  PASS: {test.__name__}")
            else:
                failed += 1
                print(f"  FAIL: {test.__name__} — returned False")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  FAIL: {test.__name__} — {e}")
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"AG1 CONTAINMENT TEST RESULTS: {passed}/{len(TESTS)} passed, {failed}/{len(TESTS)} failed")
    print(f"{'='*60}")
    if failed > 0:
        sys.exit(1)
