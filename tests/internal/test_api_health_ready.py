"""
Focused tests for POST-SPRINT-8 closeout: /health and /ready endpoints.

Run:
    cd E:\MutesHand\ai_lab_gui\backend
    pytest ..\..\tests\internal\test_api_health_ready.py -q --tb=short
"""
import os
import sys

# Ensure project root is importable
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
)
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ai_lab_gui", "backend")),
)

from fastapi.testclient import TestClient
from api import app


client = TestClient(app)


def test_health_returns_200_and_expected_shape():
    """GET /health returns 200 with expected liveness JSON."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "ai_lab_backend"


def test_ready_returns_200_and_includes_checks():
    """GET /ready returns 200 with ready:true and structured checks."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["ready"] is True
    assert data["service"] == "ai_lab_backend"
    assert "checks" in data
    checks = data["checks"]
    assert checks.get("workflow_state") is True
    assert checks.get("projection_manager") is True
    assert checks.get("project_root") is True


def test_ready_failure_shape_when_workflow_state_unavailable():
    """
    GET /ready returns 503 with structured not_ready payload when a key
    runtime handle is monkeypatched to None.
    """
    import api as _api_module

    original = _api_module._get_workflow_state
    try:
        _api_module._get_workflow_state = None
        response = client.get("/ready")
        assert response.status_code == 503
        detail = response.json().get("detail", {})
        assert detail.get("status") == "not_ready"
        assert detail.get("ready") is False
        assert detail.get("service") == "ai_lab_backend"
        checks = detail.get("checks", {})
        assert checks.get("workflow_state") is False
        assert checks.get("projection_manager") is True
        assert checks.get("project_root") is True
    finally:
        _api_module._get_workflow_state = original
