"""
CATEGORY: WORKFLOW OUTPUT AGGREGATION
AUTHORITY_LAYER: Orchestrator Runtime / Output Aggregation
VALIDATES:
  - aggregate_workflow_output deterministic behavior
  - Single-step backward compatibility
  - Multi-output preservation
  - Terminal output detection
  - Synthesis hint detection
  - Failed/blocked partial output behavior
  - Legacy workflow["output"] unchanged
ENTRYPOINT: workflow_output_aggregator.aggregate_workflow_output
DIRECT_INTERNAL_CALLS:
  - workflow_output_aggregator.aggregate_workflow_output
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: NONE — pure function over plain dicts
TEST_INTENT: UNIT_LEVEL_VALIDATION
ARCHITECTURAL_SCOPE: Output aggregation helper only

---

ISSUE-PDIAG-004 — Workflow Output Aggregation / Final Result Assembly

Architecture rules preserved:
- runtime registry remains lifecycle authority
- governance remains retry/failure/escalation authority
- system_entry remains sole tool execution gateway
- execution_result remains execution truth
- projection/frontend remain non-authoritative
- persistence remains downstream/non-authoritative
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from system.orchestrator.workflow_output_aggregator import aggregate_workflow_output


# =============================================================================
# HELPERS
# =============================================================================

def _make_step(step_id, status="COMPLETED", exec_res=None, depends_on=None, purpose="", expected_outcome="", blocked_reason=""):
    step = {
        "id": step_id,
        "status": status,
        "execution_result": exec_res,
        "depends_on": depends_on or [],
        "purpose": purpose,
        "expected_outcome": expected_outcome,
        "type": "EXECUTE_API",
    }
    if blocked_reason:
        step["blocked_reason"] = blocked_reason
    return step


def _success_result(value):
    return {"status": "success", "result": value}


def _failure_result(reason):
    return {"status": "failure", "reason": reason}


def _make_workflow(steps, status="COMPLETED", output=None):
    return {
        "id": "wf_test",
        "steps": steps,
        "status": status,
        "output": output,
    }


# =============================================================================
# TESTS
# =============================================================================

def test_single_step_workflow_backward_compatibility():
    """
    Single successful step:
    - output_mode should be 'single'
    - final_output should match workflow['output']
    - workflow['output'] must remain unchanged
    """
    step = _make_step("s1", "COMPLETED", _success_result("42"), purpose="add 2 and 3")
    wf = _make_workflow([step], status="COMPLETED", output=_success_result("42"))
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "single"
    assert agg["final_output"] == _success_result("42")
    assert agg["completed_step_count"] == 1
    assert agg["successful_output_count"] == 1
    assert agg["failed_step_count"] == 0
    assert agg["blocked_step_count"] == 0
    assert len(agg["step_outputs"]) == 1
    assert len(agg["successful_step_outputs"]) == 1
    assert len(agg["terminal_success_outputs"]) == 1
    assert len(agg["source_outputs"]) == 1
    assert agg["synthesis_output"] is None
    assert agg["synthesis_step_id"] is None
    assert agg["aggregation_warnings"] == []
    print("  [PASS] single_step_workflow_backward_compatibility")


def test_two_independent_completed_outputs_preserved():
    """
    Two independent successful steps, no synthesis:
    - output_mode should be 'multi_output_aggregate'
    - terminal_success_outputs should contain both steps
    - source_outputs should contain both steps
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"), purpose="get value A")
    s2 = _make_step("s2", "COMPLETED", _success_result("B"), purpose="get value B")
    wf = _make_workflow([s1, s2], status="COMPLETED", output=_success_result("B"))
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "multi_output_aggregate"
    assert len(agg["terminal_success_outputs"]) == 2
    assert len(agg["source_outputs"]) == 2
    terminal_ids = {t["step_id"] for t in agg["terminal_success_outputs"]}
    assert terminal_ids == {"s1", "s2"}
    source_ids = {s["step_id"] for s in agg["source_outputs"]}
    assert source_ids == {"s1", "s2"}
    assert agg["synthesis_output"] is None
    print("  [PASS] two_independent_completed_outputs_preserved")


def test_three_successful_outputs_preserved():
    """
    Three independent successful steps:
    - all three should appear in terminal_success_outputs and source_outputs
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"))
    s2 = _make_step("s2", "COMPLETED", _success_result("B"))
    s3 = _make_step("s3", "COMPLETED", _success_result("C"))
    wf = _make_workflow([s1, s2, s3], status="COMPLETED")
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "multi_output_aggregate"
    assert len(agg["terminal_success_outputs"]) == 3
    assert len(agg["source_outputs"]) == 3
    print("  [PASS] three_successful_outputs_preserved")


def test_linear_chain_terminal_output_detected():
    """
    Linear chain: s1 -> s2 -> s3
    Terminal success outputs should be only s3.
    With multiple successful completed steps but only one terminal,
    output_mode falls back to last_step_output.
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"), depends_on=[])
    s2 = _make_step("s2", "COMPLETED", _success_result("B"), depends_on=["s1"])
    s3 = _make_step("s3", "COMPLETED", _success_result("C"), depends_on=["s2"])
    wf = _make_workflow([s1, s2, s3], status="COMPLETED")
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "last_step_output"
    assert len(agg["terminal_success_outputs"]) == 1
    assert agg["terminal_success_outputs"][0]["step_id"] == "s3"
    assert len(agg["source_outputs"]) == 1
    assert agg["source_outputs"][0]["step_id"] == "s3"
    print("  [PASS] linear_chain_terminal_output_detected")


def test_mixed_chains_and_independent_branch_terminal_outputs_detected():
    """
    Mixed topology:
    s1 -> s2 -> s3
    s4 independent
    s5 -> s6
    Terminal outputs: s3, s4, s6
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"), depends_on=[])
    s2 = _make_step("s2", "COMPLETED", _success_result("B"), depends_on=["s1"])
    s3 = _make_step("s3", "COMPLETED", _success_result("C"), depends_on=["s2"])
    s4 = _make_step("s4", "COMPLETED", _success_result("D"), depends_on=[])
    s5 = _make_step("s5", "COMPLETED", _success_result("E"), depends_on=[])
    s6 = _make_step("s6", "COMPLETED", _success_result("F"), depends_on=["s5"])
    wf = _make_workflow([s1, s2, s3, s4, s5, s6], status="COMPLETED")
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "multi_output_aggregate"
    terminal_ids = {t["step_id"] for t in agg["terminal_success_outputs"]}
    assert terminal_ids == {"s3", "s4", "s6"}
    source_ids = {s["step_id"] for s in agg["source_outputs"]}
    assert source_ids == {"s3", "s4", "s6"}
    print("  [PASS] mixed_chains_and_independent_branch_terminal_outputs_detected")


def test_final_synthesis_preserves_source_outputs_and_final_output():
    """
    s1 source, s2 source, s3 final synthesis depending on s1 and s2.
    - synthesis_output should be s3
    - source_outputs should be s1 and s2
    - output_mode should be explicit_final_synthesis_output
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"), depends_on=[], purpose="get A")
    s2 = _make_step("s2", "COMPLETED", _success_result("B"), depends_on=[], purpose="get B")
    s3 = _make_step(
        "s3",
        "COMPLETED",
        _success_result("combined A+B"),
        depends_on=["s1", "s2"],
        purpose="summarize and combine results",
        expected_outcome="final answer",
    )
    wf = _make_workflow([s1, s2, s3], status="COMPLETED", output=_success_result("combined A+B"))
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "explicit_final_synthesis_output"
    assert agg["synthesis_step_id"] == "s3"
    assert agg["synthesis_output"] == _success_result("combined A+B")
    assert len(agg["source_outputs"]) == 2
    source_ids = {s["step_id"] for s in agg["source_outputs"]}
    assert source_ids == {"s1", "s2"}
    assert len(agg["terminal_success_outputs"]) == 1
    assert agg["terminal_success_outputs"][0]["step_id"] == "s3"
    print("  [PASS] final_synthesis_preserves_source_outputs_and_final_output")


def test_synthesis_over_subset_does_not_hide_other_terminal_outputs():
    """
    s1 -> s2 -> s3
    s4 independent
    s5 -> s6
    s7 synthesis depending only on s3 and s4.
    - source_outputs should be s3 and s4
    - terminal_success_outputs should include s7 (synthesis) and s6 (other branch)
    - aggregation_warnings should note s6 exists outside synthesis dependencies
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"), depends_on=[])
    s2 = _make_step("s2", "COMPLETED", _success_result("B"), depends_on=["s1"])
    s3 = _make_step("s3", "COMPLETED", _success_result("C"), depends_on=["s2"])
    s4 = _make_step("s4", "COMPLETED", _success_result("D"), depends_on=[])
    s5 = _make_step("s5", "COMPLETED", _success_result("E"), depends_on=[])
    s6 = _make_step("s6", "COMPLETED", _success_result("F"), depends_on=["s5"])
    s7 = _make_step(
        "s7",
        "COMPLETED",
        _success_result("synth"),
        depends_on=["s3", "s4"],
        purpose="combine results into final report",
    )
    wf = _make_workflow([s1, s2, s3, s4, s5, s6, s7], status="COMPLETED")
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "explicit_final_synthesis_output"
    assert agg["synthesis_step_id"] == "s7"
    source_ids = {s["step_id"] for s in agg["source_outputs"]}
    assert source_ids == {"s3", "s4"}
    terminal_ids = {t["step_id"] for t in agg["terminal_success_outputs"]}
    assert terminal_ids == {"s6", "s7"}
    assert len(agg["aggregation_warnings"]) >= 1
    assert any("s6" in w for w in agg["aggregation_warnings"])
    print("  [PASS] synthesis_over_subset_does_not_hide_other_terminal_outputs")


def test_no_final_synthesis_uses_multi_output_aggregate():
    """
    Multiple terminal outputs with no synthesis step detected.
    output_mode must be multi_output_aggregate.
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"), purpose="compute A")
    s2 = _make_step("s2", "COMPLETED", _success_result("B"), purpose="compute B")
    s3 = _make_step("s3", "COMPLETED", _success_result("C"), purpose="compute C")
    wf = _make_workflow([s1, s2, s3], status="COMPLETED")
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "multi_output_aggregate"
    assert agg["synthesis_output"] is None
    assert agg["synthesis_step_id"] is None
    assert len(agg["source_outputs"]) == 3
    print("  [PASS] no_final_synthesis_uses_multi_output_aggregate")


def test_failed_step_output_not_treated_as_successful_source_output():
    """
    s1 success, s2 failed.
    - successful_step_outputs should contain only s1
    - step_outputs should contain both (for inspection)
    - source_outputs should contain only s1
    - output_mode should be partial_result_with_warning
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"))
    s2 = _make_step("s2", "FAILED", _failure_result("division_by_zero"))
    wf = _make_workflow([s1, s2], status="FAILED", output=_success_result("A"))
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "partial_result_with_warning"
    assert len(agg["step_outputs"]) == 2
    assert len(agg["successful_step_outputs"]) == 1
    assert agg["successful_step_outputs"][0]["step_id"] == "s1"
    assert len(agg["source_outputs"]) == 1
    assert agg["source_outputs"][0]["step_id"] == "s1"
    assert agg["failed_step_count"] == 1
    print("  [PASS] failed_step_output_not_treated_as_successful_source_output")


def test_blocked_downstream_step_does_not_create_fake_output():
    """
    s1 success, s2 blocked.
    - source_outputs should contain only s1
    - blocked_step_count should be 1
    - output_mode should be partial_result_with_warning
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"))
    s2 = _make_step("s2", "BLOCKED", None, blocked_reason="dependency_failed:s1")
    wf = _make_workflow([s1, s2], status="BLOCKED")
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "partial_result_with_warning"
    assert len(agg["source_outputs"]) == 1
    assert agg["source_outputs"][0]["step_id"] == "s1"
    assert agg["blocked_step_count"] == 1
    assert agg["failed_step_count"] == 0
    print("  [PASS] blocked_downstream_step_does_not_create_fake_output")


def test_failed_workflow_preserves_partial_successful_outputs_as_inspection_only():
    """
    FAILED workflow with multiple successful completed outputs:
    - output_mode should be partial_result_with_warning
    - successful outputs preserved in source_outputs for inspection
    - final_output should still show last successful (backward compat)
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"))
    s2 = _make_step("s2", "COMPLETED", _success_result("B"))
    s3 = _make_step("s3", "FAILED", _failure_result("timeout"))
    wf = _make_workflow([s1, s2, s3], status="FAILED", output=_success_result("B"))
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "partial_result_with_warning"
    assert len(agg["successful_step_outputs"]) == 2
    assert len(agg["source_outputs"]) == 2
    assert agg["final_output"] == _success_result("B")
    print("  [PASS] failed_workflow_preserves_partial_successful_outputs_as_inspection_only")


def test_workflow_output_legacy_field_unchanged():
    """
    aggregate_workflow_output must NOT mutate the input workflow dict.
    workflow['output'] must remain exactly as passed in.
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"))
    s2 = _make_step("s2", "COMPLETED", _success_result("B"))
    original_output = _success_result("B")
    wf = _make_workflow([s1, s2], status="COMPLETED", output=original_output)

    # Capture pre-call state
    pre_output = wf["output"]
    pre_steps = [dict(s) for s in wf["steps"]]

    agg = aggregate_workflow_output(wf)

    # Post-call state must be identical
    assert wf["output"] is pre_output
    assert wf["output"] == original_output
    for i, s in enumerate(wf["steps"]):
        assert s["execution_result"] == pre_steps[i]["execution_result"]
        assert s["status"] == pre_steps[i]["status"]
    print("  [PASS] workflow_output_legacy_field_unchanged")


def test_final_output_fallback_when_workflow_output_none():
    """
    When workflow['output'] is None, final_output should fallback to
    last successful completed step execution_result.
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"))
    s2 = _make_step("s2", "COMPLETED", _success_result("B"))
    wf = _make_workflow([s1, s2], status="COMPLETED", output=None)
    agg = aggregate_workflow_output(wf)

    assert agg["final_output"] == _success_result("B")
    print("  [PASS] final_output_fallback_when_workflow_output_none")


def test_no_successful_outputs_failed_or_incomplete():
    """
    All steps failed, workflow['output'] is None.
    output_mode should be failed_or_incomplete.
    """
    s1 = _make_step("s1", "FAILED", _failure_result("error1"))
    s2 = _make_step("s2", "FAILED", _failure_result("error2"))
    wf = _make_workflow([s1, s2], status="FAILED", output=None)
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "failed_or_incomplete"
    assert agg["final_output"] is None
    assert len(agg["successful_step_outputs"]) == 0
    assert len(agg["source_outputs"]) == 0
    print("  [PASS] no_successful_outputs_failed_or_incomplete")


def test_single_step_with_failed_execution_result():
    """
    Step is COMPLETED but execution_result has status failure.
    This is a completed step with failed execution.
    output_mode should be failed_or_incomplete.
    """
    s1 = _make_step("s1", "COMPLETED", _failure_result("bad_args"))
    wf = _make_workflow([s1], status="FAILED")
    agg = aggregate_workflow_output(wf)

    assert agg["output_mode"] == "failed_or_incomplete"
    assert len(agg["step_outputs"]) == 1
    assert len(agg["successful_step_outputs"]) == 0
    print("  [PASS] single_step_with_failed_execution_result")


def test_synthesis_hint_requires_multiple_dependencies():
    """
    A step with synthesis keywords but no dependencies should NOT be
    marked as synthesis (conservative default).
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"), purpose="compute A")
    s2 = _make_step("s2", "COMPLETED", _success_result("B"), purpose="final answer")
    wf = _make_workflow([s1, s2], status="COMPLETED")
    agg = aggregate_workflow_output(wf)

    # s2 has "final answer" keyword but no depends_on -> conservative default is False
    assert agg["synthesis_step_id"] is None
    assert agg["output_mode"] == "multi_output_aggregate"
    print("  [PASS] synthesis_hint_requires_multiple_dependencies")


def test_synthesis_hint_with_single_dependency():
    """
    A step with synthesis keywords and a single dependency CAN be marked
    as synthesis hint (keyword + dependency is enough).
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("A"))
    s2 = _make_step("s2", "COMPLETED", _success_result("B"), depends_on=["s1"], purpose="summarize result")
    wf = _make_workflow([s1, s2], status="COMPLETED")
    agg = aggregate_workflow_output(wf)

    # s2 has "summarize" keyword and depends_on -> is_synthesis_hint=True
    assert agg["synthesis_step_id"] == "s2"
    assert agg["output_mode"] == "explicit_final_synthesis_output"
    print("  [PASS] synthesis_hint_with_single_dependency")


# =============================================================================
# RUN ALL
# =============================================================================

if __name__ == "__main__":
    test_single_step_workflow_backward_compatibility()
    test_two_independent_completed_outputs_preserved()
    test_three_successful_outputs_preserved()
    test_linear_chain_terminal_output_detected()
    test_mixed_chains_and_independent_branch_terminal_outputs_detected()
    test_final_synthesis_preserves_source_outputs_and_final_output()
    test_synthesis_over_subset_does_not_hide_other_terminal_outputs()
    test_no_final_synthesis_uses_multi_output_aggregate()
    test_failed_step_output_not_treated_as_successful_source_output()
    test_blocked_downstream_step_does_not_create_fake_output()
    test_failed_workflow_preserves_partial_successful_outputs_as_inspection_only()
    test_workflow_output_legacy_field_unchanged()
    test_final_output_fallback_when_workflow_output_none()
    test_no_successful_outputs_failed_or_incomplete()
    test_single_step_with_failed_execution_result()
    test_synthesis_hint_requires_multiple_dependencies()
    test_synthesis_hint_with_single_dependency()
    print("\n=== ALL TESTS PASSED ===")
