"""
System Guarantees — Strict Contract Enforcement

Tests enforce EXACT system behavior.
NO flexibility. NO interpretation.
"""

from system.entry.system_entry import system_entry


# Explicitly declare no harness TEST_CASES (pytest only)
TEST_CASES = []


def test_safe_mode_add():
    """
    Safe mode: Valid addition through full pipeline.
    """
    result = system_entry("add 2 and 3")
    assert result == {
        "status": "success",
        "result": 5
    }


def test_unknown_tool():
    """
    Unknown tool: Planner fail-fast.
    """
    result = system_entry("do something")
    assert result == {
        "status": "failure",
        "reason": "unknown_tool"
    }


def test_validation_failure():
    """
    Validation failure: Insufficient arguments.
    """
    result = system_entry("add 2")
    assert result["status"] == "failure"


def test_execution_failure():
    """
    Execution failure: Crash tool handled safely.
    """
    result = system_entry("crash 1 and 2")
    assert result["status"] == "failure"


def test_llm_invalid():
    """
    Invalid LLM output: Strict planner enforces exact/phrase match only.
    Garbage prefix causes unknown_tool failure - no substring fallback.
    """
    result = system_entry("__TEST_INVALID_JSON__ add 2 and 3")
    assert result == {
        "status": "failure",
        "reason": "unknown_tool"
    }


def test_multistep_success():
    """
    Multi-step success: Chained operations.
    """
    result = system_entry("add 2 and 3 then multiply 4 and 5")
    assert result == {
        "status": "success",
        "result": 20
    }
