"""
Planner + Intent Validator — Observational Tests

OBSERVATIONAL ONLY.
- NO simulation
- NO mocked outputs
- NO enforcement of validation logic
- Captures real outputs from plan_workflow() and evaluate_intent()
- evaluate_intent signature: (user_input, tool_name, args, output_text, step_purpose)
"""

import pytest
from system.orchestrator.orchestrator_planner import plan_workflow
from system.orchestrator.intent_validator import evaluate_intent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_steps(planner_result: dict):
    """Extract steps list from planner result without assuming structure."""
    if isinstance(planner_result.get("workflow"), dict):
        return planner_result["workflow"].get("steps") or []
    return planner_result.get("steps") or []


def _safe_validator_call(user_input, steps):
    """
    Call evaluate_intent with minimal safe defaults derived from planner output.
    Does NOT assume tool name or args — passes None/empty when unknown.
    """
    purpose = None
    if steps:
        first_step = steps[0]
        if isinstance(first_step, dict):
            purpose = first_step.get("purpose") or first_step.get("name")
        elif isinstance(first_step, str):
            purpose = first_step

    return evaluate_intent(
        user_input,   # user_input
        None,         # tool_name — not known at planner level
        [],           # args — not known at planner level
        purpose,      # output_text — use step purpose as proxy output
        purpose       # step_purpose
    )


# ===========================================================================
# TEST 1 — PLANNER + VALIDATOR OBSERVATION
# ===========================================================================

def test_planner_validator_observation():
    """
    Observational: run planner then intent_validator, print combined signal.
    """
    user_input = "add 2 and 3"

    planner_result = plan_workflow(user_input)
    steps = _extract_steps(planner_result)
    validator_result = _safe_validator_call(user_input, steps)

    print({
        "input": user_input,
        "planner_status": planner_result.get("status"),
        "step_count": len(steps) if steps else 0,
        "validator_output": validator_result
    })

    assert isinstance(planner_result, dict)
    assert "status" in planner_result
    assert isinstance(validator_result, dict)


# ===========================================================================
# TEST 2 — MULTI-RUN SIGNAL STABILITY
# ===========================================================================

def test_multi_run_signal_stability():
    """
    Observational: run planner + validator 3 times, print per-run signal.
    DO NOT compare outputs between runs.
    """
    user_input = "add 2 and 3"

    for i in range(3):
        planner_result = plan_workflow(user_input)
        steps = _extract_steps(planner_result)
        validator_result = _safe_validator_call(user_input, steps)

        print({
            "run": i,
            "steps": len(steps),
            "validator": validator_result
        })

        assert isinstance(planner_result, dict)
        assert isinstance(validator_result, dict)


# ===========================================================================
# TEST 3 — EDGE CASES
# ===========================================================================

@pytest.mark.parametrize("edge_input", [
    "",
    "???",
    "delete all files",
])
def test_edge_cases(edge_input):
    """
    Observational: run planner + validator on edge inputs, print both outputs.
    Planner must not crash. Validator must not crash.
    """
    planner_result = None
    validator_result = None

    try:
        planner_result = plan_workflow(edge_input)
    except Exception as exc:
        pytest.fail(f"Planner raised exception on {edge_input!r}: {repr(exc)}")

    steps = _extract_steps(planner_result)

    try:
        validator_result = _safe_validator_call(edge_input, steps)
    except Exception as exc:
        pytest.fail(f"Validator raised exception on {edge_input!r}: {repr(exc)}")

    print(f"EDGE INPUT={edge_input!r}")
    print("  planner_result:", planner_result)
    print("  validator_output:", validator_result)

    assert isinstance(planner_result, dict)
    assert isinstance(validator_result, dict)


# ===========================================================================
# TEST 4 — FAILURE INTERACTION
# ===========================================================================

def test_failure_interaction():
    """
    Observational: if planner returns failure, still run validator.
    Print both outputs regardless of outcome.
    DO NOT force failure.
    """
    user_input = None  # Most likely to produce failure without exception

    try:
        planner_result = plan_workflow(user_input)
    except Exception as exc:
        print("PLANNER EXCEPTION:", repr(exc))
        pytest.skip(f"Planner raised exception on None input: {repr(exc)}")

    steps = _extract_steps(planner_result)

    try:
        validator_result = _safe_validator_call(user_input, steps)
    except Exception as exc:
        validator_result = {"error": repr(exc)}

    print("FAILURE INTERACTION — planner_result:", planner_result)
    print("FAILURE INTERACTION — validator_result:", validator_result)

    assert isinstance(planner_result, dict)


# ===========================================================================
# TEST 5 — SIGNAL CONSISTENCY
# ===========================================================================

@pytest.mark.parametrize("test_input", [
    "add 2 and 3",
    "???",
    "delete all files",
])
def test_signal_consistency(test_input):
    """
    Observational: validate only that validator returns a dict and does not crash.
    NO schema enforcement.
    """
    try:
        planner_result = plan_workflow(test_input)
    except Exception as exc:
        pytest.fail(f"Planner crashed on {test_input!r}: {repr(exc)}")

    steps = _extract_steps(planner_result)

    try:
        validator_result = _safe_validator_call(test_input, steps)
    except Exception as exc:
        pytest.fail(f"Validator crashed on {test_input!r}: {repr(exc)}")

    assert isinstance(validator_result, dict), (
        f"Validator output must be dict, got {type(validator_result)} for input {test_input!r}"
    )
