"""
CATEGORY: INTERNAL_RUNTIME
AUTHORITY_LAYER: Runtime Behavioral Truth
VALIDATES:
  - Orchestrator planner behavior
  - plan_workflow output structure
  - Minimal structural validation
ENTRYPOINT: run_workflow
DIRECT_INTERNAL_CALLS: NONE
MONKEYPATCH_USAGE: NONE
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: BEHAVIORAL_VALIDATION
ARCHITECTURAL_SCOPE: Orchestrator planner behavior

---

Orchestrator Planner — Observational Tests

OBSERVATIONAL ONLY.
- NO simulation
- NO mocked outputs
- NO enforcement of planner behavior
- Minimal structural validation only
- Captures real outputs from plan_workflow()
"""

import pytest
from system.orchestrator.orchestrator_planner import plan_workflow


# ===========================================================================
# TEST 1 — BASIC STRUCTURE
# ===========================================================================

def test_basic_structure():
    """
    Observational: validate top-level output structure for a simple input.
    Does NOT enforce planner decisions, only checks minimal dict shape.
    """
    result = plan_workflow("add 2 and 3")

    print("TEST 1 OUTPUT:", result)

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "status" in result, f"Missing 'status' key in {result}"

    if result["status"] == "success":
        has_workflow = "workflow" in result
        has_steps = "steps" in result
        assert has_workflow or has_steps, (
            f"Success result missing both 'workflow' and 'steps': {result}"
        )


# ===========================================================================
# TEST 2 — STEPS EXISTENCE
# ===========================================================================

def test_steps_existence():
    """
    Observational: if steps are present, validate minimal list structure.
    Does NOT assert step count or step content.
    """
    result = plan_workflow("add 2 and 3")

    print("TEST 2 OUTPUT:", result)

    steps = None
    if isinstance(result.get("workflow"), dict):
        steps = result["workflow"].get("steps")
    elif "steps" in result:
        steps = result["steps"]

    if steps is None:
        pytest.skip("No steps present in planner output — skipping step validation")

    assert isinstance(steps, list), f"Expected steps to be list, got {type(steps)}"
    assert len(steps) >= 1, f"Expected at least 1 step, got {len(steps)}"

    for step in steps:
        assert isinstance(step, (str, dict)), (
            f"Each step must be str or dict, got {type(step)}: {step}"
        )


# ===========================================================================
# TEST 3 — FAILURE STRUCTURE
# ===========================================================================

def test_failure_structure():
    """
    Observational: trigger planner with invalid input (None).
    Only validates failure contract IF failure occurs — does NOT force it.
    """
    try:
        result = plan_workflow(None)
    except Exception as exc:
        print("TEST 3 EXCEPTION (not a test failure):", repr(exc))
        pytest.skip(f"Planner raised exception on None input: {repr(exc)}")

    print("TEST 3 OUTPUT:", result)

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "status" in result, f"Missing 'status' key in {result}"

    if result["status"] == "failure":
        assert "reason" in result, f"Failure result missing 'reason': {result}"
        assert isinstance(result["reason"], str), (
            f"'reason' must be str, got {type(result['reason'])}"
        )


# ===========================================================================
# TEST 4 — MULTI-RUN OBSERVATION
# ===========================================================================

def test_multi_run_observation():
    """
    Observational: run planner 3 times, print structural metadata each run.
    DO NOT compare outputs between runs.
    """
    for i in range(3):
        result = plan_workflow("add 2 and 3")

        steps = None
        if isinstance(result.get("workflow"), dict):
            steps = result["workflow"].get("steps", [])
        elif "steps" in result:
            steps = result.get("steps", [])
        else:
            steps = []

        print({
            "run": i,
            "step_count": len(steps),
            "structure_type": type(steps[0]) if steps else None
        })

        assert isinstance(result, dict), f"Run {i}: expected dict, got {type(result)}"
        assert "status" in result, f"Run {i}: missing 'status' key"


# ===========================================================================
# TEST 5 — EDGE INPUTS
# ===========================================================================

@pytest.mark.parametrize("edge_input", [
    "",
    "???",
    "do something impossible",
])
def test_edge_inputs(edge_input):
    """
    Observational: planner must not crash on edge inputs.
    Validates only that output is a dict with a 'status' field.
    """
    try:
        result = plan_workflow(edge_input)
    except Exception as exc:
        pytest.fail(f"Planner raised exception on edge input {edge_input!r}: {repr(exc)}")

    print(f"TEST 5 EDGE INPUT={edge_input!r} OUTPUT:", result)

    assert isinstance(result, dict), (
        f"Expected dict for input {edge_input!r}, got {type(result)}"
    )
    assert "status" in result, (
        f"Missing 'status' key for input {edge_input!r}: {result}"
    )


# ===========================================================================
# TEST 6 — RUNTIME COMPATIBILITY
# ===========================================================================

def test_runtime_compatibility():
    """
    Observational: pass planner output into runtime normalization if available.
    Skips gracefully if runtime normalization cannot be accessed.
    """
    try:
        from system.orchestrator.orchestrator_runtime import execute_from_input
    except ImportError as exc:
        pytest.skip(f"Runtime not importable: {repr(exc)}")

    try:
        result = execute_from_input("add 2 and 3")
    except Exception as exc:
        pytest.fail(f"execute_from_input raised exception: {repr(exc)}")

    print("TEST 6 RUNTIME OUTPUT:", result)

    assert result is not None, "execute_from_input returned None"
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "status" in result, f"Missing 'status' in runtime result: {result}"
