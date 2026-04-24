"""
Deterministic Orchestrator Failure Test — Controlled Injection

Uses pytest monkeypatch to inject a forced failure without LLM dependency.

Target: system.orchestrator.orchestrator_runtime.execute_from_input (SOURCE)
Injection: Always returns {"status": "failure", "reason": "forced failure"}
Isolation: pytest monkeypatch fixture (automatic cleanup)
"""

import pytest


def mock_execute_from_input(input_str):
    """Mock that always returns a controlled failure."""
    return {
        "status": "failure",
        "reason": "forced failure"
    }


@pytest.fixture(autouse=True)
def patch_execute_from_input(monkeypatch):
    """
    Pytest fixture that patches the SOURCE function.
    
    The harness imports execute_from_input from orchestrator_runtime.
    By patching the source module, the harness's reference is affected.
    
    Scope: Function-level (default)
    Cleanup: Automatic (monkeypatch restores after each test)
    Leakage: None (isolated to this test file only)
    """
    monkeypatch.setattr(
        "system.orchestrator.orchestrator_runtime.execute_from_input",
        mock_execute_from_input
    )


TEST_CASES = [
    {
        "name": "orchestrator_forced_failure",
        "type": "orchestrator",
        "input": "add 2 and 3",
        "expected": {
            "status": "failure",
            "reason": "forced failure"
        }
    }
]
