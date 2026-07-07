"""
Tests for SPRINT-11 SLICE C — Profile metadata projection transport.

Validates that:
1. build_workflow_projection() includes profile_metadata when _profile_metadata is present.
2. build_workflow_projection() returns None for profile_metadata when absent.
3. project_workflow_for_gui() includes profile_metadata when _profile_metadata is present.
4. _build_synthetic_projection preserves profile_metadata through the synthetic path.
5. route_metadata behavior is not broken.

Run:
    cd E:\\MutesHand
    python -m pytest tests\\internal\\test_profile_metadata_projection.py -v --tb=short
"""

import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if os.path.join(_PROJECT_ROOT, "ai_lab_gui", "backend") not in sys.path:
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "ai_lab_gui", "backend"))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_workflow_with_profile(workflow_id="wf-prof-1", status="ACTIVE"):
    return {
        "id": workflow_id,
        "status": status,
        "steps": [
            {"id": "s1", "type": "EXECUTE_API", "purpose": "read", "status": "COMPLETED"},
        ],
        "output": None,
        "_profile_metadata": {
            "selected_profile": "ComputeProfile",
            "recommended_profile": "ComputeProfile",
            "profile_reason_code": "pure_arithmetic_computation",
        },
        "_capability_route_metadata": {
            "route_decision": "ROUTE_ACCEPTED",
            "capability_id": "arithmetic",
            "route_confidence": 1.0,
            "route_reason_code": "pure_arithmetic_chain",
        },
    }


def _make_workflow_without_profile(workflow_id="wf-noprof-1", status="COMPLETED"):
    return {
        "id": workflow_id,
        "status": status,
        "steps": [
            {"id": "s1", "type": "EXECUTE_API", "purpose": "read", "status": "COMPLETED"},
        ],
        "output": None,
    }


# ── Tests: build_workflow_projection ─────────────────────────────────────────

def test_projection_includes_profile_metadata_when_present():
    from system.orchestrator.projection_schema import build_workflow_projection
    wf = _make_workflow_with_profile()
    proj = build_workflow_projection(
        workflow=wf,
        projection_version=1,
        lifecycle_status="ACTIVE",
    )
    assert proj["profile_metadata"] is not None
    assert proj["profile_metadata"]["selected_profile"] == "ComputeProfile"
    assert proj["profile_metadata"]["recommended_profile"] == "ComputeProfile"
    assert proj["profile_metadata"]["profile_reason_code"] == "pure_arithmetic_computation"


def test_projection_profile_metadata_none_when_absent():
    from system.orchestrator.projection_schema import build_workflow_projection
    wf = _make_workflow_without_profile()
    proj = build_workflow_projection(
        workflow=wf,
        projection_version=1,
        lifecycle_status="COMPLETED",
    )
    assert proj["profile_metadata"] is None


def test_projection_route_metadata_still_present():
    from system.orchestrator.projection_schema import build_workflow_projection
    wf = _make_workflow_with_profile()
    proj = build_workflow_projection(
        workflow=wf,
        projection_version=1,
        lifecycle_status="ACTIVE",
    )
    assert proj["route_metadata"] is not None
    assert proj["route_metadata"]["capability_id"] == "arithmetic"
    assert proj["route_metadata"]["route_decision"] == "ROUTE_ACCEPTED"


def test_projection_route_metadata_none_when_absent():
    from system.orchestrator.projection_schema import build_workflow_projection
    wf = _make_workflow_without_profile()
    proj = build_workflow_projection(
        workflow=wf,
        projection_version=1,
        lifecycle_status="COMPLETED",
    )
    assert proj["route_metadata"] is None


# ── Tests: project_workflow_for_gui ──────────────────────────────────────────

def test_project_workflow_for_gui_includes_profile_metadata():
    from api import project_workflow_for_gui
    wf = _make_workflow_with_profile()
    result = project_workflow_for_gui(wf)
    assert result["profile_metadata"] is not None
    assert result["profile_metadata"]["selected_profile"] == "ComputeProfile"
    assert result["profile_metadata"]["profile_reason_code"] == "pure_arithmetic_computation"


def test_project_workflow_for_gui_profile_metadata_none_when_absent():
    from api import project_workflow_for_gui
    wf = _make_workflow_without_profile()
    result = project_workflow_for_gui(wf)
    assert result["profile_metadata"] is None


def test_project_workflow_for_gui_route_metadata_still_present():
    from api import project_workflow_for_gui
    wf = _make_workflow_with_profile()
    result = project_workflow_for_gui(wf)
    assert result["route_metadata"] is not None
    assert result["route_metadata"]["capability_id"] == "arithmetic"


# ── Tests: _build_synthetic_projection ───────────────────────────────────────

def test_synthetic_projection_preserves_profile_metadata():
    from api import _build_synthetic_projection
    wf = _make_workflow_with_profile(status="COMPLETED")
    proj = _build_synthetic_projection("wf-prof-1", wf)
    assert proj["profile_metadata"] is not None
    assert proj["profile_metadata"]["selected_profile"] == "ComputeProfile"
    assert proj["profile_metadata"]["recommended_profile"] == "ComputeProfile"
    assert proj["profile_metadata"]["profile_reason_code"] == "pure_arithmetic_computation"


def test_synthetic_projection_profile_metadata_none_when_absent():
    from api import _build_synthetic_projection
    wf = _make_workflow_without_profile(status="COMPLETED")
    proj = _build_synthetic_projection("wf-noprof-1", wf)
    assert proj["profile_metadata"] is None


def test_synthetic_projection_preserves_route_metadata():
    from api import _build_synthetic_projection
    wf = _make_workflow_with_profile(status="COMPLETED")
    proj = _build_synthetic_projection("wf-prof-1", wf)
    assert proj["route_metadata"] is not None
    assert proj["route_metadata"]["capability_id"] == "arithmetic"
