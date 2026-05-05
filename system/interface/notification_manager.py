"""
notification_manager.py — Phase 3C Notification System (M10)

Per HAND_ARCHITECTURE_V2 Section 14:
- Notify for: approvals, failures, completion, conflicts
- Smart filtering per SYSTEM_GOALS_V2 Section 24

Per AUTHORITY_MODEL.txt and CONTROL_MODEL.txt:
- Notifications are OUTPUT ONLY
- NO authority granted
- NO control flow modification
- MUST NOT influence execution or governance decisions

Per TRACE_LOGGING_CONTRACT_V1:
- Notifications are secondary to trace
- Trace remains primary observability
- Notifications are user-facing convenience only

FAILURE-ISOLATED:
- All notification operations wrapped in try/except
- Notification failure MUST NOT affect execution
"""

import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime
from enum import Enum


class NotificationType(str, Enum):
    """Notification severity/type levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"


class NotificationCategory(str, Enum):
    """Notification source categories."""
    EXECUTION = "EXECUTION"
    GOVERNANCE = "GOVERNANCE"
    DRIFT = "DRIFT"
    MEMORY = "MEMORY"
    SYSTEM = "SYSTEM"


class FilterLevel(str, Enum):
    """Notification filtering levels per SYSTEM_GOALS_V2."""
    LOW = "LOW"      # All notifications
    MEDIUM = "MEDIUM"  # Warnings, errors, success
    HIGH = "HIGH"     # Errors only


# Global notification state (per-process, not per-workflow)
# Per ORCHESTRATOR_CONTRACT_V2: notifications are advisory output only
_notifications: List[Dict[str, Any]] = []
_filter_level: FilterLevel = FilterLevel.LOW
_max_notifications: int = 1000  # Prevent unbounded growth


def _should_notify(notification_type: NotificationType) -> bool:
    """
    Check if notification should be emitted based on filter level.
    
    Per SYSTEM_GOALS_V2 Section 24: Smart filtering
    """
    global _filter_level
    
    if _filter_level == FilterLevel.LOW:
        return True
    elif _filter_level == FilterLevel.MEDIUM:
        return notification_type in (NotificationType.WARNING, NotificationType.ERROR, NotificationType.SUCCESS)
    elif _filter_level == FilterLevel.HIGH:
        return notification_type == NotificationType.ERROR
    return True


def notify(
    notification_type: NotificationType,
    category: NotificationCategory,
    message: str,
    project_id: Optional[str] = None,
    step_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Emit a notification immediately.
    
    Per AUTHORITY_MODEL:
    - Output only — no control influence
    - Fire-and-forget — return value is notification ID only
    - Failure-isolated — exceptions absorbed
    
    Args:
        notification_type: INFO | WARNING | ERROR | SUCCESS
        category: EXECUTION | GOVERNANCE | DRIFT | MEMORY | SYSTEM
        message: Human-readable notification text
        project_id: Optional project/workflow identifier
        step_id: Optional step identifier
        metadata: Optional additional context
    
    Returns:
        Notification ID (uuid) or None if filtered/suppressed
    """
    global _notifications, _max_notifications
    
    try:
        # Apply filtering
        if not _should_notify(notification_type):
            return None
        
        notification = {
            "id": str(uuid.uuid4()),
            "type": notification_type.value,
            "category": category.value,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
            "project_id": project_id or "unknown",
            "step_id": step_id,
            "metadata": metadata or {}
        }
        
        # Prevent unbounded growth
        if len(_notifications) >= _max_notifications:
            _notifications.pop(0)  # Remove oldest
        
        _notifications.append(notification)
        
        return notification["id"]
    except Exception:
        # FAILURE-ISOLATED: Notification failure must not affect execution
        return None


def queue_notification(notification: Dict[str, Any]) -> Optional[str]:
    """
    Queue a pre-formatted notification dict.
    
    Used for batching or when notification is pre-constructed.
    
    Args:
        notification: Dict with notification data (must include type, category, message)
    
    Returns:
        Notification ID or None
    """
    global _notifications, _max_notifications
    
    try:
        # Validate required fields
        if not notification.get("type") or not notification.get("message"):
            return None
        
        # Apply filtering
        notif_type = NotificationType(notification.get("type", "INFO"))
        if not _should_notify(notif_type):
            return None
        
        # Ensure ID and timestamp
        notification["id"] = notification.get("id") or str(uuid.uuid4())
        notification["timestamp"] = notification.get("timestamp") or datetime.utcnow().isoformat()
        
        # Prevent unbounded growth
        if len(_notifications) >= _max_notifications:
            _notifications.pop(0)
        
        _notifications.append(notification)
        
        return notification["id"]
    except Exception:
        # FAILURE-ISOLATED
        return None


def get_notifications(
    project_id: Optional[str] = None,
    category: Optional[NotificationCategory] = None,
    notification_type: Optional[NotificationType] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Retrieve notifications with optional filtering.
    
    Per TRACE_LOGGING_CONTRACT_V1:
    - Notifications are secondary to trace
    - This is for UI/query purposes only
    
    Args:
        project_id: Filter by project
        category: Filter by category
        notification_type: Filter by type
        limit: Maximum results
    
    Returns:
        List of notification dicts (newest first)
    """
    global _notifications
    
    try:
        result = list(_notifications)
        
        # Apply filters
        if project_id:
            result = [n for n in result if n.get("project_id") == project_id]
        if category:
            result = [n for n in result if n.get("category") == category.value]
        if notification_type:
            result = [n for n in result if n.get("type") == notification_type.value]
        
        # Return newest first, limited
        return result[-limit:][::-1]
    except Exception:
        # FAILURE-ISOLATED: Query failure returns empty list
        return []


def clear_notifications(project_id: Optional[str] = None) -> None:
    """
    Clear notifications.
    
    Args:
        project_id: If provided, clear only for that project; else clear all
    """
    global _notifications
    
    try:
        if project_id:
            _notifications = [n for n in _notifications if n.get("project_id") != project_id]
        else:
            _notifications = []
    except Exception:
        # FAILURE-ISOLATED
        pass


def set_filter_level(level: FilterLevel) -> None:
    """
    Set notification filter level.
    
    Per SYSTEM_GOALS_V2 Section 24: Smart filtering
    
    Args:
        level: LOW (all), MEDIUM (warnings+), HIGH (errors only)
    """
    global _filter_level
    
    try:
        _filter_level = level
    except Exception:
        pass


def get_filter_level() -> FilterLevel:
    """Get current filter level."""
    return _filter_level


class NotificationManager:
    """
    Per-workflow notification manager for scoped notifications.
    
    Per ORCHESTRATOR_CONTRACT_V2:
    - Notifications are advisory output only
    - No control flow influence
    - Failure-isolated
    """
    
    def __init__(self, project_id: str):
        self.project_id = project_id
    
    def notify(
        self,
        notification_type: NotificationType,
        category: NotificationCategory,
        message: str,
        step_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Scoped notification for this project."""
        return notify(
            notification_type=notification_type,
            category=category,
            message=message,
            project_id=self.project_id,
            step_id=step_id,
            metadata=metadata
        )
    
    def get_notifications(
        self,
        category: Optional[NotificationCategory] = None,
        notification_type: Optional[NotificationType] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get notifications scoped to this project."""
        return get_notifications(
            project_id=self.project_id,
            category=category,
            notification_type=notification_type,
            limit=limit
        )
    
    def clear(self) -> None:
        """Clear notifications for this project."""
        clear_notifications(project_id=self.project_id)


# Convenience functions for common notification patterns

def notify_step_success(step_id: str, project_id: str, result_summary: str = "") -> Optional[str]:
    """Convenience: Step execution succeeded."""
    message = f"Step {step_id} completed successfully"
    if result_summary:
        message += f": {result_summary}"
    return notify(
        notification_type=NotificationType.SUCCESS,
        category=NotificationCategory.EXECUTION,
        message=message,
        project_id=project_id,
        step_id=step_id
    )


def notify_step_failure(step_id: str, project_id: str, reason: str = "") -> Optional[str]:
    """Convenience: Step execution failed."""
    message = f"Step {step_id} failed"
    if reason:
        message += f": {reason}"
    return notify(
        notification_type=NotificationType.ERROR,
        category=NotificationCategory.EXECUTION,
        message=message,
        project_id=project_id,
        step_id=step_id
    )


def notify_governance_retry(step_id: str, project_id: str, retry_count: int) -> Optional[str]:
    """Convenience: Governance decided retry."""
    return notify(
        notification_type=NotificationType.WARNING,
        category=NotificationCategory.GOVERNANCE,
        message=f"Retrying step {step_id} (attempt {retry_count})",
        project_id=project_id,
        step_id=step_id,
        metadata={"retry_count": retry_count}
    )


def notify_governance_escalation(step_id: str, project_id: str, reason: str = "") -> Optional[str]:
    """Convenience: Governance decided escalation."""
    message = f"Step {step_id} escalated"
    if reason:
        message += f": {reason}"
    return notify(
        notification_type=NotificationType.ERROR,
        category=NotificationCategory.GOVERNANCE,
        message=message,
        project_id=project_id,
        step_id=step_id
    )


def notify_approval_required(step_id: str, project_id: str, risk_level: str = "") -> Optional[str]:
    """Convenience: Approval required for step."""
    message = f"Approval required for step {step_id}"
    if risk_level:
        message += f" (risk: {risk_level})"
    return notify(
        notification_type=NotificationType.WARNING,
        category=NotificationCategory.GOVERNANCE,
        message=message,
        project_id=project_id,
        step_id=step_id,
        metadata={"risk_level": risk_level}
    )


def notify_workflow_complete(project_id: str, status: str = "success") -> Optional[str]:
    """Convenience: Workflow completed."""
    notif_type = NotificationType.SUCCESS if status == "success" else NotificationType.ERROR
    return notify(
        notification_type=notif_type,
        category=NotificationCategory.EXECUTION,
        message=f"Workflow {project_id} completed with status: {status}",
        project_id=project_id
    )
