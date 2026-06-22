"""
Sprint 9B — AG1 / Tool-Selection Event Emission Tests

Validates:
- tool_selection_started event emitted with correct workflow_id and step_id
- tool_selected event emitted with selected tool metadata
- tool_selection_failed event emitted on failure paths
- event emission failure does not break tool selection
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import patch, MagicMock

from system.interface.event_bus import get_event_bus


class TestAG1EventEmission:
    def test_event_types_defined(self):
        from system.interface.event_emitter import (
            EVENT_TOOL_SELECTION_STARTED,
            EVENT_TOOL_SELECTED,
            EVENT_TOOL_SELECTION_FAILED,
        )
        assert EVENT_TOOL_SELECTION_STARTED == "tool_selection_started"
        assert EVENT_TOOL_SELECTED == "tool_selected"
        assert EVENT_TOOL_SELECTION_FAILED == "tool_selection_failed"

    def test_emit_tool_selection_started_publishes_event(self):
        from system.interface.event_emitter import emit_tool_selection_started
        bus = get_event_bus()
        bus.clear_workflow("test_wf_ag1")
        emit_tool_selection_started("test_wf_ag1", "step_1", input_data="add 1 and 2")
        events = bus.get_events("test_wf_ag1")
        assert len(events) == 1
        assert events[0]["event_type"] == "tool_selection_started"
        assert events[0]["data"]["step_id"] == "step_1"
        bus.clear_workflow("test_wf_ag1")

    def test_emit_tool_selected_publishes_event(self):
        from system.interface.event_emitter import emit_tool_selected
        bus = get_event_bus()
        bus.clear_workflow("test_wf_ag1")
        emit_tool_selected("test_wf_ag1", "step_1", "add_numbers", provider="ollama", model="llama3.1:8b")
        events = bus.get_events("test_wf_ag1")
        assert len(events) == 1
        assert events[0]["event_type"] == "tool_selected"
        assert events[0]["data"]["selected_tool"] == "add_numbers"
        assert events[0]["data"]["provider"] == "ollama"
        bus.clear_workflow("test_wf_ag1")

    def test_emit_tool_selection_failed_publishes_event(self):
        from system.interface.event_emitter import emit_tool_selection_failed
        bus = get_event_bus()
        bus.clear_workflow("test_wf_ag1")
        emit_tool_selection_failed("test_wf_ag1", "step_1", "multiple_tool_calls_not_allowed")
        events = bus.get_events("test_wf_ag1")
        assert len(events) == 1
        assert events[0]["event_type"] == "tool_selection_failed"
        assert events[0]["data"]["reason"] == "multiple_tool_calls_not_allowed"
        bus.clear_workflow("test_wf_ag1")

    @patch("system.orchestrator.agents.tool_selection_agent.execute_llm")
    @patch("system.orchestrator.agents.tool_selection_agent.system_entry")
    def test_execute_tool_selection_emits_started_and_selected(
        self, mock_system_entry, mock_execute_llm
    ):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        mock_execute_llm.return_value = {
            "status": "success",
            "result": 'USE_TOOL: add_numbers 1 2',
        }
        mock_system_entry.return_value = {"status": "success", "result": "3"}

        bus = get_event_bus()
        bus.clear_workflow("wf_ag1_events")

        result = execute_tool_selection(
            agent={"name": "math", "role": "calculator", "scope": ["math"]},
            input_data="add 1 and 2",
            context={"workflow_id": "wf_ag1_events", "step_id": "step_1"},
        )

        assert result["status"] == "success"
        events = bus.get_events("wf_ag1_events")
        types = [e["event_type"] for e in events]
        assert "tool_selection_started" in types
        assert "tool_selected" in types
        bus.clear_workflow("wf_ag1_events")

    @patch("system.orchestrator.agents.tool_selection_agent.execute_llm")
    def test_execute_tool_selection_emits_failed_on_multiple_tools(
        self, mock_execute_llm
    ):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        mock_execute_llm.return_value = {
            "status": "success",
            "result": 'USE_TOOL: add_numbers 1 2\nUSE_TOOL: multiply_numbers 3 4',
        }

        bus = get_event_bus()
        bus.clear_workflow("wf_ag1_fail")

        result = execute_tool_selection(
            agent={"name": "math", "role": "calculator", "scope": ["math"]},
            input_data="add 1 and 2",
            context={"workflow_id": "wf_ag1_fail", "step_id": "step_1"},
        )

        assert result["status"] == "failure"
        events = bus.get_events("wf_ag1_fail")
        types = [e["event_type"] for e in events]
        assert "tool_selection_started" in types
        assert "tool_selection_failed" in types
        bus.clear_workflow("wf_ag1_fail")

    @patch("system.orchestrator.agents.tool_selection_agent.execute_llm")
    @patch("system.orchestrator.agents.tool_selection_agent.system_entry")
    def test_execute_tool_selection_survives_emitter_failure(
        self, mock_system_entry, mock_execute_llm
    ):
        from system.orchestrator.agents.tool_selection_agent import execute_tool_selection

        mock_execute_llm.return_value = {
            "status": "success",
            "result": 'USE_TOOL: add_numbers 1 2',
        }
        mock_system_entry.return_value = {"status": "success", "result": "3"}

        with patch("system.orchestrator.agents.tool_selection_agent._ag1_event_emitter", None):
            result = execute_tool_selection(
                agent={"name": "math", "role": "calculator", "scope": ["math"]},
                input_data="add 1 and 2",
                context={"workflow_id": "wf_ag1_no_emitter", "step_id": "step_1"},
            )
            assert result["status"] == "success"
