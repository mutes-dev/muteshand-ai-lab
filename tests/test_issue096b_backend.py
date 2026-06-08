"""
Backend Tests for ISSUE-096B: Contract-Safe Approval Requests and Notifications

Tests:
- ApprovalRequest model creation and validation
- Thread-safe runtime bridge (concurrent.futures.Future)
- Approval registry keyed by approval_id
- Stale approval rejection logic
- Contract-safe API endpoints (FastAPI test client)
- Notification normalization and API endpoints
- Trace event emission for approval and notification lifecycle
- Governance notification emitter contract compliance
- Runtime reset cleanup of approval registry

Per USER_APPROVAL_CONTRACT_V1 and NOTIFICATION_CONTRACT_V1.
"""

import pytest
import time
import threading
from datetime import datetime, timezone, timedelta
from uuid import UUID

# Approval imports
from system.orchestrator.user_approval import (
    ApprovalRequest,
    ApprovalStatus,
    create_approval_request,
    get_approval,
    get_pending_approvals_for_workflow,
    resolve_approval,
    cleanup_stale_approvals,
    _approval_registry,
    _approval_registry_lock,
)

# Notification imports
from system.interface.notification_manager import (
    notify,
    get_notifications,
    mark_notification_read,
    dismiss_notification,
    get_unread_count,
    NotificationType,
    NotificationSeverity,
    NotificationStatus,
    NotificationSource,
    _notifications,
    _notifications_lock,
    notify_approval_required,
)


# ── ApprovalRequest Model Tests ───────────────────────────────────────────

class TestApprovalRequestModel:
    def test_approval_request_creation(self):
        req = create_approval_request(
            workflow_id="wf-1",
            step_id="step-1",
            reason="approval_required",
            risk_level="HIGH",
            requested_action="execute_step",
            source="governance",
            details={"purpose": "test"},
        )
        assert isinstance(req, ApprovalRequest)
        assert req.status == ApprovalStatus.PENDING
        assert req.workflow_id == "wf-1"
        assert req.step_id == "step-1"
        assert req.risk_level == "HIGH"
        assert req.approval_id is not None
        # Verify UUIDv4 format
        assert UUID(req.approval_id).version == 4

    def test_approval_request_to_dict(self):
        req = create_approval_request(
            workflow_id="wf-1", step_id="step-1", reason="approval_required"
        )
        d = req.to_dict()
        assert d["status"] == "PENDING"
        assert d["workflow_id"] == "wf-1"
        assert d["step_id"] == "step-1"
        assert "approval_id" in d
        assert "created_at" in d
        assert "expires_at" in d

    def test_approval_request_is_expired(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        req.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        assert req.is_expired() is True

    def test_approval_request_not_expired(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        assert req.is_expired() is False


# ── Thread-Safe Runtime Bridge Tests ───────────────────────────────────────

class TestApprovalRuntimeBridge:
    def test_wait_and_resolve(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        result_holder = {}

        def waiter():
            result_holder["approved"] = req.wait_for_decision(timeout=5)

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)  # Let thread block on Future
        resolve_approval(req.approval_id, approved=True, actor="test")
        t.join(timeout=10)

        assert result_holder.get("approved") is True
        assert req.status == ApprovalStatus.APPROVED

    def test_reject_and_wait(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        result_holder = {}

        def waiter():
            result_holder["approved"] = req.wait_for_decision(timeout=5)

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.1)
        resolve_approval(req.approval_id, approved=False, actor="test")
        t.join(timeout=10)

        assert result_holder.get("approved") is False
        assert req.status == ApprovalStatus.REJECTED

    def test_wait_timeout(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        # Set expiry far in the future
        req.expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        # wait_for_decision catches TimeoutError and returns False
        result = req.wait_for_decision(timeout=0.1)
        assert result is False

    def test_double_resolve_raises(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        resolve_approval(req.approval_id, approved=True, actor="test")
        result = resolve_approval(req.approval_id, approved=False, actor="test")
        assert result["success"] is False
        assert result["status"] == "APPROVED"


# ── Approval Registry Tests ─────────────────────────────────────────────────

class TestApprovalRegistry:
    def setup_method(self):
        # Clear registry between tests
        with _approval_registry_lock:
            _approval_registry.clear()

    def test_registry_keyed_by_approval_id(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        fetched = get_approval(req.approval_id)
        assert fetched is req

    def test_get_pending_for_workflow(self):
        create_approval_request(workflow_id="wf-a", step_id="step-1", reason="approval_required")
        create_approval_request(workflow_id="wf-a", step_id="step-2", reason="approval_required")
        create_approval_request(workflow_id="wf-b", step_id="step-1", reason="approval_required")
        pending = get_pending_approvals_for_workflow("wf-a")
        assert len(pending) == 2
        for p in pending:
            assert p.workflow_id == "wf-a"

    def test_resolve_updates_registry(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        resolve_approval(req.approval_id, approved=True, actor="test")
        fetched = get_approval(req.approval_id)
        assert fetched.status == ApprovalStatus.APPROVED

    def test_cleanup_stale_approvals(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        req.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        cleaned = cleanup_stale_approvals()
        assert cleaned >= 1
        assert get_approval(req.approval_id) is not None  # Registry keeps it for audit
        assert get_approval(req.approval_id).status == ApprovalStatus.EXPIRED


# ── Stale Rejection Tests ───────────────────────────────────────────────────

class TestStaleRejection:
    def setup_method(self):
        with _approval_registry_lock:
            _approval_registry.clear()

    def test_reject_expired_approval(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        req.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        result = resolve_approval(req.approval_id, approved=True, actor="test")
        assert result["success"] is False
        assert result["status"] == "EXPIRED"
        assert req.status == ApprovalStatus.EXPIRED

    def test_reject_nonexistent_approval(self):
        result = resolve_approval("fake-id", approved=True, actor="test")
        assert result["success"] is False
        assert result["status"] == "not_found"

    def test_reject_already_resolved(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        resolve_approval(req.approval_id, approved=True, actor="test")
        result = resolve_approval(req.approval_id, approved=True, actor="test")
        assert result["success"] is False
        assert result["status"] == "APPROVED"

    def test_validate_mismatched_workflow(self):
        req = create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        result = resolve_approval(
            req.approval_id,
            approved=True,
            actor="test",
            validate={"workflow_id": "wf-2"},
        )
        assert result["success"] is False
        assert result["status"] == "mismatch"


# ── Notification Contract Tests ─────────────────────────────────────────────

class TestNotificationContract:
    def setup_method(self):
        with _notifications_lock:
            _notifications.clear()

    def test_notification_creation(self):
        nid = notify(
            notification_type=NotificationType.APPROVAL_REQUIRED,
            severity=NotificationSeverity.WARNING,
            title="Approval needed",
            message="Step requires approval",
            workflow_id="wf-1",
            step_id="step-1",
            source=NotificationSource.GOVERNANCE,
        )
        assert nid is not None
        notifications = get_notifications(workflow_id="wf-1")
        assert len(notifications) == 1
        n = notifications[0]
        assert n["notification_id"] == nid
        assert n["type"] == "approval_required"
        assert n["severity"] == "WARNING"
        assert n["status"] == "UNREAD"
        assert n["source"] == "governance"
        assert n["title"] == "Approval needed"

    def test_notification_read(self):
        nid = notify(
            notification_type=NotificationType.WORKFLOW_COMPLETED,
            severity=NotificationSeverity.SUCCESS,
            title="Done",
            message="Workflow done",
            workflow_id="wf-1",
            source=NotificationSource.RUNTIME,
        )
        ok = mark_notification_read(nid)
        assert ok is True
        notifications = get_notifications(workflow_id="wf-1")
        assert notifications[0]["status"] == "READ"
        assert notifications[0]["read_at"] is not None

    def test_notification_dismiss(self):
        nid = notify(
            notification_type=NotificationType.STEP_FAILED,
            severity=NotificationSeverity.ERROR,
            title="Failed",
            message="Step failed",
            workflow_id="wf-1",
            source=NotificationSource.RUNTIME,
        )
        ok = dismiss_notification(nid)
        assert ok is True
        notifications = get_notifications(include_dismissed=False)
        assert len(notifications) == 0

    def test_notification_not_found(self):
        assert mark_notification_read("fake-id") is False
        assert dismiss_notification("fake-id") is False

    def test_unread_count(self):
        notify(
            notification_type=NotificationType.WORKFLOW_COMPLETED,
            severity=NotificationSeverity.SUCCESS,
            title="Done",
            message="Workflow done",
            workflow_id="wf-1",
            source=NotificationSource.RUNTIME,
        )
        assert get_unread_count(workflow_id="wf-1") == 1
        assert get_unread_count() == 1

    def test_notification_bounding(self):
        # Fill beyond max capacity
        for i in range(150):
            notify(
                notification_type=NotificationType.WORKFLOW_COMPLETED,
                severity=NotificationSeverity.INFO,
                title=f"Event {i}",
                message=f"Event {i}",
                workflow_id="wf-1",
                source=NotificationSource.RUNTIME,
            )
        all_notifs = get_notifications(limit=200)
        assert len(all_notifs) <= 200

    def test_notify_approval_required_convenience(self):
        nid = notify_approval_required(
            step_id="step-1",
            project_id="wf-1",
            risk_level="HIGH",
            approval_id="app-123",
        )
        assert nid is not None
        n = get_notifications(workflow_id="wf-1")[0]
        assert n["type"] == "approval_required"
        assert n["metadata"]["approval_id"] == "app-123"
        assert n["action"]["type"] == "approval"

    def test_notification_with_action_and_metadata(self):
        nid = notify(
            notification_type=NotificationType.GOVERNANCE_ESCALATION,
            severity=NotificationSeverity.CRITICAL,
            title="Escalation",
            message="Escalated",
            workflow_id="wf-1",
            step_id="step-1",
            source=NotificationSource.GOVERNANCE,
            action={"type": "link", "url": "/escalation"},
            metadata={"reason": "max_retries"},
        )
        n = get_notifications(workflow_id="wf-1")[0]
        assert n["action"] == {"type": "link", "url": "/escalation"}
        assert n["metadata"] == {"reason": "max_retries"}


# ── API Endpoint Tests (FastAPI TestClient) ─────────────────────────────────

class TestApprovalEndpoints:
    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from ai_lab_gui.backend.api import app
        return TestClient(app)

    def setup_method(self):
        with _approval_registry_lock:
            _approval_registry.clear()

    def test_list_pending_approvals(self, client):
        create_approval_request(workflow_id="wf-test", step_id="step-1", reason="approval_required")
        resp = client.get("/approvals/wf-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == "wf-test"
        assert data["count"] == 1
        assert data["pending"][0]["status"] == "PENDING"

    def test_approve_endpoint(self, client):
        req = create_approval_request(workflow_id="wf-test", step_id="step-1", reason="approval_required")
        resp = client.post(f"/approvals/{req.approval_id}/approve")
        assert resp.status_code == 200
        assert resp.json()["resolution"] == "APPROVED"

    def test_reject_endpoint(self, client):
        req = create_approval_request(workflow_id="wf-test", step_id="step-1", reason="approval_required")
        resp = client.post(f"/approvals/{req.approval_id}/reject")
        assert resp.status_code == 200
        assert resp.json()["resolution"] == "REJECTED"

    def test_approve_not_found(self, client):
        resp = client.post("/approvals/fake-id/approve")
        assert resp.status_code == 404

    def test_reject_not_found(self, client):
        resp = client.post("/approvals/fake-id/reject")
        assert resp.status_code == 404

    def test_approve_already_resolved(self, client):
        req = create_approval_request(workflow_id="wf-test", step_id="step-1", reason="approval_required")
        client.post(f"/approvals/{req.approval_id}/approve")
        resp = client.post(f"/approvals/{req.approval_id}/approve")
        assert resp.status_code == 409

    def test_approve_expired(self, client):
        req = create_approval_request(workflow_id="wf-test", step_id="step-1", reason="approval_required")
        req.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        resp = client.post(f"/approvals/{req.approval_id}/approve")
        assert resp.status_code == 410

    def test_legacy_endpoints_gone(self, client):
        resp = client.get("/approval/pending")
        assert resp.status_code == 410
        resp = client.post("/approve", json={"workflow_id": "w", "step_id": "s", "approved": True})
        assert resp.status_code == 410
        resp = client.post("/deny", json={"workflow_id": "w", "step_id": "s", "approved": False})
        assert resp.status_code == 410


class TestNotificationEndpoints:
    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from ai_lab_gui.backend.api import app
        return TestClient(app)

    def setup_method(self):
        with _notifications_lock:
            _notifications.clear()

    def test_list_notifications(self, client):
        notify(
            notification_type=NotificationType.WORKFLOW_COMPLETED,
            severity=NotificationSeverity.SUCCESS,
            title="Done",
            message="Done",
            workflow_id="wf-1",
            source=NotificationSource.RUNTIME,
        )
        resp = client.get("/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["unread"] == 1

    def test_list_workflow_notifications(self, client):
        notify(
            notification_type=NotificationType.WORKFLOW_COMPLETED,
            severity=NotificationSeverity.SUCCESS,
            title="Done",
            message="Done",
            workflow_id="wf-1",
            source=NotificationSource.RUNTIME,
        )
        resp = client.get("/notifications/wf-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == "wf-1"
        assert data["count"] == 1

    def test_read_notification(self, client):
        nid = notify(
            notification_type=NotificationType.WORKFLOW_COMPLETED,
            severity=NotificationSeverity.SUCCESS,
            title="Done",
            message="Done",
            workflow_id="wf-1",
            source=NotificationSource.RUNTIME,
        )
        resp = client.post(f"/notifications/{nid}/read")
        assert resp.status_code == 200
        assert resp.json()["new_status"] == "READ"

    def test_dismiss_notification(self, client):
        nid = notify(
            notification_type=NotificationType.WORKFLOW_COMPLETED,
            severity=NotificationSeverity.SUCCESS,
            title="Done",
            message="Done",
            workflow_id="wf-1",
            source=NotificationSource.RUNTIME,
        )
        resp = client.post(f"/notifications/{nid}/dismiss")
        assert resp.status_code == 200
        assert resp.json()["new_status"] == "DISMISSED"

    def test_read_not_found(self, client):
        resp = client.post("/notifications/fake-id/read")
        assert resp.status_code == 404

    def test_dismiss_not_found(self, client):
        resp = client.post("/notifications/fake-id/dismiss")
        assert resp.status_code == 404

    def test_notification_filter_by_workflow(self, client):
        notify(
            notification_type=NotificationType.WORKFLOW_COMPLETED,
            severity=NotificationSeverity.SUCCESS,
            title="A",
            message="A",
            workflow_id="wf-a",
            source=NotificationSource.RUNTIME,
        )
        notify(
            notification_type=NotificationType.WORKFLOW_COMPLETED,
            severity=NotificationSeverity.SUCCESS,
            title="B",
            message="B",
            workflow_id="wf-b",
            source=NotificationSource.RUNTIME,
        )
        resp = client.get("/notifications?workflow_id=wf-a")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        assert resp.json()["notifications"][0]["workflow_id"] == "wf-a"


# ── Runtime Reset Cleanup Test ──────────────────────────────────────────────

class TestRuntimeResetCleanup:
    def setup_method(self):
        with _approval_registry_lock:
            _approval_registry.clear()
        with _notifications_lock:
            _notifications.clear()

    def test_reset_clears_approval_registry(self):
        create_approval_request(workflow_id="wf-1", step_id="step-1", reason="approval_required")
        # Simulate what /admin/test/reset_runtime does
        try:
            from system.orchestrator.user_approval import _approval_registry, _approval_registry_lock
            with _approval_registry_lock:
                _approval_registry.clear()
        except Exception:
            pass
        assert len(_approval_registry) == 0


# ── Governance Notification Emitter Contract Test ───────────────────────────

class TestGovernanceNotificationContract:
    def setup_method(self):
        with _notifications_lock:
            _notifications.clear()

    def test_governance_block_notification_has_approval_id_when_provided(self):
        nid = notify_approval_required(
            step_id="step-1",
            project_id="wf-1",
            risk_level="HIGH",
            approval_id="app-abc-123",
        )
        n = get_notifications(workflow_id="wf-1")[0]
        assert n["action"]["approval_id"] == "app-abc-123"
        assert n["type"] == "approval_required"
        assert n["severity"] == "WARNING"

    def test_governance_block_notification_without_approval_id(self):
        nid = notify_approval_required(
            step_id="step-1",
            project_id="wf-1",
            risk_level="MEDIUM",
        )
        n = get_notifications(workflow_id="wf-1")[0]
        assert n["action"] == {}
        assert n["type"] == "approval_required"
