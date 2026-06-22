"""
Sprint 9B — Formatter / Validator workflow_id Linkage Tests

Validates:
- formatter LLM usage ledger entry includes workflow_id
- validator LLM usage ledger entry includes workflow_id
- formatter behavior/output remains unchanged
- validator behavior/output remains unchanged
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import patch, MagicMock


class TestFormatterWorkflowLinkage:
    def test_format_tool_output_passes_workflow_id_to_execute_llm(self):
        from system.orchestrator.agent_executor import _format_tool_output

        with patch("system.orchestrator.agent_executor.execute_llm") as mock_execute_llm:
            with patch("system.orchestrator.agent_executor.get_llm") as mock_get_llm:
                mock_get_llm.return_value = {
                    "status": "success",
                    "provider": {"name": "ollama", "model": "llama3.1:8b", "callable": lambda x: x},
                }
                mock_execute_llm.return_value = {
                    "status": "success",
                    "result": "Formatted result",
                }

                result = _format_tool_output("add 1 and 2", "3", workflow_id="wf_formatter_test")

                assert result == "Formatted result"
                assert mock_execute_llm.called
                _, kwargs = mock_execute_llm.call_args
                assert kwargs.get("workflow_id") == "wf_formatter_test"

    def test_format_tool_output_default_workflow_id_none(self):
        from system.orchestrator.agent_executor import _format_tool_output

        with patch("system.orchestrator.agent_executor.execute_llm") as mock_execute_llm:
            with patch("system.orchestrator.agent_executor.get_llm") as mock_get_llm:
                mock_get_llm.return_value = {
                    "status": "success",
                    "provider": {"name": "ollama", "model": "llama3.1:8b", "callable": lambda x: x},
                }
                mock_execute_llm.return_value = {
                    "status": "success",
                    "result": "Formatted result",
                }

                result = _format_tool_output("add 1 and 2", "3")

                assert result == "Formatted result"
                _, kwargs = mock_execute_llm.call_args
                assert kwargs.get("workflow_id") is None

    def test_format_tool_output_fallback_unchanged(self):
        from system.orchestrator.agent_executor import _format_tool_output

        with patch("system.orchestrator.agent_executor.get_llm") as mock_get_llm:
            mock_get_llm.return_value = {"status": "failure", "reason": "unavailable"}

            result = _format_tool_output("add 1 and 2", "3")

            assert result == "3"


class TestValidatorWorkflowLinkage:
    def test_extract_constraints_llm_passes_workflow_id_to_execute_llm(self):
        from system.orchestrator.intent_validator import _extract_constraints_llm

        with patch("system.orchestrator.intent_validator.execute_llm") as mock_execute_llm:
            with patch("system.orchestrator.intent_validator.get_llm") as mock_get_llm:
                mock_get_llm.return_value = {
                    "status": "success",
                    "provider": {"name": "ollama", "model": "llama3.1:8b", "callable": lambda x: x},
                }
                mock_execute_llm.return_value = {
                    "status": "success",
                    "result": "{}",
                }

                result = _extract_constraints_llm("add 1 and 2", workflow_id="wf_validator_test")

                assert result == {}
                assert mock_execute_llm.called
                _, kwargs = mock_execute_llm.call_args
                assert kwargs.get("workflow_id") == "wf_validator_test"

    def test_extract_constraints_llm_default_workflow_id_none(self):
        from system.orchestrator.intent_validator import _extract_constraints_llm

        with patch("system.orchestrator.intent_validator.execute_llm") as mock_execute_llm:
            with patch("system.orchestrator.intent_validator.get_llm") as mock_get_llm:
                mock_get_llm.return_value = {
                    "status": "success",
                    "provider": {"name": "ollama", "model": "llama3.1:8b", "callable": lambda x: x},
                }
                mock_execute_llm.return_value = {
                    "status": "success",
                    "result": "{}",
                }

                result = _extract_constraints_llm("add 1 and 2")

                assert result == {}
                _, kwargs = mock_execute_llm.call_args
                assert kwargs.get("workflow_id") is None

    def test_evaluate_intent_passes_workflow_id(self):
        from system.orchestrator.intent_validator import evaluate_intent

        with patch("system.orchestrator.intent_validator.execute_llm") as mock_execute_llm:
            with patch("system.orchestrator.intent_validator.get_llm") as mock_get_llm:
                mock_get_llm.return_value = {
                    "status": "success",
                    "provider": {"name": "ollama", "model": "llama3.1:8b", "callable": lambda x: x},
                }
                mock_execute_llm.return_value = {
                    "status": "success",
                    "result": "{}",
                }

                result = evaluate_intent(
                    user_input="add 1 and 2",
                    tool_name="add_numbers",
                    args=["1", "2"],
                    output_text="3",
                    step_purpose="add 1 and 2",
                    workflow_id="wf_eval_test",
                )

                assert result.get("recommendation") == "accept"
                assert mock_execute_llm.called
                _, kwargs = mock_execute_llm.call_args
                assert kwargs.get("workflow_id") == "wf_eval_test"
