"""
CATEGORY: FALSE SUCCESS DETECTOR
AUTHORITY_LAYER: Orchestrator Runtime / Output Aggregation (Advisory Only)
VALIDATES:
  - evaluate_false_success deterministic behavior
  - instruction echo detection
  - unresolved placeholder detection
  - generic non-answer detection
  - missing comparison detection
  - missing synthesis sources detection
  - single-output-when-multiple-requested detection
  - artifact instruction echo detection
  - valid outputs produce no warnings
  - advisory-only semantics (no lifecycle change)

ENTRYPOINT: false_success_detector.evaluate_false_success
DIRECT_INTERNAL_CALLS:
  - false_success_detector.evaluate_false_success
MOCKING_POLICY: NONE — pure function over plain dicts
TEST_INTENT: UNIT_LEVEL_VALIDATION
ARCHITECTURAL_SCOPE: False-success detector helper only

---

ISSUE-PDIAG-005 Phase 1 — Narrow Purpose/Output False-Success Gate (Advisory Only)

Architecture rules preserved:
- Does NOT change lifecycle, governance, retry, replan, execution_result
- Does NOT set purpose_met=false
- Does NOT block step or workflow completion
- Does NOT trigger retry or replan
- Does NOT change governance decisions
- Does NOT mutate lifecycle state
- Does NOT override execution_result
- Does NOT mark workflow failed/incomplete
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from system.orchestrator.false_success_detector import evaluate_false_success
from system.orchestrator.workflow_output_aggregator import aggregate_workflow_output


# =============================================================================
# HELPERS
# =============================================================================

def _make_step(step_id, status="COMPLETED", exec_res=None, depends_on=None, purpose="", expected_outcome=""):
    step = {
        "id": step_id,
        "status": status,
        "execution_result": exec_res,
        "depends_on": depends_on or [],
        "purpose": purpose,
        "expected_outcome": expected_outcome,
        "type": "EXECUTE_API",
    }
    return step


def _success_result(value):
    return {"status": "success", "result": value}


def _make_workflow(steps, status="COMPLETED", output=None):
    return {
        "id": "wf_test",
        "steps": steps,
        "status": status,
        "output": output,
    }


# =============================================================================
# TESTS: Warning-producing patterns
# =============================================================================

def test_instruction_echo_produces_warning():
    """
    When step output closely matches step purpose, advisory warning is produced.
    """
    purpose = "Generate a summary of the quarterly sales report"
    step = _make_step("s1", "COMPLETED", _success_result(purpose), purpose=purpose)
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is True
    assert any(w["code"] == "instruction_echo_output" for w in fsa["warnings"])
    print("  [PASS] instruction_echo_produces_warning")


def test_unresolved_placeholder_produces_warning():
    """
    When output contains {{...}}, [missing], TBD, or TODO, advisory warning is produced.
    """
    step = _make_step("s1", "COMPLETED", _success_result("The result is {{value}}"), purpose="compute total")
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is True
    assert any(w["code"] == "unresolved_placeholder" for w in fsa["warnings"])
    print("  [PASS] unresolved_placeholder_produces_warning")


def test_generic_non_answer_produces_warning():
    """
    When output is a generic refusal, advisory warning is produced.
    """
    step = _make_step(
        "s1",
        "COMPLETED",
        _success_result("I cannot help with that request."),
        purpose="calculate total sales",
    )
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is True
    assert any(w["code"] == "generic_non_answer" for w in fsa["warnings"])
    print("  [PASS] generic_non_answer_produces_warning")


def test_missing_comparison_produces_warning():
    """
    When purpose implies comparison but result is a bare scalar, advisory warning is produced.
    """
    step = _make_step(
        "s1",
        "COMPLETED",
        _success_result("42"),
        purpose="compare the sales of Q1 and Q2",
    )
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is True
    assert any(w["code"] == "missing_comparison" for w in fsa["warnings"])
    print("  [PASS] missing_comparison_produces_warning")


def test_comparison_with_language_does_not_warn():
    """
    When purpose implies comparison and result contains comparative language, no warning.
    """
    step = _make_step(
        "s1",
        "COMPLETED",
        _success_result("Q1 sales were higher than Q2 sales by 10%"),
        purpose="compare the sales of Q1 and Q2",
    )
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is False
    print("  [PASS] comparison_with_language_does_not_warn")


def test_missing_synthesis_sources_produces_warning():
    """
    When synthesis step does not reference its source outputs, advisory warning is produced.
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("value_alpha_data"), purpose="get alpha")
    s2 = _make_step("s2", "COMPLETED", _success_result("value_beta_data"), purpose="get beta")
    s3 = _make_step(
        "s3",
        "COMPLETED",
        _success_result("Here is a generic greeting."),
        depends_on=["s1", "s2"],
        purpose="summarize and combine results from previous steps",
    )
    wf = _make_workflow([s1, s2, s3], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is True
    assert any(w["code"] == "missing_synthesis_sources" for w in fsa["warnings"])
    print("  [PASS] missing_synthesis_sources_produces_warning")


def test_synthesis_with_sources_does_not_warn():
    """
    When synthesis step references its source outputs, no warning.
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("value_alpha_data"), purpose="get alpha")
    s2 = _make_step("s2", "COMPLETED", _success_result("value_beta_data"), purpose="get beta")
    s3 = _make_step(
        "s3",
        "COMPLETED",
        _success_result("Combined: value_alpha_data and value_beta_data."),
        depends_on=["s1", "s2"],
        purpose="summarize and combine results from previous steps",
    )
    wf = _make_workflow([s1, s2, s3], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    # Should not have missing_synthesis_sources warning
    assert not any(w["code"] == "missing_synthesis_sources" for w in fsa["warnings"])
    print("  [PASS] synthesis_with_sources_does_not_warn")


def test_single_output_when_multiple_requested_produces_warning():
    """
    When purpose implies multiple outputs but result is a short scalar, advisory warning.
    """
    step = _make_step(
        "s1",
        "COMPLETED",
        _success_result("42"),
        purpose="list both results",
    )
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is True
    assert any(w["code"] == "single_output_when_multiple_requested" for w in fsa["warnings"])
    print("  [PASS] single_output_when_multiple_requested_produces_warning")


def test_artifact_instruction_echo_produces_warning():
    """
    When generation step output matches the instruction, instruction_echo_output warning is produced
    (artifact_contains_instruction is deduplicated since instruction_echo_output is more specific).
    """
    purpose = "Write a poem about spring"
    step = _make_step("s1", "COMPLETED", _success_result(purpose), purpose=purpose)
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is True
    assert any(w["code"] == "instruction_echo_output" for w in fsa["warnings"])
    print("  [PASS] artifact_instruction_echo_produces_warning")


# =============================================================================
# TESTS: No-warning patterns
# =============================================================================

def test_valid_numeric_output_does_not_warn():
    """
    Simple arithmetic with numeric result produces no warning.
    """
    step = _make_step("s1", "COMPLETED", _success_result(42), purpose="add 20 and 22")
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is False
    assert fsa["summary"] == "no obvious false-success pattern detected"
    print("  [PASS] valid_numeric_output_does_not_warn")


def test_valid_text_output_does_not_warn():
    """
    Retrieval with meaningful text produces no warning.
    """
    step = _make_step(
        "s1",
        "COMPLETED",
        _success_result("The capital of France is Paris."),
        purpose="fetch capital of France",
    )
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is False
    print("  [PASS] valid_text_output_does_not_warn")


def test_valid_synthesis_with_sources_does_not_warn():
    """
    Synthesis step that references sources produces no missing-sources warning.
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("Q1 sales: $100K"), purpose="get Q1 sales")
    s2 = _make_step("s2", "COMPLETED", _success_result("Q2 sales: $120K"), purpose="get Q2 sales")
    s3 = _make_step(
        "s3",
        "COMPLETED",
        _success_result("Combined: Q1 sales: $100K and Q2 sales: $120K. Total: $220K."),
        depends_on=["s1", "s2"],
        purpose="combine sales figures",
    )
    wf = _make_workflow([s1, s2, s3], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert not any(w["code"] == "missing_synthesis_sources" for w in fsa["warnings"])
    print("  [PASS] valid_synthesis_with_sources_does_not_warn")


# =============================================================================
# TESTS: Advisory-only semantics
# =============================================================================

def test_warning_does_not_change_lifecycle_status():
    """
    False-success warning must NOT mutate workflow status.
    """
    step = _make_step("s1", "COMPLETED", _success_result("I cannot help with that."), purpose="calculate total")
    wf = _make_workflow([step], status="COMPLETED")
    original_status = wf["status"]
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is True
    assert wf["status"] == original_status
    print("  [PASS] warning_does_not_change_lifecycle_status")


def test_warning_does_not_change_execution_result():
    """
    False-success warning must NOT mutate step execution_result.
    """
    original_result = _success_result("I cannot help with that.")
    step = _make_step("s1", "COMPLETED", original_result, purpose="calculate total")
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is True
    assert step["execution_result"] is original_result
    print("  [PASS] warning_does_not_change_execution_result")


def test_warning_does_not_change_step_status():
    """
    False-success warning must NOT mutate step status.
    """
    step = _make_step("s1", "COMPLETED", _success_result("TBD"), purpose="calculate total")
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)
    fsa = agg["false_success_analysis"]

    assert fsa["warning"] is True
    assert step["status"] == "COMPLETED"
    print("  [PASS] warning_does_not_change_step_status")


def test_warning_appears_in_output_aggregation():
    """
    false_success_analysis must be present in output_aggregation dict.
    """
    step = _make_step("s1", "COMPLETED", _success_result("42"), purpose="compare A and B")
    wf = _make_workflow([step], status="COMPLETED")
    agg = aggregate_workflow_output(wf)

    assert "false_success_analysis" in agg
    assert isinstance(agg["false_success_analysis"], dict)
    assert "warning" in agg["false_success_analysis"]
    assert "warnings" in agg["false_success_analysis"]
    assert "summary" in agg["false_success_analysis"]
    print("  [PASS] warning_appears_in_output_aggregation")


def test_detector_fail_safe_on_malformed_input():
    """
    Detector must not crash on malformed/missing data.
    """
    result = evaluate_false_success({}, {})
    assert isinstance(result, dict)
    assert result["warning"] is False
    assert result["summary"] == "no obvious false-success pattern detected"
    print("  [PASS] detector_fail_safe_on_malformed_input")


# =============================================================================
# TESTS: Phase 2A compute_step_governance_input
# =============================================================================

from system.orchestrator.false_success_detector import compute_step_governance_input


def test_governance_input_placeholder_sets_purpose_met_false():
    """
    unresolved_placeholder detected → purpose_met=False.
    """
    step = _make_step("s1", "COMPLETED", _success_result("The result is {{value}}"), purpose="compute total")
    result = compute_step_governance_input(step)

    assert result["purpose_met"] is False
    assert result["false_success_detected"] is True
    assert result["governance_reason"] == "unresolved_placeholder"
    assert result["severity"] == "lifecycle"
    assert result["scope"] == "step"
    print("  [PASS] governance_input_placeholder_sets_purpose_met_false")


def test_governance_input_instruction_echo_sets_purpose_met_false():
    """
    instruction_echo_output detected → purpose_met=False.
    """
    purpose = "Generate a summary of the quarterly sales report"
    step = _make_step("s1", "COMPLETED", _success_result(purpose), purpose=purpose)
    result = compute_step_governance_input(step)

    assert result["purpose_met"] is False
    assert result["false_success_detected"] is True
    assert result["governance_reason"] == "instruction_echo_output"
    assert result["severity"] == "lifecycle"
    print("  [PASS] governance_input_instruction_echo_sets_purpose_met_false")


def test_governance_input_valid_numeric_does_not_warn():
    """
    Valid numeric output → purpose_met=True, no false-success detected.
    """
    step = _make_step("s1", "COMPLETED", _success_result(42), purpose="add 20 and 22")
    result = compute_step_governance_input(step)

    assert result["purpose_met"] is True
    assert result["false_success_detected"] is False
    assert result["governance_reason"] is None
    assert result["severity"] is None
    print("  [PASS] governance_input_valid_numeric_does_not_warn")


def test_governance_input_valid_text_does_not_warn():
    """
    Valid text output → purpose_met=True.
    """
    step = _make_step("s1", "COMPLETED", _success_result("The capital of France is Paris."), purpose="fetch capital")
    result = compute_step_governance_input(step)

    assert result["purpose_met"] is True
    assert result["false_success_detected"] is False
    print("  [PASS] governance_input_valid_text_does_not_warn")


def test_governance_input_generic_non_answer_advisory_only():
    """
    generic_non_answer must NOT be governance-affecting.
    It must remain advisory-only (Phase 1).
    """
    step = _make_step(
        "s1",
        "COMPLETED",
        _success_result("I cannot help with that request."),
        purpose="calculate total",
    )
    result = compute_step_governance_input(step)

    assert result["purpose_met"] is True
    assert result["false_success_detected"] is False
    assert result["governance_reason"] is None
    print("  [PASS] governance_input_generic_non_answer_advisory_only")


def test_governance_input_missing_comparison_advisory_only():
    """
    missing_comparison must NOT be governance-affecting.
    """
    step = _make_step("s1", "COMPLETED", _success_result("42"), purpose="compare the sales of Q1 and Q2")
    result = compute_step_governance_input(step)

    assert result["purpose_met"] is True
    assert result["false_success_detected"] is False
    print("  [PASS] governance_input_missing_comparison_advisory_only")


def test_governance_input_missing_synthesis_advisory_only():
    """
    missing_synthesis_sources must NOT be governance-affecting.
    """
    s1 = _make_step("s1", "COMPLETED", _success_result("value_alpha_data"), purpose="get alpha")
    s2 = _make_step("s2", "COMPLETED", _success_result("value_beta_data"), purpose="get beta")
    s3 = _make_step(
        "s3",
        "COMPLETED",
        _success_result("Here is a generic greeting."),
        depends_on=["s1", "s2"],
        purpose="summarize and combine results from previous steps",
    )
    wf = _make_workflow([s1, s2, s3], status="COMPLETED")
    result = compute_step_governance_input(s3, wf)

    assert result["purpose_met"] is True
    assert result["false_success_detected"] is False
    print("  [PASS] governance_input_missing_synthesis_advisory_only")


def test_governance_input_single_output_advisory_only():
    """
    single_output_when_multiple_requested must NOT be governance-affecting.
    """
    step = _make_step("s1", "COMPLETED", _success_result("42"), purpose="list both results")
    result = compute_step_governance_input(step)

    assert result["purpose_met"] is True
    assert result["false_success_detected"] is False
    print("  [PASS] governance_input_single_output_advisory_only")


def test_governance_input_artifact_instruction_advisory_only():
    """
    artifact_contains_instruction must NOT be governance-affecting.
    It overlaps instruction_echo_output but is less specific.
    """
    purpose = "Write a poem about spring"
    step = _make_step("s1", "COMPLETED", _success_result(purpose), purpose=purpose)
    # instruction_echo_output IS governance-affecting, but artifact_contains_instruction
    # is deduplicated in Phase 1. compute_step_governance_input should only flag
    # instruction_echo_output (which it does via _looks_like_instruction_echo).
    result = compute_step_governance_input(step)

    # Note: instruction_echo_output IS approved for Phase 2A.
    # This test verifies the approved code is used, not the advisory-only one.
    assert result["false_success_detected"] is True
    assert result["governance_reason"] == "instruction_echo_output"
    print("  [PASS] governance_input_artifact_instruction_maps_to_approved_echo")


def test_governance_input_no_mutation():
    """
    compute_step_governance_input must NOT mutate step, execution_result, or status.
    """
    original_result = _success_result("{{value}}")
    step = _make_step("s1", "COMPLETED", original_result, purpose="compute total")
    original_step = dict(step)

    compute_step_governance_input(step)

    assert step["status"] == original_step["status"]
    assert step["execution_result"] is original_result
    assert step.get("purpose_met", True) == original_step.get("purpose_met", True)
    print("  [PASS] governance_input_no_mutation")


def test_governance_input_fail_safe_on_malformed():
    """
    compute_step_governance_input must be fail-safe on malformed input.
    """
    result = compute_step_governance_input({})
    assert isinstance(result, dict)
    assert result["purpose_met"] is True
    assert result["false_success_detected"] is False
    assert result["scope"] == "step"
    print("  [PASS] governance_input_fail_safe_on_malformed")


# =============================================================================
# RUN ALL
# =============================================================================

if __name__ == "__main__":
    test_instruction_echo_produces_warning()
    test_unresolved_placeholder_produces_warning()
    test_generic_non_answer_produces_warning()
    test_missing_comparison_produces_warning()
    test_comparison_with_language_does_not_warn()
    test_missing_synthesis_sources_produces_warning()
    test_synthesis_with_sources_does_not_warn()
    test_single_output_when_multiple_requested_produces_warning()
    test_artifact_instruction_echo_produces_warning()
    test_valid_numeric_output_does_not_warn()
    test_valid_text_output_does_not_warn()
    test_valid_synthesis_with_sources_does_not_warn()
    test_warning_does_not_change_lifecycle_status()
    test_warning_does_not_change_execution_result()
    test_warning_does_not_change_step_status()
    test_warning_appears_in_output_aggregation()
    test_detector_fail_safe_on_malformed_input()
    # Phase 2A tests
    test_governance_input_placeholder_sets_purpose_met_false()
    test_governance_input_instruction_echo_sets_purpose_met_false()
    test_governance_input_valid_numeric_does_not_warn()
    test_governance_input_valid_text_does_not_warn()
    test_governance_input_generic_non_answer_advisory_only()
    test_governance_input_missing_comparison_advisory_only()
    test_governance_input_missing_synthesis_advisory_only()
    test_governance_input_single_output_advisory_only()
    test_governance_input_artifact_instruction_advisory_only()
    test_governance_input_no_mutation()
    test_governance_input_fail_safe_on_malformed()
    print("\n=== ALL TESTS PASSED ===")
