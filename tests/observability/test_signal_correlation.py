"""
CATEGORY: OBSERVABILITY
AUTHORITY_LAYER: Observability Validation
VALIDATES:
  - Signal correlation
  - Planner + Tool Observer + Validator
  - Observer signal reconstruction
  - No execution path changes
ENTRYPOINT: run_workflow
DIRECT_INTERNAL_CALLS:
  - orchestrator_planner internals
  - orchestrator_runtime internals
  - intent_validator internals
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: OBSERVABILITY_VALIDATION
ARCHITECTURAL_SCOPE: Signal correlation

---

Signal Correlation — Planner + Tool Observer + Validator

OBSERVATIONAL ONLY.
- NO simulation
- NO mocked outputs
- NO control logic
- NO execution path changes
- Captures real signals from plan_workflow(), observe_tool_call(), evaluate_intent()

Observer signal is reconstructed from the step purpose string (the input the LLM
agent receives) without modifying any execution path.
"""

import pytest
from system.orchestrator.orchestrator_planner import plan_workflow
from system.orchestrator.orchestrator_runtime import observe_tool_call
from system.orchestrator.intent_validator import evaluate_intent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_steps(planner_result: dict) -> list:
    """Extract steps list from planner result without assuming structure."""
    if isinstance(planner_result.get("workflow"), dict):
        return planner_result["workflow"].get("steps") or []
    return planner_result.get("steps") or []


def _get_step_purpose(steps: list):
    """Return first step purpose string, or None."""
    if not steps:
        return None
    first = steps[0]
    if isinstance(first, dict):
        return first.get("purpose") or first.get("name")
    if isinstance(first, str):
        return first
    return None


def _safe_observer(steps: list) -> dict:
    """
    Call observe_tool_call using the first step purpose as the observed string.
    This is the string the LLM agent receives — structurally inspected without
    modifying any execution path.
    """
    purpose = _get_step_purpose(steps)
    return observe_tool_call(purpose)


def _safe_validator(user_input, steps: list) -> dict:
    """
    Call evaluate_intent with minimal safe defaults derived from planner output.
    tool_name and args are None/[] — not known at planner level.
    """
    purpose = _get_step_purpose(steps)
    return evaluate_intent(
        user_input,
        None,
        [],
        purpose,
        purpose
    )


def classify_alignment(observer: dict, validator: dict) -> str:
    if observer["issue_count"] == 0 and validator["decision"] == "accept":
        return "aligned"
    elif observer["issue_count"] > 0:
        return "observer_flagged"
    elif validator["decision"] != "accept":
        return "validator_flagged"
    else:
        return "unknown"


# ===========================================================================
# TEST 1 — BASIC ALIGNMENT
# ===========================================================================

def test_basic_alignment():
    """
    Observational: capture planner, observer, validator signals for one input.
    Prints combined signal dict.
    """
    user_input = "add 2 and 3"

    planner_result = plan_workflow(user_input)
    steps = _extract_steps(planner_result)
    observer_result = _safe_observer(steps)
    validator_result = _safe_validator(user_input, steps)

    print({
        "input": user_input,
        "planner": planner_result,
        "tool_observer": observer_result,
        "validator": validator_result,
        "alignment": "TBD"
    })

    assert isinstance(planner_result, dict)
    assert isinstance(observer_result, dict)
    assert isinstance(validator_result, dict)


# ===========================================================================
# TEST 2 — MULTI-RUN CORRELATION
# ===========================================================================

def test_multi_run_correlation():
    """
    Observational: run 3 times, print per-run signal correlation.
    DO NOT compare outputs between runs.
    """
    user_input = "add 2 and 3"

    for i in range(3):
        planner_result = plan_workflow(user_input)
        steps = _extract_steps(planner_result)
        step_count = len(steps)
        observer_result = _safe_observer(steps)
        validator_result = _safe_validator(user_input, steps)

        print({
            "run": i,
            "steps": step_count,
            "issues": observer_result["issue_count"],
            "validator": validator_result["decision"]
        })

        assert isinstance(planner_result, dict)
        assert isinstance(observer_result, dict)
        assert isinstance(validator_result, dict)


# ===========================================================================
# TEST 3 — EDGE INPUTS
# ===========================================================================

@pytest.mark.parametrize("edge_input", [
    "",
    "???",
    "delete all files",
])
def test_edge_inputs(edge_input):
    """
    Observational: capture all three signals for edge inputs, print each.
    """
    planner_result = None
    observer_result = None
    validator_result = None

    try:
        planner_result = plan_workflow(edge_input)
    except Exception as exc:
        pytest.fail(f"Planner crashed on {edge_input!r}: {repr(exc)}")

    steps = _extract_steps(planner_result)

    try:
        observer_result = _safe_observer(steps)
    except Exception as exc:
        pytest.fail(f"Observer crashed on {edge_input!r}: {repr(exc)}")

    try:
        validator_result = _safe_validator(edge_input, steps)
    except Exception as exc:
        pytest.fail(f"Validator crashed on {edge_input!r}: {repr(exc)}")

    print(f"\nEDGE INPUT={edge_input!r}")
    print("  planner_result:", planner_result)
    print("  observer_result:", observer_result)
    print("  validator_result:", validator_result)

    assert isinstance(planner_result, dict)
    assert isinstance(observer_result, dict)
    assert isinstance(validator_result, dict)


# ===========================================================================
# TEST 4 — SIGNAL RELATION (SOFT CLASSIFICATION)
# ===========================================================================

@pytest.mark.parametrize("test_input", [
    "add 2 and 3",
    "???",
    "delete all files",
    "",
])
def test_signal_relation(test_input):
    """
    Observational: classify signal alignment for each input.
    classify_alignment is used for logging ONLY — no branching on result.
    """
    try:
        planner_result = plan_workflow(test_input)
    except Exception as exc:
        pytest.fail(f"Planner crashed on {test_input!r}: {repr(exc)}")

    steps = _extract_steps(planner_result)

    try:
        observer_result = _safe_observer(steps)
    except Exception as exc:
        pytest.fail(f"Observer crashed on {test_input!r}: {repr(exc)}")

    try:
        validator_result = _safe_validator(test_input, steps)
    except Exception as exc:
        pytest.fail(f"Validator crashed on {test_input!r}: {repr(exc)}")

    alignment = classify_alignment(observer_result, validator_result)

    print({
        "input": test_input,
        "observer_issues": observer_result["issue_count"],
        "validator_decision": validator_result["decision"],
        "alignment": alignment
    })

    assert isinstance(planner_result, dict)
    assert isinstance(observer_result, dict)
    assert isinstance(validator_result, dict)


# ===========================================================================
# TEST 5 — CONSISTENCY CHECK
# ===========================================================================

@pytest.mark.parametrize("test_input", [
    "add 2 and 3",
    "???",
    "delete all files",
    "",
])
def test_consistency_check(test_input):
    """
    Observational: validate only that all three signals return dicts without crashing.
    NO schema enforcement.
    """
    try:
        planner_result = plan_workflow(test_input)
    except Exception as exc:
        pytest.fail(f"Planner crashed on {test_input!r}: {repr(exc)}")

    steps = _extract_steps(planner_result)

    try:
        observer_result = _safe_observer(steps)
    except Exception as exc:
        pytest.fail(f"Observer crashed on {test_input!r}: {repr(exc)}")

    try:
        validator_result = _safe_validator(test_input, steps)
    except Exception as exc:
        pytest.fail(f"Validator crashed on {test_input!r}: {repr(exc)}")

    assert isinstance(planner_result, dict), (
        f"planner_result must be dict, got {type(planner_result)} for {test_input!r}"
    )
    assert isinstance(observer_result, dict), (
        f"observer_result must be dict, got {type(observer_result)} for {test_input!r}"
    )
    assert isinstance(validator_result, dict), (
        f"validator_result must be dict, got {type(validator_result)} for {test_input!r}"
    )
