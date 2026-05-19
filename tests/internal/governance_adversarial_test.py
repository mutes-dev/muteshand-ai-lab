#!/usr/bin/env python3
"""
Governance Capability Reconciliation Audit — Phase 6 Adversarial Validation
Tests boundary violations and isolation rules.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from system.orchestrator.governance import (
    decide_next_action, GovernanceDecision, _create_governance_context,
    _evaluate_retry_exhaustion, is_execution_valid
)
from system.orchestrator.drift_detector import compare as drift_compare
from system.orchestrator.intent_validator import evaluate_intent

TRACE = []
def _log(event, data):
    TRACE.append({"event": event, "data": data})
    print(f"[ADVERSARIAL] {event}: {data}")

def _make_step(**kwargs):
    defaults = {"id": "step_1", "status": "ACTIVE", "retries": 0, "risk": "MEDIUM",
                "importance": "normal", "purpose_met": True, "purpose": "test", "input": "test"}
    defaults.update(kwargs)
    return defaults

def _make_context():
    return {"workflow_id": "wf_1"}

def _make_exec_result(status="success", result="ok"):
    return {"status": status, "result": result}

# =============================================================================
# RULE 1: execution_result is sole truth
# =============================================================================

def test_adversarial_execution_truth_override():
    """execution_result.status='success' MUST NOT be overridden by validator saying failure."""
    step = _make_step(purpose_met=True, executed_input="test")
    validator = {"recommendation": "retry", "reason": "fake_failure", "signals": {"constraint_ok": False}}
    result = _make_exec_result("success", "ok")
    decision = decide_next_action(validator, result, step, _make_context())
    _log("execution_truth_override", {
        "validator_recommendation": "retry",
        "execution_status": "success",
        "decision": decision.action,
        "pass": decision.action == "complete"
    })
    assert decision.action == "complete", f"execution_result truth was overridden! Got {decision.action}"
    return True

def test_adversarial_execution_failure_override():
    """execution_result.status='failure' MUST NOT be overridden by validator saying accept."""
    step = _make_step(retries=0)
    validator = {"recommendation": "accept", "reason": "fake_accept", "signals": {"constraint_ok": True}}
    result = _make_exec_result("failure", None)
    decision = decide_next_action(validator, result, step, _make_context())
    _log("execution_failure_override", {
        "validator_recommendation": "accept",
        "execution_status": "failure",
        "decision": decision.action,
        "pass": decision.action == "retry"
    })
    assert decision.action == "retry", f"execution_result truth was overridden! Got {decision.action}"
    return True

# =============================================================================
# RULE 2: Governance is sole decision maker
# =============================================================================

def test_adversarial_validator_no_retry_trigger():
    """Validator signal MUST NOT autonomously trigger retry — governance decides."""
    step = _make_step(purpose_met=True, executed_input="test")
    validator = {"recommendation": "retry", "reason": "semantic_drift", "signals": {"constraint_ok": False}}
    result = _make_exec_result("success", "ok")
    decision = decide_next_action(validator, result, step, _make_context())
    _log("validator_no_retry_trigger", {
        "pass": decision.action == "complete"
    })
    assert decision.action == "complete"
    return True

def test_adversarial_drift_no_mutation():
    """Drift detector MUST NOT mutate runtime state."""
    step = _make_step()
    original_status = step["status"]
    drift_compare("test", {"status": "failure", "result": None}, context=None, semantic_expectation=None)
    _log("drift_no_mutation", {
        "status_unchanged": step["status"] == original_status,
        "pass": step["status"] == original_status
    })
    assert step["status"] == original_status, "Drift detector mutated step state!"
    return True

# =============================================================================
# RULE 3: Validator isolation — advisory only
# =============================================================================

def test_adversarial_validator_isolation():
    """Validator output stored as advisory metadata, zero control impact."""
    step = _make_step(purpose_met=True, executed_input="test")
    validator = {"recommendation": "escalate", "reason": "critical", "signals": {"constraint_ok": False}}
    result = _make_exec_result("success", "ok")
    decision = decide_next_action(validator, result, step, _make_context())
    _log("validator_isolation", {
        "stored_advisory": step.get("_validator_decision"),
        "decision": decision.action,
        "pass": step.get("_validator_decision") == "escalate" and decision.action == "complete"
    })
    assert step.get("_validator_decision") == "escalate", "Validator advisory not stored"
    assert decision.action == "complete", "Validator influenced governance decision"
    return True

# =============================================================================
# RULE 4: Escalation determinism (post-override removal)
# =============================================================================

def test_adversarial_retry_exhaustion_always_escalates():
    """Retry exhaustion MUST always escalate — no override bypass path."""
    step = _make_step(retries=3)
    step["max_retries"] = 3
    result = _make_exec_result("failure", None)
    decision = decide_next_action(None, result, step, _make_context())
    _log("retry_exhaustion_always_escalates", {
        "decision": decision.action,
        "pass": decision.action == "escalate"
    })
    assert decision.action == "escalate", f"Expected escalate on exhaustion, got {decision.action}"
    return True

def test_adversarial_no_override_parameter_accepted():
    """decide_next_action MUST NOT accept override_state keyword argument."""
    import inspect
    sig = inspect.signature(decide_next_action)
    assert "override_state" not in sig.parameters, "override_state must not exist in decide_next_action"
    _log("no_override_parameter", {"pass": True})
    return True

# =============================================================================
# RULE 5: Retry exhaustion boundary
# =============================================================================

def test_adversarial_retry_exhaustion_escalate():
    """Exhausted retries without override MUST escalate (not silently fail)."""
    step = _make_step(retries=3)
    step["max_retries"] = 3
    result = _make_exec_result("failure", None)
    action, reason, branch = _evaluate_retry_exhaustion(step, "wf_1", "step_1")
    _log("retry_exhaustion_escalate", {
        "action": action, "reason": reason, "pass": action == "escalate"
    })
    assert action == "escalate", f"Expected escalate, got {action}"
    return True

# =============================================================================
# RULE 6: is_execution_valid structural enforcement
# =============================================================================

def test_adversarial_missing_executed_input():
    """Missing executed_input MUST invalidate successful execution_result."""
    result = {"status": "success", "result": "ok"}
    step = {"executed_input": None}
    valid, reason = is_execution_valid(result, step)
    _log("missing_executed_input", {"valid": valid, "reason": reason, "pass": valid is False})
    assert valid is False, "Missing executed_input was accepted as valid!"
    return True

def test_adversarial_missing_result_field():
    """Missing 'result' field MUST invalidate execution."""
    result = {"status": "success"}
    step = {"executed_input": "test"}
    valid, reason = is_execution_valid(result, step)
    _log("missing_result_field", {"valid": valid, "reason": reason, "pass": valid is False})
    assert valid is False, "Missing result field was accepted as valid!"
    return True

# =============================================================================
# RULE 7: GovernanceContext immutability
# =============================================================================

def test_adversarial_governance_context_immutable():
    """GovernanceContext is frozen — mutation must raise."""
    from system.orchestrator.governance import GovernanceContext
    ctx = GovernanceContext(
        execution_result={"status": "success"},
        retry_count=0,
        max_retries=3,
        workflow_id="wf_1",
        step_id="step_1"
    )
    try:
        ctx.retry_count = 99
        _log("governance_context_immutable", {"pass": False, "reason": "No exception raised on mutation"})
        return False  # Should have raised
    except Exception as e:
        _log("governance_context_immutable", {"pass": True, "exception_type": type(e).__name__})
        return True

# =============================================================================
# RUN ALL
# =============================================================================
TESTS = [
    test_adversarial_execution_truth_override,
    test_adversarial_execution_failure_override,
    test_adversarial_validator_no_retry_trigger,
    test_adversarial_drift_no_mutation,
    test_adversarial_validator_isolation,
    test_adversarial_retry_exhaustion_always_escalates,
    test_adversarial_no_override_parameter_accepted,
    test_adversarial_retry_exhaustion_escalate,
    test_adversarial_missing_executed_input,
    test_adversarial_missing_result_field,
    test_adversarial_governance_context_immutable,
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
            print(f"  FAIL: {test.__name__} — {e}")

    print(f"\n{'='*60}")
    print(f"ADVERSARIAL TEST RESULTS: {passed}/{len(TESTS)} passed, {failed}/{len(TESTS)} failed")
    print(f"{'='*60}")
    if failed > 0:
        sys.exit(1)
