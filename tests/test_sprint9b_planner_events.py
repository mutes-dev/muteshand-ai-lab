"""
Sprint 9B — Planner Event Emission Tests

Validates:
- planning_started event emitted with correct workflow_id
- planning_completed event emitted with correct step_count
- planning_retry event emitted on retry path
- planning_failed event emitted on failure path
- event emission failure does not break planning
"""

import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import patch, MagicMock

from system.interface.event_bus import get_event_bus


class TestPlannerEventEmission:
    def test_event_types_defined(self):
        from system.interface.event_emitter import (
            EVENT_PLANNING_STARTED,
            EVENT_PLANNING_RETRY,
            EVENT_PLANNING_COMPLETED,
            EVENT_PLANNING_FAILED,
        )
        assert EVENT_PLANNING_STARTED == "planning_started"
        assert EVENT_PLANNING_RETRY == "planning_retry"
        assert EVENT_PLANNING_COMPLETED == "planning_completed"
        assert EVENT_PLANNING_FAILED == "planning_failed"

    def test_emit_planning_started_publishes_event(self):
        from system.interface.event_emitter import emit_planning_started
        bus = get_event_bus()
        bus.clear_workflow("test_wf_started")
        emit_planning_started("test_wf_started", attempt=0, prompt_version="v2")
        events = bus.get_events("test_wf_started")
        assert len(events) == 1
        assert events[0]["event_type"] == "planning_started"
        assert events[0]["data"]["attempt"] == 0
        assert events[0]["data"]["prompt_version"] == "v2"
        bus.clear_workflow("test_wf_started")

    def test_emit_planning_completed_publishes_event(self):
        from system.interface.event_emitter import emit_planning_completed
        bus = get_event_bus()
        bus.clear_workflow("test_wf_completed")
        emit_planning_completed("test_wf_completed", step_count=3, prompt_version="v2")
        events = bus.get_events("test_wf_completed")
        assert len(events) == 1
        assert events[0]["event_type"] == "planning_completed"
        assert events[0]["data"]["step_count"] == 3
        bus.clear_workflow("test_wf_completed")

    def test_emit_planning_retry_publishes_event(self):
        from system.interface.event_emitter import emit_planning_retry
        bus = get_event_bus()
        bus.clear_workflow("test_wf_retry")
        emit_planning_retry("test_wf_retry", attempt=1, reason="llm_call_failed")
        events = bus.get_events("test_wf_retry")
        assert len(events) == 1
        assert events[0]["event_type"] == "planning_retry"
        assert events[0]["data"]["attempt"] == 1
        assert events[0]["data"]["reason"] == "llm_call_failed"
        bus.clear_workflow("test_wf_retry")

    def test_emit_planning_failed_publishes_event(self):
        from system.interface.event_emitter import emit_planning_failed
        bus = get_event_bus()
        bus.clear_workflow("test_wf_failed")
        emit_planning_failed("test_wf_failed", reason="planner_parse_failure")
        events = bus.get_events("test_wf_failed")
        assert len(events) == 1
        assert events[0]["event_type"] == "planning_failed"
        assert events[0]["data"]["reason"] == "planner_parse_failure"
        bus.clear_workflow("test_wf_failed")

    @patch("system.orchestrator.orchestrator_planner.execute_llm")
    def test_plan_workflow_emits_started_and_completed(self, mock_execute_llm):
        from system.orchestrator.orchestrator_planner import plan_workflow

        mock_execute_llm.return_value = {
            "status": "success",
            "result": json.dumps({
                "steps": [
                    {"name": "step1", "purpose": "add 1 and 2", "agent": "math", "type": "EXECUTE_API", "estimated_complexity": "LOW"}
                ]
            })
        }

        bus = get_event_bus()
        bus.clear_workflow("wf_test_events")

        result = plan_workflow("add 1 and 2", pre_generated_workflow_id="wf_test_events")

        assert result["status"] == "success"
        events = bus.get_events("wf_test_events")
        types = [e["event_type"] for e in events]
        assert "planning_started" in types
        assert "planning_completed" in types
        bus.clear_workflow("wf_test_events")

    @patch("system.orchestrator.orchestrator_planner.execute_llm")
    def test_plan_workflow_emits_retry_on_llm_failure(self, mock_execute_llm):
        from system.orchestrator.orchestrator_planner import plan_workflow

        # First call fails, second succeeds
        mock_execute_llm.side_effect = [
            {"status": "failure", "reason": "timeout"},
            {"status": "success", "result": json.dumps({
                "steps": [
                    {"name": "step1", "purpose": "add 1 and 2", "agent": "math", "type": "EXECUTE_API", "estimated_complexity": "LOW"}
                ]
            })}
        ]

        bus = get_event_bus()
        bus.clear_workflow("wf_test_retry")

        result = plan_workflow("add 1 and 2", pre_generated_workflow_id="wf_test_retry")

        assert result["status"] == "success"
        events = bus.get_events("wf_test_retry")
        types = [e["event_type"] for e in events]
        assert "planning_started" in types
        assert "planning_retry" in types
        assert "planning_completed" in types
        bus.clear_workflow("wf_test_retry")

    @patch("system.orchestrator.orchestrator_planner.execute_llm")
    def test_plan_workflow_emits_failed_on_exhausted_retries(self, mock_execute_llm):
        from system.orchestrator.orchestrator_planner import plan_workflow

        mock_execute_llm.return_value = {"status": "failure", "reason": "timeout"}

        bus = get_event_bus()
        bus.clear_workflow("wf_test_failed")

        result = plan_workflow("add 1 and 2", pre_generated_workflow_id="wf_test_failed")

        assert result["status"] == "failure"
        events = bus.get_events("wf_test_failed")
        types = [e["event_type"] for e in events]
        assert "planning_started" in types
        assert "planning_failed" in types
        bus.clear_workflow("wf_test_failed")

    @patch("system.orchestrator.orchestrator_planner.execute_llm")
    def test_plan_workflow_survives_event_emitter_failure(self, mock_execute_llm):
        from system.orchestrator.orchestrator_planner import plan_workflow

        mock_execute_llm.return_value = {
            "status": "success",
            "result": json.dumps({
                "steps": [
                    {"name": "step1", "purpose": "add 1 and 2", "agent": "math", "type": "EXECUTE_API", "estimated_complexity": "LOW"}
                ]
            })
        }

        with patch("system.orchestrator.orchestrator_planner._planner_event_emitter", None):
            result = plan_workflow("add 1 and 2", pre_generated_workflow_id="wf_test_no_emitter")
            assert result["status"] == "success"
