"""
ISSUE-097 — Admin/Test Endpoint Gating Validation

Tests:
- /admin/test/* endpoints are blocked by default
- /admin/test/* endpoints work when MH_ENABLE_ADMIN_TEST_ENDPOINTS=true
- Token gating works when MH_ADMIN_TEST_TOKEN is set
- Normal non-admin endpoints remain unaffected

DIRECT_INTERNAL_CALLS:
  - ai_lab_gui.backend.api
MOCKING_POLICY: None (guard layer tests)
TEST_INTENT: VALIDATION
ARCHITECTURAL_SCOPE: P0 safety hardening
"""

import pytest
from fastapi.testclient import TestClient


# We must import api after any env setup, but since module-level flags are
# evaluated at import time, we monkeypatch them directly on the module.
from ai_lab_gui.backend import api as _api_module
from ai_lab_gui.backend.api import app


@pytest.fixture(scope="function")
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_admin_gates():
    """Reset admin gate flags to safe defaults before each test."""
    orig_enabled = _api_module._ADMIN_TEST_ENABLED
    orig_token = _api_module._ADMIN_TEST_TOKEN
    _api_module._ADMIN_TEST_ENABLED = False
    _api_module._ADMIN_TEST_TOKEN = ""
    yield
    _api_module._ADMIN_TEST_ENABLED = orig_enabled
    _api_module._ADMIN_TEST_TOKEN = orig_token


class TestAdminEndpointsBlockedByDefault:
    def test_reset_runtime_blocked_by_default(self, client):
        resp = client.post("/admin/test/reset_runtime")
        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()

    def test_execute_deterministic_fail_blocked_by_default(self, client):
        resp = client.post("/admin/test/execute_deterministic_fail", json={
            "workflow_id": "wf-test",
            "step_id": "step-1",
        })
        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()

    def test_create_approval_request_blocked_by_default(self, client):
        resp = client.post("/admin/test/create_approval_request", json={
            "workflow_id": "wf-test",
            "step_id": "step-1",
            "reason": "approval_required",
        })
        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()


class TestAdminEndpointsEnabledWithoutToken:
    def test_reset_runtime_enabled_no_token(self, client):
        _api_module._ADMIN_TEST_ENABLED = True
        # reset_runtime mutates real runtime state; we only validate guard pass
        # by checking the endpoint no longer returns 403.
        # The actual reset will proceed and may fail for other reasons.
        resp = client.post("/admin/test/reset_runtime")
        assert resp.status_code != 403
        # If it proceeded, it should be 200 or some runtime-related error,
        # but definitely not "disabled".
        assert "disabled" not in resp.text.lower()

    def test_create_approval_request_enabled_no_token(self, client):
        _api_module._ADMIN_TEST_ENABLED = True
        resp = client.post("/admin/test/create_approval_request", json={
            "workflow_id": "wf-test-enabled",
            "step_id": "step-1",
            "reason": "approval_required",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert "approval_id" in data


class TestAdminEndpointsWithTokenGating:
    def test_missing_token_blocked(self, client):
        _api_module._ADMIN_TEST_ENABLED = True
        _api_module._ADMIN_TEST_TOKEN = "secret-token-123"
        resp = client.post("/admin/test/create_approval_request", json={
            "workflow_id": "wf-test",
            "step_id": "step-1",
        })
        assert resp.status_code == 403
        assert "Invalid admin test token" in resp.json()["detail"]

    def test_wrong_token_blocked(self, client):
        _api_module._ADMIN_TEST_ENABLED = True
        _api_module._ADMIN_TEST_TOKEN = "secret-token-123"
        resp = client.post("/admin/test/create_approval_request", json={
            "workflow_id": "wf-test",
            "step_id": "step-1",
        }, headers={"X-MH-Admin-Token": "wrong-token"})
        assert resp.status_code == 403
        assert "Invalid admin test token" in resp.json()["detail"]

    def test_correct_token_succeeds(self, client):
        _api_module._ADMIN_TEST_ENABLED = True
        _api_module._ADMIN_TEST_TOKEN = "secret-token-123"
        resp = client.post("/admin/test/create_approval_request", json={
            "workflow_id": "wf-test-token",
            "step_id": "step-1",
            "reason": "approval_required",
        }, headers={"X-MH-Admin-Token": "secret-token-123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert "approval_id" in data

    def test_reset_runtime_with_correct_token(self, client):
        _api_module._ADMIN_TEST_ENABLED = True
        _api_module._ADMIN_TEST_TOKEN = "secret-token-123"
        resp = client.post("/admin/test/reset_runtime", headers={
            "X-MH-Admin-Token": "secret-token-123"
        })
        assert resp.status_code != 403
        assert "disabled" not in resp.text.lower()
        assert "Invalid admin test token" not in resp.text


class TestNormalEndpointsUnaffected:
    def test_execute_endpoint_unaffected(self, client):
        # /execute is a normal endpoint and should not be gated
        resp = client.post("/execute", json={"input": ""})
        # Empty input should fail with 400, NOT 403 admin gate
        assert resp.status_code == 400
        assert "admin" not in resp.text.lower()

    def test_llm_usage_recent_unaffected(self, client):
        resp = client.get("/llm/usage/recent")
        # Should not be blocked by admin gate
        assert resp.status_code != 403
        assert "disabled" not in resp.text.lower()

    def test_status_endpoint_unaffected(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        assert "admin" not in resp.text.lower()
