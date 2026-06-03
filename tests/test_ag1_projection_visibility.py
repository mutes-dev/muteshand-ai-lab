"""
ISSUE-073 FINAL PHASE — AG1 Projection/Frontend Visibility Tests

Validates that AG1 attribution metadata flows through projection schema
and API projection layer as read-only observability.

Hard boundaries enforced:
- no Task Hub changes
- no History changes
- no lifecycle display changes
- no retry/actionability interpretation
- no FAILED actionability changes
- no planning/replan changes
- no transport changes
- no controls, buttons, agent actions
- no frontend authority
- no projection authority
- no governance input changes
- no execution_result changes
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.projection_schema import (
    build_step_projection,
    build_workflow_projection,
    PROJECTION_STATE_ACTIVE,
)


def _make_step(step_id, with_agent_metadata=None):
    step = {
        "id": step_id,
        "type": "action",
        "purpose": "Test step",
        "expected_outcome": "Success",
        "risk": "LOW",
        "importance": "MEDIUM",
        "depends_on": [],
        "resource_targets": [],
        "status": "COMPLETED",
        "retries": 0,
    }
    if with_agent_metadata is not None:
        step["_agent_metadata"] = with_agent_metadata
    return step


def _make_workflow(step_count=1, with_agent_metadata=None):
    steps = [_make_step(f"s-{i:03d}", with_agent_metadata=with_agent_metadata) for i in range(1, step_count + 1)]
    return {
        "id": "wf-test",
        "name": "Test Workflow",
        "steps": steps,
        "status": "COMPLETED",
    }


class TestStepProjectionAgentMetadata:
    """Validate build_step_projection passes through _agent_metadata."""

    def test_step_projection_includes_agent_metadata(self):
        meta = {
            "selected_agent": "tool_selection_agent",
            "selected_agent_type": "tool_selection",
            "selected_tool": "add_numbers",
            "routing_source": "agent_executor",
            "system_entry_routed": True,
            "agent_authority": "advisory_only",
        }
        step = _make_step("s-001", with_agent_metadata=meta)
        proj = build_step_projection("wf-001", step, 1)
        assert proj["agent_metadata"] == meta
        print("  [PASS] step projection includes agent_metadata when present")

    def test_step_projection_agent_metadata_none_when_absent(self):
        step = _make_step("s-001")
        assert "_agent_metadata" not in step
        proj = build_step_projection("wf-001", step, 1)
        assert proj.get("agent_metadata") is None
        print("  [PASS] step projection agent_metadata is None when absent")

    def test_step_projection_no_execution_fields_leaked(self):
        meta = {"selected_tool": "add_numbers"}
        step = _make_step("s-001", with_agent_metadata=meta)
        step["tool_call"] = "USE_TOOL: add_numbers"
        step["execution_result"] = {"status": "success"}
        proj = build_step_projection("wf-001", step, 1)
        assert "tool_call" not in proj
        assert "execution_result" not in proj
        assert proj["agent_metadata"] == meta
        print("  [PASS] step projection excludes execution fields while exposing agent_metadata")


class TestWorkflowProjectionAgentMetadata:
    """Validate build_workflow_projection propagates agent_metadata."""

    def test_workflow_projection_propagates_agent_metadata(self):
        meta = {
            "selected_agent": "tool_selection_agent",
            "selected_agent_type": "tool_selection",
            "selected_tool": "add_numbers",
            "routing_source": "agent_executor",
            "system_entry_routed": True,
            "agent_authority": "advisory_only",
        }
        wf = _make_workflow(step_count=2, with_agent_metadata=meta)
        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="COMPLETED",
            projection_state=PROJECTION_STATE_ACTIVE,
        )
        for sp in proj["steps"]:
            assert sp["agent_metadata"] == meta
        print("  [PASS] workflow projection propagates agent_metadata through all steps")

    def test_workflow_projection_none_for_steps_without_metadata(self):
        wf = _make_workflow(step_count=2)
        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="COMPLETED",
            projection_state=PROJECTION_STATE_ACTIVE,
        )
        for sp in proj["steps"]:
            assert sp.get("agent_metadata") is None
        print("  [PASS] workflow projection agent_metadata is None for steps without it")

    def test_workflow_projection_mixed_metadata(self):
        wf = _make_workflow(step_count=2)
        wf["steps"][0]["_agent_metadata"] = {"selected_tool": "add_numbers"}
        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="COMPLETED",
            projection_state=PROJECTION_STATE_ACTIVE,
        )
        assert proj["steps"][0]["agent_metadata"] == {"selected_tool": "add_numbers"}
        assert proj["steps"][1].get("agent_metadata") is None
        print("  [PASS] workflow projection handles mixed metadata presence")


class TestApiProjectionAgentMetadata:
    """Validate project_workflow_for_gui passes through agent_metadata."""

    def test_api_projection_includes_agent_metadata(self):
        from ai_lab_gui.backend.api import project_workflow_for_gui
        wf = _make_workflow(step_count=1, with_agent_metadata={
            "selected_agent": "tool_selection_agent",
            "selected_tool": "add_numbers",
            "routing_source": "agent_executor",
            "system_entry_routed": True,
            "agent_authority": "advisory_only",
        })
        projected = project_workflow_for_gui(wf)
        assert projected["steps"][0]["agent_metadata"] is not None
        assert projected["steps"][0]["agent_metadata"]["selected_agent"] == "tool_selection_agent"
        print("  [PASS] API projection includes agent_metadata")

    def test_api_projection_none_when_absent(self):
        from ai_lab_gui.backend.api import project_workflow_for_gui
        wf = _make_workflow(step_count=1)
        projected = project_workflow_for_gui(wf)
        assert projected["steps"][0].get("agent_metadata") is None
        print("  [PASS] API projection agent_metadata is None when absent")

    def test_api_projection_no_execution_fields(self):
        from ai_lab_gui.backend.api import project_workflow_for_gui
        wf = _make_workflow(step_count=1, with_agent_metadata={"selected_tool": "add_numbers"})
        wf["steps"][0]["tool_call"] = "USE_TOOL: add_numbers"
        wf["steps"][0]["execution_result"] = {"status": "success"}
        projected = project_workflow_for_gui(wf)
        step = projected["steps"][0]
        assert "tool_call" not in step
        assert "execution_result" not in step
        assert step["agent_metadata"] == {"selected_tool": "add_numbers"}
        print("  [PASS] API projection excludes execution fields while exposing agent_metadata")


class TestProjectionAuthorityBoundaries:
    """Validate that agent_metadata exposure does not alter projection authority."""

    def test_projection_does_not_infer_lifecycle(self):
        meta = {"selected_agent": "tool_selection_agent"}
        step = _make_step("s-001", with_agent_metadata=meta)
        step["status"] = "FAILED"
        proj = build_step_projection("wf-001", step, 1)
        assert proj["status"] == "FAILED"
        assert proj["agent_metadata"] == meta
        # Status must come from step, not be inferred from agent_metadata
        assert "lifecycle" not in proj["agent_metadata"]
        print("  [PASS] projection does not infer lifecycle from agent_metadata")

    def test_projection_does_not_infer_retry(self):
        meta = {"selected_agent": "tool_selection_agent"}
        step = _make_step("s-001", with_agent_metadata=meta)
        step["retries"] = 3
        proj = build_step_projection("wf-001", step, 1)
        assert proj["retries"] == 3
        assert proj["agent_metadata"] == meta
        assert "retry" not in proj["agent_metadata"]
        print("  [PASS] projection does not infer retry from agent_metadata")

    def test_workflow_projection_failure_metadata_independent(self):
        meta = {"selected_agent": "tool_selection_agent"}
        wf = _make_workflow(step_count=1, with_agent_metadata=meta)
        wf["steps"][0]["status"] = "FAILED"
        wf["error"] = "step failed"
        proj = build_workflow_projection(
            workflow=wf,
            projection_version=1,
            lifecycle_status="FAILED",
        )
        assert proj["failure_reason"] == "step failed"
        assert proj["steps"][0]["agent_metadata"] == meta
        print("  [PASS] workflow failure metadata is independent of agent_metadata")


if __name__ == "__main__":
    import traceback

    all_tests = []
    for cls in [
        TestStepProjectionAgentMetadata,
        TestWorkflowProjectionAgentMetadata,
        TestApiProjectionAgentMetadata,
        TestProjectionAuthorityBoundaries,
    ]:
        for name in dir(cls):
            if name.startswith("test_"):
                all_tests.append((cls, name))

    passed = 0
    failed = 0
    for cls, name in all_tests:
        try:
            instance = cls()
            getattr(instance, name)()
            passed += 1
        except Exception:
            failed += 1
            print(f"  [FAIL] {cls.__name__}.{name}")
            traceback.print_exc()

    print(f"\nResults: {passed}/{passed + failed} passed")
    if failed > 0:
        sys.exit(1)
