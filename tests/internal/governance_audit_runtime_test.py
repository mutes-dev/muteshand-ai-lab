#!/usr/bin/env python3
"""
Governance Capability Reconciliation Audit — Phase 3 Runtime Testing
Audit-only. No modifications to source code.
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from system.orchestrator.governance import (
    decide_next_action,
    GovernanceDecision,
    RetryStrategy,
    GovernanceContext,
    _create_governance_context,
    replay_governance_decision,
    is_execution_valid,
    _evaluate_retry_exhaustion,
    _evaluate_retry_eligibility,
    _get_risk_based_max_retries,
    _get_step_tool_name,
    _PHASE2A_RAW_ACQUISITION_TOOLS,
)
from system.orchestrator.escalation_controller import (
    handle_retry,
    handle_escalation,
    _normalize_action,
)
from system.orchestrator.drift_detector import compare as drift_compare
from system.orchestrator.intent_validator import evaluate_intent

# =============================================================================
# Helpers
# =============================================================================
def _make_step(status="PENDING", retries=0, risk="MEDIUM", importance="normal", purpose_met=True, purpose="test"):
    return {
        "id": "step_1",
        "status": status,
        "retries": retries,
        "risk": risk,
        "importance": importance,
        "purpose_met": purpose_met,
        "purpose": purpose,
        "input": purpose,
    }

def _make_context():
    return {"workflow_id": "wf_1"}

def _make_exec_result(status="success", result="ok"):
    return {"status": status, "result": result}

TRACE = []

def _log(event, data):
    TRACE.append({"event": event, "data": data})
    print(f"[AUDIT_TEST] {event}: {data}")

# =============================================================================
# TEST SUITE: Governance Decision Engine
# =============================================================================

def test_governance_decision_complete():
    """COMPLETE when execution success + purpose_met + valid execution."""
    step = _make_step(status="ACTIVE", purpose_met=True)
    step["executed_input"] = "test"
    result = _make_exec_result("success", "ok")
    decision = decide_next_action(None, result, step, _make_context())
    _log("governance_decision_complete", {
        "action": decision.action,
        "reason": decision.reason,
        "authority_source": decision.authority_source,
    })
    assert decision.action == "complete", f"Expected complete, got {decision.action}"
    assert decision.authority_source == "execution_result"
    return True

def test_governance_decision_retry_on_failure():
    """RETRY when execution failure and retries < max."""
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    result = _make_exec_result("failure", None)
    decision = decide_next_action(None, result, step, _make_context())
    _log("governance_decision_retry_on_failure", {
        "action": decision.action,
        "retry_strategy": decision.retry_strategy,
        "reason": decision.reason,
    })
    assert decision.action == "retry", f"Expected retry, got {decision.action}"
    assert decision.retry_strategy == RetryStrategy.SAME
    return True

def test_governance_decision_escalate_on_exhaustion():
    """ESCALATE when retries exhausted — always, no override bypass."""
    step = _make_step(status="ACTIVE", retries=3, risk="MEDIUM")
    step["max_retries"] = 3
    result = _make_exec_result("failure", None)
    decision = decide_next_action(None, result, step, _make_context())
    _log("governance_decision_escalate_on_exhaustion", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "escalate", f"Expected escalate, got {decision.action}"
    return True

def test_governance_decision_no_override_parameter():
    """decide_next_action must not accept override_state."""
    import inspect
    sig = inspect.signature(decide_next_action)
    assert "override_state" not in sig.parameters, "override_state must not be in decide_next_action signature"
    _log("governance_no_override_parameter", {"pass": True})
    return True

def test_governance_decision_no_execution_result():
    """FAIL when execution_result is None."""
    step = _make_step(status="ACTIVE")
    decision = decide_next_action(None, None, step, _make_context())
    _log("governance_decision_no_execution_result", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "fail", f"Expected fail, got {decision.action}"
    return True

def test_governance_decision_success_but_invalid():
    """RETRY when execution success but no executed_input (invalid execution)."""
    step = _make_step(status="ACTIVE", purpose_met=True)
    # No executed_input → is_execution_valid returns False
    result = _make_exec_result("success", "ok")
    decision = decide_next_action(None, result, step, _make_context())
    _log("governance_decision_success_but_invalid", {
        "action": decision.action,
        "reason": decision.reason,
    })
    # Since no executed_input, validity fails. Should retry if eligible.
    assert decision.action == "retry", f"Expected retry, got {decision.action}"
    return True

def test_governance_decision_purpose_not_met():
    """RETRY when execution success but purpose_met=False."""
    step = _make_step(status="ACTIVE", purpose_met=False)
    step["executed_input"] = "test"
    result = _make_exec_result("success", "ok")
    decision = decide_next_action(None, result, step, _make_context())
    _log("governance_decision_purpose_not_met", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "retry", f"Expected retry, got {decision.action}"
    return True

def test_governance_decision_validator_advisory_no_influence():
    """Validator signals MUST NOT influence governance decision."""
    step = _make_step(status="ACTIVE", purpose_met=True)
    step["executed_input"] = "test"
    result = _make_exec_result("success", "ok")
    # Validator says "retry" — governance should still return complete
    validator_output = {"recommendation": "retry", "reason": "fake", "signals": {"constraint_ok": False}}
    decision = decide_next_action(validator_output, result, step, _make_context())
    _log("governance_decision_validator_advisory_no_influence", {
        "action": decision.action,
        "validator_recommendation": validator_output["recommendation"],
    })
    assert decision.action == "complete", f"Expected complete (validator advisory ignored), got {decision.action}"
    # Verify advisory metadata stored
    assert step.get("_validator_advisory") == "fake"
    assert step.get("_validator_decision") == "retry"
    return True

def test_governance_decision_high_risk_fewer_retries():
    """HIGH risk should reduce max_retries to 1."""
    step = _make_step(status="ACTIVE", retries=1, risk="HIGH")
    result = _make_exec_result("failure", None)
    decision = decide_next_action(None, result, step, _make_context())
    _log("governance_decision_high_risk_fewer_retries", {
        "action": decision.action,
        "risk": step["risk"],
        "retries": step["retries"],
    })
    # HIGH risk max_retries = 1, retries = 1 → exhausted → escalate
    assert decision.action == "escalate", f"Expected escalate (HIGH risk exhausted), got {decision.action}"
    return True

def test_governance_replay_determinism():
    """Replay MUST produce identical decision."""
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    step["executed_input"] = "test"
    result = _make_exec_result("success", "ok")
    decision1 = decide_next_action(None, result, step, _make_context())
    ctx = _create_governance_context(result, step, _make_context())
    decision2 = replay_governance_decision(ctx)
    _log("governance_replay_determinism", {
        "decision1_action": decision1.action,
        "decision2_action": decision2.action,
        "match": decision1 == decision2,
    })
    assert decision1 == decision2, f"Replay mismatch: {decision1.action} != {decision2.action}"
    return True

# =============================================================================
# TEST SUITE: PDIAG-005 Phase 2A Governance Integration
# =============================================================================

def test_governance_phase2a_placeholder_triggers_retry():
    """unresolved_placeholder detected with retries remaining → RETRY."""
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    step["executed_input"] = "test"
    step["purpose"] = "compute total"
    result = _make_exec_result("success", "The result is {{value}}")
    step["execution_result"] = result  # Required for compute_step_governance_input
    decision = decide_next_action(None, result, step, _make_context())
    _log("governance_phase2a_placeholder_triggers_retry", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "retry", f"Expected retry, got {decision.action}"
    assert step.get("_false_success_reason") == "unresolved_placeholder"
    assert step.get("purpose_met") is False
    return True

def test_governance_phase2a_instruction_echo_triggers_retry():
    """instruction_echo_output detected with retries remaining → RETRY."""
    purpose = "Generate a summary of the quarterly sales report"
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    step["executed_input"] = "test"
    step["purpose"] = purpose
    result = _make_exec_result("success", purpose)
    step["execution_result"] = result
    decision = decide_next_action(None, result, step, _make_context())
    _log("governance_phase2a_instruction_echo_triggers_retry", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "retry", f"Expected retry, got {decision.action}"
    assert step.get("_false_success_reason") == "instruction_echo_output"
    assert step.get("purpose_met") is False
    return True

def test_governance_phase2a_placeholder_exhausts_to_escalate():
    """unresolved_placeholder detected with retries exhausted → ESCALATE."""
    step = _make_step(status="ACTIVE", retries=3, risk="MEDIUM")
    step["max_retries"] = 3
    step["executed_input"] = "test"
    step["purpose"] = "compute total"
    result = _make_exec_result("success", "The result is {{value}}")
    step["execution_result"] = result
    decision = decide_next_action(None, result, step, _make_context())
    _log("governance_phase2a_placeholder_exhausts_to_escalate", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "escalate", f"Expected escalate, got {decision.action}"
    assert step.get("_false_success_reason") == "unresolved_placeholder"
    assert step.get("purpose_met") is False
    return True

def test_governance_phase2a_valid_output_completes():
    """Valid output (no false-success pattern) still COMPLETES."""
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    step["executed_input"] = "test"
    step["purpose"] = "add 20 and 22"
    result = _make_exec_result("success", 42)
    step["execution_result"] = result
    decision = decide_next_action(None, result, step, _make_context())
    _log("governance_phase2a_valid_output_completes", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "complete", f"Expected complete, got {decision.action}"
    assert step.get("purpose_met", True) is True
    assert step.get("_false_success_reason") is None
    return True

def test_governance_phase2a_execution_result_unchanged():
    """execution_result must remain unchanged after Phase 2A detection."""
    original_result = {"status": "success", "result": "{{value}}"}
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    step["executed_input"] = "test"
    step["purpose"] = "compute total"
    result = dict(original_result)
    step["execution_result"] = result
    decision = decide_next_action(None, result, step, _make_context())
    _log("governance_phase2a_execution_result_unchanged", {
        "action": decision.action,
        "result_status": result.get("status"),
        "result_value": result.get("result"),
    })
    assert result["status"] == original_result["status"]
    assert result["result"] == original_result["result"]
    # execution_result on step should still be the same object
    assert step["execution_result"] is result
    return True

# =============================================================================
# TEST SUITE: FOUNDATION-RETOUCH-001 Raw Acquisition Tool Bypass
# =============================================================================

def test_phase2a_read_file_placeholder_bypasses():
    """read_file output containing {{...}} must not trigger Phase-2A retry."""
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    step["executed_input"] = 'read_file "E:\\MutesHand\\Project Docs\\SYSTEM_STATE_V2.txt"'
    step["purpose"] = "Read the file E:\\MutesHand\\Project Docs\\SYSTEM_STATE_V2.txt"
    result = _make_exec_result("success", "This file contains {{customer_name}} and TODO markers.")
    step["execution_result"] = result
    decision = decide_next_action(None, result, step, _make_context())
    _log("phase2a_read_file_placeholder_bypasses", {
        "action": decision.action,
        "reason": decision.reason,
        "purpose_met": step.get("purpose_met"),
        "false_success_reason": step.get("_false_success_reason"),
    })
    assert decision.action == "complete", f"Expected complete, got {decision.action}"
    assert step.get("purpose_met", True) is True
    assert step.get("_false_success_reason") is None
    return True

def test_phase2a_read_file_todo_bypasses():
    """read_file output containing TODO/TBD/N/A must not trigger Phase-2A retry."""
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    step["executed_input"] = 'read_file "docs/plan.md"'
    step["purpose"] = "Read docs/plan.md"
    result = _make_exec_result("success", "Plan: TODO - implement feature. Status: TBD. Note: N/A.")
    step["execution_result"] = result
    decision = decide_next_action(None, result, step, _make_context())
    _log("phase2a_read_file_todo_bypasses", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "complete", f"Expected complete, got {decision.action}"
    assert step.get("purpose_met", True) is True
    return True

def test_phase2a_read_webpage_placeholder_bypasses():
    """read_webpage output containing placeholder-like text must not trigger Phase-2A retry."""
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    step["executed_input"] = 'read_webpage "https://example.com"'
    step["purpose"] = "Read https://example.com"
    result = _make_exec_result("success", "Welcome to {{site_name}}. TODO: add content.")
    step["execution_result"] = result
    decision = decide_next_action(None, result, step, _make_context())
    _log("phase2a_read_webpage_placeholder_bypasses", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "complete", f"Expected complete, got {decision.action}"
    assert step.get("purpose_met", True) is True
    return True

def test_phase2a_list_files_placeholder_bypasses():
    """list_files output must not trigger Phase-2A retry even with placeholder-like filenames."""
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    step["executed_input"] = 'list_files "tmp"'
    step["purpose"] = "List files in tmp"
    result = _make_exec_result("success", "TODO.txt\n{{template}}.md\nN/A.log")
    step["execution_result"] = result
    decision = decide_next_action(None, result, step, _make_context())
    _log("phase2a_list_files_placeholder_bypasses", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "complete", f"Expected complete, got {decision.action}"
    assert step.get("purpose_met", True) is True
    return True

def test_phase2a_web_search_placeholder_bypasses():
    """web_search raw result output must not trigger Phase-2A retry."""
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    step["executed_input"] = 'web_search "{{customer_name}} status"'
    step["purpose"] = 'Search for "{{customer_name}} status"'
    result = _make_exec_result("success", "Results: TODO list for {{customer_name}} includes TBD items.")
    step["execution_result"] = result
    decision = decide_next_action(None, result, step, _make_context())
    _log("phase2a_web_search_placeholder_bypasses", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "complete", f"Expected complete, got {decision.action}"
    assert step.get("purpose_met", True) is True
    return True

def test_phase2a_finalize_output_placeholder_still_triggers():
    """finalize_output containing unresolved placeholders must still trigger Phase-2A retry."""
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    step["executed_input"] = 'finalize_output "The result is {{customer_name}}"'
    step["purpose"] = "Extract key points from step_1"
    result = _make_exec_result("success", "The result is {{customer_name}}")
    step["execution_result"] = result
    decision = decide_next_action(None, result, step, _make_context())
    _log("phase2a_finalize_output_placeholder_still_triggers", {
        "action": decision.action,
        "reason": decision.reason,
    })
    assert decision.action == "retry", f"Expected retry, got {decision.action}"
    assert step.get("purpose_met") is False
    assert step.get("_false_success_reason") == "unresolved_placeholder"
    return True

def test_phase2a_bypass_uses_agent_metadata_selected_tool():
    """_get_step_tool_name must prefer _agent_metadata.selected_tool when available."""
    step = _make_step(status="ACTIVE", retries=0, risk="MEDIUM")
    # executed_input must be non-empty for is_execution_valid to pass,
    # but agent_metadata should take priority over it.
    step["executed_input"] = 'finalize_output "test"'
    step["tool_call"] = None
    step["_agent_metadata"] = {"selected_tool": "read_file"}
    step["purpose"] = "compute total"
    result = _make_exec_result("success", "The result is {{value}}")
    step["execution_result"] = result
    tool_name = _get_step_tool_name(step)
    assert tool_name == "read_file", f"Expected read_file, got {tool_name}"
    decision = decide_next_action(None, result, step, _make_context())
    assert decision.action == "complete", f"Expected complete, got {decision.action}"
    return True

def test_phase2a_raw_acquisition_tool_set_membership():
    """_PHASE2A_RAW_ACQUISITION_TOOLS must contain the expected tool names."""
    expected = {"read_file", "read_webpage", "web_search", "list_files"}
    assert _PHASE2A_RAW_ACQUISITION_TOOLS == expected, f"Mismatch: {_PHASE2A_RAW_ACQUISITION_TOOLS}"
    return True

# =============================================================================
# TEST SUITE: Escalation Controller
# =============================================================================

def test_escalation_controller_retry():
    """handle_retry increments retries and returns RETRY action."""
    step = _make_step(status="ACTIVE", retries=0)
    step["max_retries"] = 3  # REQUIRED by handle_retry line 148
    workflow = {"id": "wf_1", "steps": [step]}
    result = handle_retry(step, workflow, "retry", governance_decision=None)
    _log("escalation_controller_retry", {
        "action": result["action"],
        "retries_after": step["retries"],
    })
    assert result["action"] == "RETRY", f"Expected RETRY, got {result['action']}"
    assert step["retries"] == 1
    return True

def test_escalation_controller_max_retries_blocked():
    """handle_retry converts to BLOCKED when max retries reached."""
    step = _make_step(status="ACTIVE", retries=2)
    step["max_retries"] = 2
    workflow = {"id": "wf_1", "steps": [step]}
    result = handle_retry(step, workflow, "retry", governance_decision=None)
    _log("escalation_controller_max_retries_blocked", {
        "action": result["action"],
        "retries_after": step["retries"],
    })
    assert result["action"] == "BLOCKED", f"Expected BLOCKED, got {result['action']}"
    assert step["retries"] == 3  # incremented before check
    return True

def test_escalation_controller_escalation():
    """handle_escalation sets BLOCKED."""
    step = _make_step(status="ACTIVE")
    workflow = {"id": "wf_1", "steps": [step], "output": None}
    result = handle_escalation(step, workflow, "escalate", {}, governance_decision=None)
    _log("escalation_controller_escalation", {
        "action": result["action"],
    })
    assert result["action"] == "BLOCKED", f"Expected BLOCKED, got {result['action']}"
    return True

# =============================================================================
# TEST SUITE: Drift Detector (Advisory Only)
# =============================================================================

def test_drift_detector_missing_execution_result():
    """Drift on missing execution_result = LARGE (observational only)."""
    signal = drift_compare(None, None)
    _log("drift_detector_missing_execution_result", signal)
    assert signal["drift_detected"] is True
    assert signal["drift_type"] == "LARGE"
    return True

def test_drift_detector_execution_failure():
    """Execution failure = LARGE drift (observational only)."""
    signal = drift_compare("test", {"status": "failure", "result": None})
    _log("drift_detector_execution_failure", signal)
    assert signal["drift_detected"] is True
    assert signal["drift_type"] == "LARGE"
    return True

def test_drift_detector_no_semantic_expectation():
    """No semantic expectation = NONE drift (valid, not error)."""
    signal = drift_compare("test", {"status": "success", "result": 42}, semantic_expectation=None)
    _log("drift_detector_no_semantic_expectation", signal)
    assert signal["drift_detected"] is False
    assert signal["drift_type"] == "NONE"
    return True

def test_drift_detector_shape_mismatch():
    """Shape mismatch = LARGE drift."""
    from system.orchestrator.semantic_expectation import SHAPE_SCALAR
    se = {"semantic_domain": "numeric", "output_shape": SHAPE_SCALAR, "semantic_category": "arithmetic"}
    signal = drift_compare("test", {"status": "success", "result": [1, 2, 3]}, semantic_expectation=se)
    _log("drift_detector_shape_mismatch", signal)
    assert signal["drift_detected"] is True
    assert signal["drift_type"] == "LARGE"
    return True

# =============================================================================
# TEST SUITE: Intent Validator (Advisory Only)
# =============================================================================

def test_validator_empty_output():
    """Empty output → retry recommendation (advisory)."""
    result = evaluate_intent("test", None, None, "", "purpose", execution_result=None)
    _log("validator_empty_output", result)
    # NOTE: evaluate_intent has inconsistent return format — early exits use 'decision',
    # final return uses 'recommendation'. This is an actual code inconsistency (audit finding).
    key = "decision" if "decision" in result else "recommendation"
    assert result[key] == "retry"
    return True

def test_validator_execution_success_correct():
    """Execution success with correct result → accept (advisory)."""
    result = evaluate_intent(
        "multiply 2 and 3",
        "calculator",
        [2, 3],
        "6",
        "multiply 2 and 3",
        execution_result={"status": "success", "result": 6},
        executed_input="multiply 2 and 3",
    )
    _log("validator_execution_success_correct", result)
    assert result["recommendation"] == "accept"
    return True

def test_validator_signals_stored_not_authoritative():
    """Validator stores signals but they are advisory only."""
    # Even with constraint violation signals, validator just reports advisory
    result = evaluate_intent(
        "add 1 and 2 but output only the count",
        "calculator",
        [1, 2],
        "3",
        "add 1 and 2 but output only the count",
        execution_result={"status": "success", "result": "3"},
        executed_input="add 1 and 2 but output only the count",
    )
    _log("validator_signals_stored_not_authoritative", result)
    # Validator returns accept or retry based on its own logic, but it's advisory
    assert "recommendation" in result
    assert "signals" in result
    return True

# =============================================================================
# RUN ALL TESTS
# =============================================================================
TESTS = [
    test_governance_decision_complete,
    test_governance_decision_retry_on_failure,
    test_governance_decision_escalate_on_exhaustion,
    test_governance_decision_no_override_parameter,
    test_governance_decision_no_execution_result,
    test_governance_decision_success_but_invalid,
    test_governance_decision_purpose_not_met,
    test_governance_decision_validator_advisory_no_influence,
    test_governance_decision_high_risk_fewer_retries,
    test_governance_replay_determinism,
    # PDIAG-005 Phase 2A
    test_governance_phase2a_placeholder_triggers_retry,
    test_governance_phase2a_instruction_echo_triggers_retry,
    test_governance_phase2a_placeholder_exhausts_to_escalate,
    test_governance_phase2a_valid_output_completes,
    test_governance_phase2a_execution_result_unchanged,
    # FOUNDATION-RETOUCH-001 Raw Acquisition Tool Bypass
    test_phase2a_read_file_placeholder_bypasses,
    test_phase2a_read_file_todo_bypasses,
    test_phase2a_read_webpage_placeholder_bypasses,
    test_phase2a_list_files_placeholder_bypasses,
    test_phase2a_web_search_placeholder_bypasses,
    test_phase2a_finalize_output_placeholder_still_triggers,
    test_phase2a_bypass_uses_agent_metadata_selected_tool,
    test_phase2a_raw_acquisition_tool_set_membership,
    test_escalation_controller_retry,
    test_escalation_controller_max_retries_blocked,
    test_escalation_controller_escalation,
    test_drift_detector_missing_execution_result,
    test_drift_detector_execution_failure,
    test_drift_detector_no_semantic_expectation,
    test_drift_detector_shape_mismatch,
    test_validator_empty_output,
    test_validator_execution_success_correct,
    test_validator_signals_stored_not_authoritative,
]

if __name__ == "__main__":
    passed = 0
    failed = 0
    for test in TESTS:
        try:
            test()
            passed += 1
            print(f"  PASS: {test.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL: {test.__name__} — {e}")

    print(f"\n{'='*60}")
    print(f"AUDIT RUNTIME TEST RESULTS: {passed}/{len(TESTS)} passed, {failed}/{len(TESTS)} failed")
    print(f"{'='*60}")
    if failed > 0:
        sys.exit(1)
