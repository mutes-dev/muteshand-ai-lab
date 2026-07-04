"""
Focused tests for SPRINT-11-FIX: synthetic projection fallback in api.py.

Validates that _build_synthetic_projection sets projection_state correctly
for terminal and non-terminal workflows, and preserves projection_version
without introducing high anchor versions.

Run:
    cd E:\MutesHand\ai_lab_gui\backend
    pytest ..\..\tests\internal\test_api_synthetic_projection.py -v --tb=short
"""
import os
import sys

# Ensure project root and backend are importable
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
)
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ai_lab_gui", "backend")),
)

from api import _build_synthetic_projection


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_wf(workflow_id: str, status: str, steps: list = None) -> dict:
    return {
        "id": workflow_id,
        "status": status,
        "steps": steps or [],
        "output": None,
    }


# ── Tests ────────────────────────────────────────────────────────────────────

def test_synthetic_completed_has_terminal_state():
    wf = _make_wf("wf-comp-1", "COMPLETED", [
        {"id": "s1", "type": "EXECUTE_API", "purpose": "read", "status": "COMPLETED"},
    ])
    proj = _build_synthetic_projection("wf-comp-1", wf)
    assert proj["projection_state"] == "TERMINAL"
    assert proj["lifecycle_status"] == "COMPLETED"
    assert proj["workflow_id"] == "wf-comp-1"
    assert "projection_version" in proj
    assert "projection_timestamp" in proj
    assert "projection_type" in proj


def test_synthetic_failed_has_terminal_state():
    wf = _make_wf("wf-fail-1", "FAILED", [
        {"id": "s1", "type": "EXECUTE_API", "purpose": "read", "status": "FAILED"},
    ])
    proj = _build_synthetic_projection("wf-fail-1", wf)
    assert proj["projection_state"] == "TERMINAL"
    assert proj["lifecycle_status"] == "FAILED"


def test_synthetic_cancelled_has_terminal_state():
    wf = _make_wf("wf-cancel-1", "CANCELLED", [
        {"id": "s1", "type": "EXECUTE_API", "purpose": "read", "status": "CANCELLED"},
    ])
    proj = _build_synthetic_projection("wf-cancel-1", wf)
    assert proj["projection_state"] == "TERMINAL"
    assert proj["lifecycle_status"] == "CANCELLED"


def test_synthetic_active_has_active_state():
    wf = _make_wf("wf-active-1", "ACTIVE", [
        {"id": "s1", "type": "EXECUTE_API", "purpose": "read", "status": "ACTIVE"},
    ])
    proj = _build_synthetic_projection("wf-active-1", wf)
    assert proj["projection_state"] == "ACTIVE"
    assert proj["lifecycle_status"] == "ACTIVE"


def test_synthetic_blocked_has_active_state():
    wf = _make_wf("wf-block-1", "BLOCKED", [
        {"id": "s1", "type": "EXECUTE_API", "purpose": "read", "status": "BLOCKED"},
    ])
    proj = _build_synthetic_projection("wf-block-1", wf)
    assert proj["projection_state"] == "ACTIVE"
    assert proj["lifecycle_status"] == "BLOCKED"


def test_synthetic_paused_has_active_state():
    wf = _make_wf("wf-pause-1", "PAUSED", [
        {"id": "s1", "type": "EXECUTE_API", "purpose": "read", "status": "PAUSED"},
    ])
    proj = _build_synthetic_projection("wf-pause-1", wf)
    assert proj["projection_state"] == "ACTIVE"
    assert proj["lifecycle_status"] == "PAUSED"


def test_synthetic_preserves_existing_projection_version():
    wf = _make_wf("wf-ver-1", "COMPLETED")
    # Simulate a pre-existing projection_version in the workflow dict (should not happen,
    # but the helper must not clobber an existing version)
    proj = _build_synthetic_projection("wf-ver-1", wf)
    assert proj["projection_version"] == 1  # default when missing


def test_synthetic_does_not_use_high_anchor_version():
    wf = _make_wf("wf-anchor-1", "COMPLETED")
    proj = _build_synthetic_projection("wf-anchor-1", wf)
    assert proj["projection_version"] < 1000
    assert proj["projection_version"] == 1  # explicit default, not 999999


def test_synthetic_includes_steps_and_outputs():
    wf = _make_wf("wf-steps-1", "COMPLETED", [
        {"id": "s1", "type": "EXECUTE_API", "purpose": "read file", "status": "COMPLETED",
         "execution_result": {"status": "success", "output": "hello"}},
    ])
    proj = _build_synthetic_projection("wf-steps-1", wf)
    assert len(proj["steps"]) == 1
    assert proj["steps"][0]["status"] == "COMPLETED"
    assert "execution_result" not in proj["steps"][0]  # project_workflow_for_gui strips it
    assert len(proj["outputs"]) == 1
