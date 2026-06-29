"""
CATEGORY: HARNESS_CONTRACT
AUTHORITY_LAYER: External Observable Truth
VALIDATES:
  - Source-grounded deterministic finalize_output must not be flagged as error
  - Real finalize_output error wrappers still fail
  - Actual system_entry parse failures still fail
ENTRYPOINT: system_entry, execute_step, evaluate_intent
DIRECT_INTERNAL_CALLS:
  - system.orchestrator.step_executor.execute_step
  - system.orchestrator.intent_validator.evaluate_intent
  - system.entry.system_entry
MOCKING_POLICY: REAL_EXECUTION
TEST_INTENT: REGRESSION
ARCHITECTURAL_SCOPE: AGENT-001G-FIX2
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from system.entry.system_entry import system_entry
from system.orchestrator.intent_validator import evaluate_intent
from system.orchestrator.step_executor import execute_step


def _make_web_read_step_2(purpose):
    return {
        "id": "step_2",
        "type": "EXECUTE_API",
        "name": "Present webpage contents",
        "purpose": purpose,
        "input": purpose,
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "depends_on": ["step_1"],
        "capability_metadata": {
            "capability_id": "web_read",
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": "present",
            "intent_mode": "present",
        },
        "expected_outcome": "Result shown",
        "status": "PENDING",
        "retries": 0,
        "max_retries": 2,
    }


def _make_dependency_output(data):
    return {
        "step_1": {
            "status": "success",
            "data": data,
            "purpose": "Read the webpage at https://docs.python.org/3/tutorial/introduction.html",
            "selected_tool": "read_webpage",
            "resource_targets": ["https://docs.python.org/3/tutorial/introduction.html"],
        }
    }


def test_deterministic_finalize_output_exempt_error_word():
    source = "There was an error: trying to use it will give you an error:\n\nDone."
    step = _make_web_read_step_2("Present the webpage contents from step_1")
    workflow = {"id": "wf_test", "status": "ACTIVE", "steps": [step]}
    result = execute_step(step, workflow, dependency_outputs=_make_dependency_output(source))
    assert result["execution_result"]["status"] == "success"
    assert result["step_result"]["status"] == "success"
    assert result["step_result"].get("result", {}).get("output") == source
    print("[PASS] deterministic_finalize_output_exempt_error_word")


def test_deterministic_finalize_output_exempt_syntax_error():
    source = "This section describes a syntax error: invalid token."
    step = _make_web_read_step_2("Present the webpage contents from step_1")
    workflow = {"id": "wf_test", "status": "ACTIVE", "steps": [step]}
    result = execute_step(step, workflow, dependency_outputs=_make_dependency_output(source))
    assert result["execution_result"]["status"] == "success"
    assert result["step_result"].get("result", {}).get("output") == source
    print("[PASS] deterministic_finalize_output_exempt_syntax_error")


def test_python_docs_like_content_completes_step_2():
    source = (
        "3. An Informal Introduction to Python\n\n"
        "In the following examples, input and output are distinguished.\n\n"
        "You can use the Copy button.\n\n"
        "Note: trying to use it will give you an error:\n\n"
        "Traceback (most recent call last):\n"
        "  File \"<stdin>\", line 1, in <module>\n"
        "NameError: name 'n' is not defined\n\n"
        "Done."
    )
    step = _make_web_read_step_2("Present the webpage contents from step_1")
    workflow = {"id": "wf_test", "status": "ACTIVE", "steps": [step]}
    result = execute_step(step, workflow, dependency_outputs=_make_dependency_output(source))
    assert result["execution_result"]["status"] == "success"
    assert result["step_result"]["status"] == "success"
    assert result["step_result"].get("result", {}).get("output") == source
    print("[PASS] python_docs_like_content_completes_step_2")


def test_actual_system_entry_invalid_token_type_fails():
    result = system_entry('finalize_output "ok" bad')
    assert result["status"] == "failure"
    assert result["reason"] == "invalid_token_type"
    print("[PASS] actual_system_entry_invalid_token_type_fails")


def test_finalize_output_error_wrapper_still_fails():
    decision = evaluate_intent(
        user_input="Run this",
        tool_name="finalize_output",
        args=["execution error: tool failed"],
        output_text="execution error: tool failed",
        step_purpose="Run this",
        execution_result={"status": "success", "result": "execution error: tool failed"},
        executed_input='finalize_output "execution error: tool failed"',
        deterministic_synthesis=False,
    )
    assert decision["decision"] == "retry"
    assert decision["reason"] == "finalize_output_contains_error"
    print("[PASS] finalize_output_error_wrapper_still_fails")


def test_intent_validator_accepts_non_error_source():
    decision = evaluate_intent(
        user_input="Present or summarize the webpage contents from step_1",
        tool_name="finalize_output",
        args=["hello world"],
        output_text="hello world",
        step_purpose="Present or summarize the webpage contents from step_1",
        execution_result={"status": "success", "result": "hello world"},
        executed_input='finalize_output "hello world"',
        deterministic_synthesis=False,
    )
    assert decision["decision"] == "accept"
    print("[PASS] intent_validator_accepts_non_error_source")


if __name__ == "__main__":
    test_deterministic_finalize_output_exempt_error_word()
    test_deterministic_finalize_output_exempt_syntax_error()
    test_python_docs_like_content_completes_step_2()
    test_actual_system_entry_invalid_token_type_fails()
    test_finalize_output_error_wrapper_still_fails()
    test_intent_validator_accepts_non_error_source()
    print("All web_read false-error classification tests passed.")
