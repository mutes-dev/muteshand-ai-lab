"""
Signal Integrity Tests — Harness Expansion

Purpose:
    Enforce that signals (validator, mismatch, agent suggestions)
    NEVER influence control flow. Only execution_result drives decisions.

Rules:
    - validator = advisory ONLY
    - mismatch = advisory ONLY
    - agent output = advisory ONLY
    - execution_result = ONLY decision driver
    - governance = ONLY decision authority
"""

import sys
import os
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, str(PROJECT_ROOT))

from system.orchestrator.governance import decide_next_action

# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def _fmt(label, er, vo, step, decision, expected, passed):
    print(f"  execution_result: {json.dumps(er)}")
    print(f"  validator_output: {json.dumps(vo)}")
    print(f"  step state:       retries={step.get('retries')}, max_retries={step.get('max_retries')}, mismatch={step.get('mismatch', False)}")
    print(f"  decision:         {decision}")
    print(f"  expected:         {expected}")
    print(f"  [{'PASS' if passed else 'FAIL'}] {label}")


# ================================================================
# TEST 1 — Validator Retry Ignored
# ================================================================
def test_validator_retry_ignored():
    """Validator says retry, execution says success → COMPLETE."""
    print("\n" + "=" * 60)
    print("  TEST 1 — Validator Retry Ignored")
    print("=" * 60)

    er = {"status": "success", "result": 42}
    vo = {"decision": "retry", "reason": "tool_mismatch"}
    step = {"retries": 0, "max_retries": 3}

    decision = decide_next_action(
        validator_output=vo,
        execution_result=er,
        step=step,
        context={}
    )

    passed = decision == "complete"
    _fmt("Validator retry ignored", er, vo, step, decision, "complete", passed)

    assert decision == "complete", f"SIGNAL LEAK: validator retry changed decision to '{decision}'"
    assert step.get("_validator_advisory") == "tool_mismatch", "Advisory not stored"


# ================================================================
# TEST 2 — Validator Fail Ignored
# ================================================================
def test_validator_fail_ignored():
    """Validator says fail, execution says success → COMPLETE."""
    print("\n" + "=" * 60)
    print("  TEST 2 — Validator Fail Ignored")
    print("=" * 60)

    er = {"status": "success", "result": 100}
    vo = {"decision": "fail", "reason": "critical_error"}
    step = {"retries": 0, "max_retries": 3}

    decision = decide_next_action(
        validator_output=vo,
        execution_result=er,
        step=step,
        context={}
    )

    passed = decision == "complete"
    _fmt("Validator fail ignored", er, vo, step, decision, "complete", passed)

    assert decision == "complete", f"SIGNAL LEAK: validator fail changed decision to '{decision}'"


# ================================================================
# TEST 3a — Execution Failure Drives Retry
# ================================================================
def test_execution_failure_drives_retry():
    """Execution fails, retries available → RETRY."""
    print("\n" + "=" * 60)
    print("  TEST 3a — Execution Failure Drives Retry")
    print("=" * 60)

    er = {"status": "failure", "reason": "division_by_zero"}
    vo = {"decision": "accept"}
    step = {"retries": 0, "max_retries": 3}

    decision = decide_next_action(
        validator_output=vo,
        execution_result=er,
        step=step,
        context={}
    )

    passed = decision == "retry"
    _fmt("Execution failure → retry", er, vo, step, decision, "retry", passed)

    assert decision == "retry", f"Expected 'retry', got '{decision}'"


# ================================================================
# TEST 3b — Execution Failure Drives Fail (Exhausted)
# ================================================================
def test_execution_failure_drives_fail():
    """Execution fails, retries exhausted → FAIL."""
    print("\n" + "=" * 60)
    print("  TEST 3b — Execution Failure Drives Fail (Exhausted)")
    print("=" * 60)

    er = {"status": "failure", "reason": "division_by_zero"}
    vo = {"decision": "accept"}
    step = {"retries": 3, "max_retries": 3}

    decision = decide_next_action(
        validator_output=vo,
        execution_result=er,
        step=step,
        context={}
    )

    passed = decision == "fail"
    _fmt("Execution failure → fail (exhausted)", er, vo, step, decision, "fail", passed)

    assert decision == "fail", f"Expected 'fail', got '{decision}'"


# ================================================================
# TEST 4 — Mismatch Signal Ignored
# ================================================================
def test_mismatch_signal_ignored():
    """Mismatch is True, execution says success → COMPLETE."""
    print("\n" + "=" * 60)
    print("  TEST 4 — Mismatch Signal Ignored")
    print("=" * 60)

    er = {"status": "success", "result": 25}
    vo = {}
    step = {
        "retries": 0,
        "max_retries": 3,
        "mismatch": True,
        "execution_result": {"status": "success", "result": 25},
        "output": "The answer is 25"
    }

    decision = decide_next_action(
        validator_output=vo,
        execution_result=er,
        step=step,
        context={}
    )

    passed = decision == "complete"
    _fmt("Mismatch signal ignored", er, vo, step, decision, "complete", passed)

    assert decision == "complete", f"SIGNAL LEAK: mismatch changed decision to '{decision}'"
    assert step.get("_mismatch_advisory") is True, "Mismatch advisory not stored"


# ================================================================
# TEST 5 — LLM Output Wrong, Execution Correct
# ================================================================
def test_llm_output_wrong_execution_correct():
    """LLM output != execution result, but execution succeeds → COMPLETE."""
    print("\n" + "=" * 60)
    print("  TEST 5 — LLM Output Wrong, Execution Correct")
    print("=" * 60)

    er = {"status": "success", "result": 20}
    vo = {}
    step = {
        "retries": 0,
        "max_retries": 3,
        "mismatch": True,
        "execution_result": {"status": "success", "result": 20},
        "output": "The answer is 80"  # Wrong LLM output
    }

    decision = decide_next_action(
        validator_output=vo,
        execution_result=er,
        step=step,
        context={}
    )

    passed = decision == "complete"
    _fmt("LLM wrong but execution correct", er, vo, step, decision, "complete", passed)

    assert decision == "complete", f"SIGNAL LEAK: LLM output mismatch changed decision to '{decision}'"


# ================================================================
# TEST 6 — Agent Suggests Retry, Execution Success
# ================================================================
def test_agent_suggests_retry_ignored():
    """Agent output implies retry, execution succeeds → COMPLETE."""
    print("\n" + "=" * 60)
    print("  TEST 6 — Agent Suggests Retry (Simulated)")
    print("=" * 60)

    er = {"status": "success", "result": 10}
    # Simulate: agent's interpretation flagged as retry
    vo = {"decision": "retry", "reason": "agent_suggested_retry"}
    step = {
        "retries": 0,
        "max_retries": 3,
        "decision": "retry"  # Agent-level decision flag (advisory)
    }

    decision = decide_next_action(
        validator_output=vo,
        execution_result=er,
        step=step,
        context={}
    )

    passed = decision == "complete"
    _fmt("Agent retry suggestion ignored", er, vo, step, decision, "complete", passed)

    assert decision == "complete", f"SIGNAL LEAK: agent suggestion changed decision to '{decision}'"
    assert step.get("_validator_advisory") == "agent_suggested_retry", "Advisory not stored"


# ================================================================
# TEST 7 — No Execution Result (Synthetic Failure)
# ================================================================
def test_no_execution_result_synthetic_failure():
    """No execution_result → runtime synthesizes failure → governance decides."""
    print("\n" + "=" * 60)
    print("  TEST 7 — No Execution Result (Synthetic Failure)")
    print("=" * 60)

    # Simulate runtime synthesis: execution_result was None, runtime creates:
    er_synth = {"status": "failure", "reason": "no_output"}

    # 7a: retries available → retry
    step_a = {"retries": 0, "max_retries": 3}
    decision_a = decide_next_action(
        validator_output={},
        execution_result=er_synth,
        step=step_a,
        context={}
    )

    passed_a = decision_a == "retry"
    print(f"  7a: execution_result: {json.dumps(er_synth)}")
    print(f"      retries: 0/3 → decision: {decision_a} (expected: retry)")
    print(f"      [{'PASS' if passed_a else 'FAIL'}]")

    assert decision_a == "retry", f"Expected 'retry', got '{decision_a}'"

    # 7b: retries exhausted → fail
    step_b = {"retries": 3, "max_retries": 3}
    decision_b = decide_next_action(
        validator_output={},
        execution_result=er_synth,
        step=step_b,
        context={}
    )

    passed_b = decision_b == "fail"
    print(f"  7b: retries: 3/3 → decision: {decision_b} (expected: fail)")
    print(f"      [{'PASS' if passed_b else 'FAIL'}]")

    assert decision_b == "fail", f"Expected 'fail', got '{decision_b}'"

    # 7c: None execution_result (not synthesized) → fail
    step_c = {"retries": 0, "max_retries": 3}
    decision_c = decide_next_action(
        validator_output={},
        execution_result=None,
        step=step_c,
        context={}
    )

    passed_c = decision_c == "fail"
    print(f"  7c: execution_result: None → decision: {decision_c} (expected: fail)")
    print(f"      [{'PASS' if passed_c else 'FAIL'}]")

    assert decision_c == "fail", f"Expected 'fail', got '{decision_c}'"


# ================================================================
# FAILURE INJECTION — Regression Detection
# ================================================================
def test_regression_validator_cannot_force_retry():
    """REGRESSION: If validator could force retry on success, this MUST fail."""
    print("\n" + "=" * 60)
    print("  REGRESSION — Validator Cannot Force Retry")
    print("=" * 60)

    er = {"status": "success", "result": 5}
    vo = {"decision": "retry", "reason": "forced_retry_attempt"}
    step = {"retries": 0, "max_retries": 3}

    decision = decide_next_action(
        validator_output=vo,
        execution_result=er,
        step=step,
        context={}
    )

    # This MUST be complete. If it's retry, the architecture is broken.
    assert decision != "retry", "CRITICAL REGRESSION: Validator forced retry on successful execution!"
    assert decision == "complete", f"Expected 'complete', got '{decision}'"
    print(f"  decision: {decision}")
    print(f"  [PASS] Validator cannot force retry")


def test_regression_mismatch_cannot_force_retry():
    """REGRESSION: If mismatch could force retry on success, this MUST fail."""
    print("\n" + "=" * 60)
    print("  REGRESSION — Mismatch Cannot Force Retry")
    print("=" * 60)

    er = {"status": "success", "result": 16}
    vo = {}
    step = {
        "retries": 0,
        "max_retries": 3,
        "mismatch": True,
        "execution_result": {"status": "success", "result": 16},
        "output": "16"
    }

    decision = decide_next_action(
        validator_output=vo,
        execution_result=er,
        step=step,
        context={}
    )

    assert decision != "retry", "CRITICAL REGRESSION: Mismatch forced retry on successful execution!"
    assert decision == "complete", f"Expected 'complete', got '{decision}'"
    print(f"  decision: {decision}")
    print(f"  [PASS] Mismatch cannot force retry")
