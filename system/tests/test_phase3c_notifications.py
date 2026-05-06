"""
PHASE 3C — NOTIFICATION SYSTEM TESTS (M10)

Verifies:
1. SUCCESS notification on step success
2. ERROR notification on step failure
3. GOVERNANCE notification on retry/escalation
4. Notifications are output only (no control impact)
5. Failure isolation (notification failure doesn't break execution)

Architecture validation:
- execution_result unchanged
- notifications are output only
- no control flow modification
- trace remains primary
"""

import pytest
from system.interface.notification_manager import (
    notify,
    notify_step_success,
    notify_step_failure,
    notify_governance_retry,
    notify_governance_escalation,
    notify_approval_required,
    get_notifications,
    clear_notifications,
    set_filter_level,
    FilterLevel,
    NotificationType,
    NotificationCategory
)


# ─── TEST 1: SUCCESS NOTIFICATION ────────────────────────────────────────────

def test_success_notification():
    """
    Step success → SUCCESS notification created
    """
    clear_notifications()
    
    notif_id = notify_step_success(
        step_id="step_1",
        project_id="test_workflow",
        result_summary="result: 5"
    )
    
    assert notif_id is not None, "Notification ID should be returned"
    
    notifications = get_notifications(project_id="test_workflow")
    assert len(notifications) == 1, f"Expected 1 notification, got {len(notifications)}"
    
    notif = notifications[0]
    assert notif["type"] == "SUCCESS"
    assert notif["category"] == "EXECUTION"
    assert "step_1" in notif["message"]
    assert notif["project_id"] == "test_workflow"
    
    print("TEST 1 (SUCCESS):", notif)


# ─── TEST 2: FAILURE NOTIFICATION ──────────────────────────────────────────────

def test_failure_notification():
    """
    Step failure → ERROR notification created
    """
    clear_notifications()
    
    notif_id = notify_step_failure(
        step_id="step_2",
        project_id="test_workflow",
        reason="division_by_zero"
    )
    
    assert notif_id is not None
    
    notifications = get_notifications(project_id="test_workflow")
    assert len(notifications) == 1
    
    notif = notifications[0]
    assert notif["type"] == "ERROR"
    assert notif["category"] == "EXECUTION"
    assert "step_2" in notif["message"]
    assert "division_by_zero" in notif["message"]
    
    print("TEST 2 (FAILURE):", notif)


# ─── TEST 3: GOVERNANCE RETRY NOTIFICATION ───────────────────────────────────

def test_governance_retry_notification():
    """
    Governance retry → WARNING notification created
    """
    clear_notifications()
    
    notif_id = notify_governance_retry(
        step_id="step_3",
        project_id="test_workflow",
        retry_count=2
    )
    
    assert notif_id is not None
    
    notifications = get_notifications(project_id="test_workflow")
    assert len(notifications) == 1
    
    notif = notifications[0]
    assert notif["type"] == "WARNING"
    assert notif["category"] == "GOVERNANCE"
    assert "step_3" in notif["message"]
    assert notif["metadata"].get("retry_count") == 2
    
    print("TEST 3 (GOVERNANCE RETRY):", notif)


# ─── TEST 4: GOVERNANCE ESCALATION NOTIFICATION ────────────────────────────

def test_governance_escalation_notification():
    """
    Governance escalation → ERROR notification created
    """
    clear_notifications()
    
    notif_id = notify_governance_escalation(
        step_id="step_4",
        project_id="test_workflow",
        reason="max_retries_reached"
    )
    
    assert notif_id is not None
    
    notifications = get_notifications(project_id="test_workflow")
    assert len(notifications) == 1
    
    notif = notifications[0]
    assert notif["type"] == "ERROR"
    assert notif["category"] == "GOVERNANCE"
    assert "step_4" in notif["message"]
    
    print("TEST 4 (GOVERNANCE ESCALATION):", notif)


# ─── TEST 5: APPROVAL REQUIRED NOTIFICATION ──────────────────────────────────

def test_approval_required_notification():
    """
    Approval required → WARNING notification created
    """
    clear_notifications()
    
    notif_id = notify_approval_required(
        step_id="step_5",
        project_id="test_workflow",
        risk_level="HIGH"
    )
    
    assert notif_id is not None
    
    notifications = get_notifications(project_id="test_workflow")
    assert len(notifications) == 1
    
    notif = notifications[0]
    assert notif["type"] == "WARNING"
    assert notif["category"] == "GOVERNANCE"
    assert "step_5" in notif["message"]
    assert "HIGH" in notif["message"]
    assert notif["metadata"].get("risk_level") == "HIGH"
    
    print("TEST 5 (APPROVAL REQUIRED):", notif)


# ─── TEST 6: FILTER LEVEL ───────────────────────────────────────────────────

def test_filter_level_high():
    """
    HIGH filter level → only ERROR notifications
    """
    clear_notifications()
    set_filter_level(FilterLevel.HIGH)
    
    # INFO should be filtered
    notify(NotificationType.INFO, NotificationCategory.SYSTEM, "info message")
    # ERROR should pass
    notify(NotificationType.ERROR, NotificationCategory.EXECUTION, "error message")
    # SUCCESS should be filtered
    notify(NotificationType.SUCCESS, NotificationCategory.EXECUTION, "success message")
    
    notifications = get_notifications()
    
    # Only ERROR should be present
    assert len(notifications) == 1, f"Expected 1 notification with HIGH filter, got {len(notifications)}"
    assert notifications[0]["type"] == "ERROR"
    
    # Reset filter
    set_filter_level(FilterLevel.LOW)
    
    print("TEST 6 (FILTER HIGH):", len(notifications), "notifications")


def test_filter_level_medium():
    """
    MEDIUM filter level → WARNING, ERROR, SUCCESS only
    """
    clear_notifications()
    set_filter_level(FilterLevel.MEDIUM)
    
    notify(NotificationType.INFO, NotificationCategory.SYSTEM, "info message")
    notify(NotificationType.WARNING, NotificationCategory.GOVERNANCE, "warning message")
    notify(NotificationType.ERROR, NotificationCategory.EXECUTION, "error message")
    notify(NotificationType.SUCCESS, NotificationCategory.EXECUTION, "success message")
    
    notifications = get_notifications()
    
    # INFO should be filtered, others should pass
    assert len(notifications) == 3, f"Expected 3 notifications with MEDIUM filter, got {len(notifications)}"
    types = {n["type"] for n in notifications}
    assert "INFO" not in types
    assert "WARNING" in types
    assert "ERROR" in types
    assert "SUCCESS" in types
    
    # Reset filter
    set_filter_level(FilterLevel.LOW)
    
    print("TEST 6b (FILTER MEDIUM):", len(notifications), "notifications")


# ─── TEST 7: NOTIFICATION STRUCTURE ──────────────────────────────────────────

def test_notification_structure():
    """
    Notification has all required fields
    """
    clear_notifications()
    
    notif_id = notify(
        notification_type=NotificationType.SUCCESS,
        category=NotificationCategory.EXECUTION,
        message="Test message",
        project_id="test_project",
        step_id="test_step",
        metadata={"key": "value"}
    )
    
    assert notif_id is not None
    
    notifications = get_notifications()
    assert len(notifications) == 1
    
    notif = notifications[0]
    assert "id" in notif
    assert "type" in notif
    assert "category" in notif
    assert "message" in notif
    assert "timestamp" in notif
    assert "project_id" in notif
    assert "step_id" in notif
    assert "metadata" in notif
    
    print("TEST 7 (STRUCTURE): all fields present")


# ─── TEST 8: OUTPUT ONLY (NO CONTROL IMPACT) ────────────────────────────────

def test_notification_output_only():
    """
    VERIFY: notify() returns ID only, no control signal
    """
    result = notify(
        notification_type=NotificationType.INFO,
        category=NotificationCategory.SYSTEM,
        message="Test"
    )
    
    # Should return string ID or None
    assert result is None or isinstance(result, str)
    
    # Should never return a dict, bool, or any control signal
    assert not isinstance(result, dict)
    assert not isinstance(result, bool)
    
    print("TEST 8 (OUTPUT ONLY): returns ID only")


# ─── TEST 9: FAILURE ISOLATION ─────────────────────────────────────────────

def test_notification_failure_isolated():
    """
    VERIFY: Invalid notification data doesn't crash system
    """
    # These should not raise exceptions
    try:
        notify(None, None, None)  # Invalid types
        notify("invalid_type", "invalid_category", "")  # Invalid enum values
        # Should complete without exception
        assert True
    except Exception as e:
        pytest.fail(f"Notification failure should be isolated, got: {e}")
    
    print("TEST 9 (FAILURE ISOLATED): no exceptions raised")


# ─── TEST 10: CLEAR NOTIFICATIONS ────────────────────────────────────────────

def test_clear_notifications():
    """
    VERIFY: clear_notifications() works per project and all
    """
    clear_notifications()
    
    # Add notifications for two projects
    notify(NotificationType.INFO, NotificationCategory.SYSTEM, "msg1", project_id="proj_a")
    notify(NotificationType.INFO, NotificationCategory.SYSTEM, "msg2", project_id="proj_b")
    
    # Clear only proj_a
    clear_notifications(project_id="proj_a")
    
    notifs_a = get_notifications(project_id="proj_a")
    notifs_b = get_notifications(project_id="proj_b")
    
    assert len(notifs_a) == 0, "proj_a should be cleared"
    assert len(notifs_b) == 1, "proj_b should remain"
    
    # Clear all
    clear_notifications()
    notifs_all = get_notifications()
    assert len(notifs_all) == 0, "All should be cleared"
    
    print("TEST 10 (CLEAR): per-project and global clear work")
