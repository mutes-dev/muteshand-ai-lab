"""
notification_manager.py — Contract-Safe Notification System (ISSUE-096B)

Per NOTIFICATION_CONTRACT_V1:
- Backend-authored notification identity
- Notifications inform; they do not decide
- Notification dismissal is not approval
- Sensitive data must not be exposed in title/message

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
import threading
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from enum import Enum

# FAILURE-ISOLATED: trace_collector import
try:
    from system.orchestrator import trace_collector as _trace_collector
except Exception:
    _trace_collector = None


class NotificationSeverity(str, Enum):
    """Notification severity per NOTIFICATION_CONTRACT_V1 §6."""
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class NotificationType(str, Enum):
    """Notification type per NOTIFICATION_CONTRACT_V1 §5."""
    APPROVAL_REQUIRED = "approval_required"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_BLOCKED = "workflow_blocked"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    WORKFLOW_RECOVERED = "workflow_recovered"
    WORKFLOW_RETRY_AVAILABLE = "workflow_retry_available"
    STEP_FAILED = "step_failed"
    STEP_BLOCKED = "step_blocked"
    GOVERNANCE_ESCALATION = "governance_escalation"
    CONFLICT_DETECTED = "conflict_detected"
    PRIVACY_APPROVAL_REQUIRED = "privacy_approval_required"
    EXTERNAL_CALL_WARNING = "external_call_warning"
    TOOL_FAILURE = "tool_failure"
    MEMORY_WARNING = "memory_warning"
    LEARNING_SUGGESTION = "learning_suggestion"
    PERFORMANCE_WARNING = "performance_warning"
    SYSTEM_WARNING = "system_warning"
    USER_CONTROL_REQUIRED = "user_control_required"


class NotificationStatus(str, Enum):
    """Notification status per NOTIFICATION_CONTRACT_V1 §7."""
    UNREAD = "UNREAD"
    READ = "READ"
    DISMISSED = "DISMISSED"
    EXPIRED = "EXPIRED"


class NotificationSource(str, Enum):
    """Notification source per NOTIFICATION_CONTRACT_V1 §8."""
    RUNTIME = "runtime"
    GOVERNANCE = "governance"
    APPROVAL = "approval"
    PROJECTION = "projection"
    MEMORY = "memory"
    AGENT = "agent"
    TOOL = "tool"
    SYSTEM = "system"
    PRIVACY = "privacy"
    PERFORMANCE = "performance"


class NotificationCategory(str, Enum):
    """Notification source categories (legacy compatibility)."""
    EXECUTION = "EXECUTION"
    GOVERNANCE = "GOVERNANCE"
    DRIFT = "DRIFT"
    MEMORY = "MEMORY"
    SYSTEM = "SYSTEM"


class FilterLevel(str, Enum):
    """Notification filtering levels per SYSTEM_GOALS_V2."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# Global notification state (per-process, in-memory)
# Per NOTIFICATION_CONTRACT_V1 §13: In-memory model allowed for Sprint 7B
_notifications: List[Dict[str, Any]] = []
_notifications_lock = threading.Lock()
_filter_level: FilterLevel = FilterLevel.LOW
_max_notifications: int = 1000


def _severity_from_legacy_type(notification_type: NotificationType) -> NotificationSeverity:
    """Map legacy/emission type to contract severity."""
    mapping = {
        NotificationType.APPROVAL_REQUIRED: NotificationSeverity.WARNING,
        NotificationType.WORKFLOW_COMPLETED: NotificationSeverity.SUCCESS,
        NotificationType.WORKFLOW_FAILED: NotificationSeverity.ERROR,
        NotificationType.WORKFLOW_BLOCKED: NotificationSeverity.WARNING,
        NotificationType.WORKFLOW_CANCELLED: NotificationSeverity.INFO,
        NotificationType.WORKFLOW_RECOVERED: NotificationSeverity.SUCCESS,
        NotificationType.WORKFLOW_RETRY_AVAILABLE: NotificationSeverity.WARNING,
        NotificationType.STEP_FAILED: NotificationSeverity.ERROR,
        NotificationType.STEP_BLOCKED: NotificationSeverity.WARNING,
        NotificationType.GOVERNANCE_ESCALATION: NotificationSeverity.ERROR,
        NotificationType.CONFLICT_DETECTED: NotificationSeverity.WARNING,
        NotificationType.PRIVACY_APPROVAL_REQUIRED: NotificationSeverity.CRITICAL,
        NotificationType.EXTERNAL_CALL_WARNING: NotificationSeverity.WARNING,
        NotificationType.TOOL_FAILURE: NotificationSeverity.ERROR,
        NotificationType.MEMORY_WARNING: NotificationSeverity.WARNING,
        NotificationType.LEARNING_SUGGESTION: NotificationSeverity.INFO,
        NotificationType.PERFORMANCE_WARNING: NotificationSeverity.WARNING,
        NotificationType.SYSTEM_WARNING: NotificationSeverity.WARNING,
    }
    return mapping.get(notification_type, NotificationSeverity.INFO)


def _should_notify(severity: NotificationSeverity) -> bool:
    """Check if notification should be emitted based on filter level."""
    global _filter_level
    if _filter_level == FilterLevel.LOW:
        return True
    elif _filter_level == FilterLevel.MEDIUM:
        return severity in (NotificationSeverity.WARNING, NotificationSeverity.ERROR, NotificationSeverity.CRITICAL, NotificationSeverity.SUCCESS)
    elif _filter_level == FilterLevel.HIGH:
        return severity in (NotificationSeverity.ERROR, NotificationSeverity.CRITICAL)
    return True


def _emit_notification_trace(notification: Dict[str, Any]) -> None:
    """Emit notification_created trace event."""
    global _trace_collector
    if _trace_collector is None:
        return
    try:
        _tc = _trace_collector.get_collector(notification.get("workflow_id"))
        if _tc:
            _tc._safe(
                "notification_created",
                lambda: _tc.steps.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "project_id": notification.get("workflow_id"),
                    "step_id": notification.get("step_id"),
                    "level": "NORMAL",
                    "event": "notification_created",
                    "data": {
                        "notification_id": notification.get("notification_id"),
                        "workflow_id": notification.get("workflow_id"),
                        "step_id": notification.get("step_id"),
                        "type": notification.get("type"),
                        "severity": notification.get("severity"),
                        "source": notification.get("source"),
                        "title": notification.get("title"),
                        "message": (notification.get("message") or "")[:100],
                    }
                })
            )
    except Exception:
        pass


def notify(
    notification_type: NotificationType,
    severity: Optional[NotificationSeverity] = None,
    title: str = "",
    message: str = "",
    workflow_id: Optional[str] = None,
    step_id: Optional[str] = None,
    source: NotificationSource = NotificationSource.SYSTEM,
    action: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    # Legacy compatibility args
    category: Optional[NotificationCategory] = None,
    project_id: Optional[str] = None,
) -> Optional[str]:
    """
    Emit a contract-safe notification.

    Per NOTIFICATION_CONTRACT_V1:
    - Backend-authored notification identity
    - Stable notification_id
    - All required fields populated

    Args:
        notification_type: Contract type per NOTIFICATION_CONTRACT_V1 §5
        severity: If omitted, inferred from type
        title: Short human-readable title
        message: Human-readable message (no secrets/API keys/full paths)
        workflow_id: Target workflow
        step_id: Target step
        source: Source system per §8
        action: Optional action dict (e.g., {"type": "approval", "approval_id": "..."})
        metadata: Additional context (may contain more detail)
        category: Legacy compatibility — maps to source if provided
        project_id: Legacy compatibility — maps to workflow_id if provided

    Returns:
        notification_id or None if filtered/suppressed
    """
    global _notifications, _notifications_lock, _max_notifications

    try:
        with _notifications_lock:
            # Legacy compatibility: project_id -> workflow_id
            effective_workflow_id = workflow_id or project_id or "unknown"
            effective_source = source
            if category and not source:
                source_map = {
                    NotificationCategory.EXECUTION: NotificationSource.RUNTIME,
                    NotificationCategory.GOVERNANCE: NotificationSource.GOVERNANCE,
                    NotificationCategory.DRIFT: NotificationSource.SYSTEM,
                    NotificationCategory.MEMORY: NotificationSource.MEMORY,
                    NotificationCategory.SYSTEM: NotificationSource.SYSTEM,
                }
                effective_source = source_map.get(category, NotificationSource.SYSTEM)

            # Derive severity if not provided
            actual_severity = severity or _severity_from_legacy_type(notification_type)

            # Filtering
            if not _should_notify(actual_severity):
                return None

            # Sensitive data guard: do not put secrets in title/message
            # (Caller responsibility; we enforce by not adding anything extra)
            now = datetime.now(timezone.utc).isoformat()

            notification = {
                "notification_id": str(uuid.uuid4()),
                "workflow_id": effective_workflow_id,
                "step_id": step_id,
                "type": notification_type.value,
                "severity": actual_severity.value,
                "title": title or message[:60] if message else notification_type.value.replace("_", " ").title(),
                "message": message or title,
                "status": NotificationStatus.UNREAD.value,
                "source": effective_source.value,
                "created_at": now,
                "updated_at": now,
                "expires_at": None,
                "action": action or {},
                "metadata": metadata or {},
                # Legacy compatibility fields
                "id": None,  # Will be set below to notification_id for backward compat
                "category": (category.value if category else None),
                "project_id": effective_workflow_id,
                "timestamp": now,
            }
            notification["id"] = notification["notification_id"]

            # Prevent unbounded growth
            if len(_notifications) >= _max_notifications:
                _notifications.pop(0)

            _notifications.append(notification)

        # TRACE: notification_created (outside lock to avoid holding lock during I/O)
        _emit_notification_trace(notification)

        return notification["notification_id"]
    except Exception:
        # FAILURE-ISOLATED
        return None


def queue_notification(notification: Dict[str, Any]) -> Optional[str]:
    """
    Queue a pre-formatted notification dict (legacy compatibility).
    Upgrades legacy shape to contract shape where possible.
    """
    global _notifications, _notifications_lock, _max_notifications
    try:
        with _notifications_lock:
            # Migrate legacy fields to contract fields if missing
            if "notification_id" not in notification and "id" in notification:
                notification["notification_id"] = notification["id"]
            if "notification_id" not in notification:
                notification["notification_id"] = str(uuid.uuid4())
            if "id" not in notification:
                notification["id"] = notification["notification_id"]
            if "type" not in notification and "category" in notification:
                notification["type"] = notification["category"]
            if "severity" not in notification and "type" in notification:
                try:
                    ntype = NotificationType(notification["type"])
                    notification["severity"] = _severity_from_legacy_type(ntype).value
                except Exception:
                    notification["severity"] = NotificationSeverity.INFO.value
            if "status" not in notification:
                notification["status"] = NotificationStatus.UNREAD.value
            if "source" not in notification and "category" in notification:
                notification["source"] = notification["category"]
            if "created_at" not in notification:
                notification["created_at"] = datetime.now(timezone.utc).isoformat()
            if "updated_at" not in notification:
                notification["updated_at"] = notification["created_at"]
            if "title" not in notification:
                notification["title"] = notification.get("message", "")[:60]
            if "workflow_id" not in notification and "project_id" in notification:
                notification["workflow_id"] = notification["project_id"]
            if "action" not in notification:
                notification["action"] = {}
            if "metadata" not in notification:
                notification["metadata"] = {}

            # Apply filtering
            try:
                sev = NotificationSeverity(notification.get("severity", "INFO"))
                if not _should_notify(sev):
                    return None
            except Exception:
                pass

            if len(_notifications) >= _max_notifications:
                _notifications.pop(0)

            _notifications.append(notification)
        _emit_notification_trace(notification)
        return notification["notification_id"]
    except Exception:
        return None


def get_notifications(
    workflow_id: Optional[str] = None,
    project_id: Optional[str] = None,
    category: Optional[NotificationCategory] = None,
    notification_type: Optional[NotificationType] = None,
    severity: Optional[NotificationSeverity] = None,
    status: Optional[NotificationStatus] = None,
    limit: int = 100,
    include_dismissed: bool = True,
) -> List[Dict[str, Any]]:
    """
    Retrieve notifications with optional filtering.
    Per NOTIFICATION_CONTRACT_V1 §12: supports workflow-scoped and global lookup.
    """
    global _notifications
    try:
        result = list(_notifications)
        effective_wid = workflow_id or project_id
        if effective_wid:
            result = [n for n in result if n.get("workflow_id") == effective_wid or n.get("project_id") == effective_wid]
        if category:
            result = [n for n in result if n.get("category") == category.value]
        if notification_type:
            result = [n for n in result if n.get("type") == notification_type.value]
        if severity:
            result = [n for n in result if n.get("severity") == severity.value]
        if status:
            result = [n for n in result if n.get("status") == status.value]
        if not include_dismissed:
            result = [n for n in result if n.get("status") != NotificationStatus.DISMISSED.value]
        # Newest first, limited
        return result[-limit:][::-1]
    except Exception:
        return []


def mark_notification_read(notification_id: str) -> bool:
    """
    Mark a notification as READ.
    Per NOTIFICATION_CONTRACT_V1 §7: read does NOT approve/reject/mutate workflow.
    """
    global _notifications, _notifications_lock
    try:
        with _notifications_lock:
            for n in _notifications:
                if n.get("notification_id") == notification_id:
                    n["status"] = NotificationStatus.READ.value
                    n["read_at"] = datetime.now(timezone.utc).isoformat()
                    n["updated_at"] = n["read_at"]
                # TRACE: notification_read (low-priority, failure-isolated)
                try:
                    if _trace_collector:
                        _tc = _trace_collector.get_collector(n.get("workflow_id"))
                        if _tc:
                            _tc._safe(
                                "notification_read",
                                lambda: _tc.steps.append({
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "project_id": n.get("workflow_id"),
                                    "step_id": n.get("step_id"),
                                    "level": "NORMAL",
                                    "event": "notification_read",
                                    "data": {
                                        "notification_id": notification_id,
                                        "workflow_id": n.get("workflow_id"),
                                        "step_id": n.get("step_id"),
                                    }
                                })
                            )
                except Exception:
                    pass
                return True
        return False
    except Exception:
        return False


def dismiss_notification(notification_id: str) -> bool:
    """
    Mark a notification as DISMISSED.
    Per NOTIFICATION_CONTRACT_V1 §7 + §10: dismissal != approval.
    Must NOT mutate workflow lifecycle, approval status, retry state, governance, or projection.
    """
    global _notifications, _notifications_lock
    try:
        with _notifications_lock:
            for n in _notifications:
                if n.get("notification_id") == notification_id:
                    n["status"] = NotificationStatus.DISMISSED.value
                    n["updated_at"] = datetime.now(timezone.utc).isoformat()
                # TRACE: notification_dismissed
                try:
                    if _trace_collector:
                        _tc = _trace_collector.get_collector(n.get("workflow_id"))
                        if _tc:
                            _tc._safe(
                                "notification_dismissed",
                                lambda: _tc.steps.append({
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "project_id": n.get("workflow_id"),
                                    "step_id": n.get("step_id"),
                                    "level": "NORMAL",
                                    "event": "notification_dismissed",
                                    "data": {
                                        "notification_id": notification_id,
                                        "workflow_id": n.get("workflow_id"),
                                        "step_id": n.get("step_id"),
                                    }
                                })
                            )
                except Exception:
                    pass
                return True
        return False
    except Exception:
        return False


def dismiss_notifications_for_control_id(control_id: str) -> int:
    """
    Dismiss all notifications associated with a user-control control_id.
    Per ISSUE-098KL: prevents stale banner after request is resolved.
    Must NOT mutate workflow lifecycle or approval status.
    """
    global _notifications, _notifications_lock
    count = 0
    try:
        with _notifications_lock:
            for n in _notifications:
                meta = n.get("metadata") or {}
                if meta.get("control_id") == control_id and n.get("status") != NotificationStatus.DISMISSED.value:
                    n["status"] = NotificationStatus.DISMISSED.value
                    n["updated_at"] = datetime.now(timezone.utc).isoformat()
                    count += 1
        return count
    except Exception:
        return 0


def get_unread_count(workflow_id: Optional[str] = None) -> int:
    """Return count of UNREAD notifications, optionally filtered by workflow."""
    global _notifications, _notifications_lock
    try:
        with _notifications_lock:
            count = 0
            for n in _notifications:
                if n.get("status") == NotificationStatus.UNREAD.value:
                    if workflow_id is None or n.get("workflow_id") == workflow_id or n.get("project_id") == workflow_id:
                        count += 1
            return count
    except Exception:
        return 0


def clear_notifications(workflow_id: Optional[str] = None, project_id: Optional[str] = None) -> None:
    """Clear notifications. Legacy compatibility supports both workflow_id and project_id."""
    global _notifications, _notifications_lock
    try:
        with _notifications_lock:
            effective_id = workflow_id or project_id
            if effective_id:
                _notifications[:] = [
                    n for n in _notifications
                    if n.get("workflow_id") != effective_id and n.get("project_id") != effective_id
                ]
            else:
                _notifications.clear()
    except Exception:
        pass


def set_filter_level(level: FilterLevel) -> None:
    """Set notification filter level."""
    global _filter_level
    try:
        _filter_level = level
    except Exception:
        pass


def get_filter_level() -> FilterLevel:
    """Get current filter level."""
    return _filter_level


class NotificationManager:
    """Per-workflow notification manager for scoped notifications."""

    def __init__(self, project_id: str):
        self.project_id = project_id

    def notify(
        self,
        notification_type: NotificationType,
        severity: Optional[NotificationSeverity] = None,
        title: str = "",
        message: str = "",
        step_id: Optional[str] = None,
        source: NotificationSource = NotificationSource.SYSTEM,
        action: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Scoped notification for this project."""
        return notify(
            notification_type=notification_type,
            severity=severity,
            title=title,
            message=message,
            workflow_id=self.project_id,
            step_id=step_id,
            source=source,
            action=action,
            metadata=metadata,
        )

    def get_notifications(
        self,
        notification_type: Optional[NotificationType] = None,
        severity: Optional[NotificationSeverity] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get notifications scoped to this project."""
        return get_notifications(
            workflow_id=self.project_id,
            notification_type=notification_type,
            severity=severity,
            limit=limit,
        )


# Convenience functions for common notification patterns

def notify_step_success(step_id: str, project_id: str, result_summary: str = "") -> Optional[str]:
    """Convenience: Step execution succeeded."""
    message = f"Step {step_id} completed successfully"
    if result_summary:
        message += f": {result_summary}"
    return notify(
        notification_type=NotificationType.WORKFLOW_COMPLETED,
        severity=NotificationSeverity.SUCCESS,
        title=f"Step {step_id} succeeded",
        message=message,
        workflow_id=project_id,
        step_id=step_id,
        source=NotificationSource.RUNTIME,
    )


def notify_step_failure(step_id: str, project_id: str, reason: str = "") -> Optional[str]:
    """Convenience: Step execution failed."""
    message = f"Step {step_id} failed"
    if reason:
        message += f": {reason}"
    return notify(
        notification_type=NotificationType.STEP_FAILED,
        severity=NotificationSeverity.ERROR,
        title=f"Step {step_id} failed",
        message=message,
        workflow_id=project_id,
        step_id=step_id,
        source=NotificationSource.RUNTIME,
        metadata={"failure_reason": reason},
    )


def notify_governance_retry(step_id: str, project_id: str, retry_count: int) -> Optional[str]:
    """Convenience: Governance decided retry."""
    return notify(
        notification_type=NotificationType.WORKFLOW_RETRY_AVAILABLE,
        severity=NotificationSeverity.WARNING,
        title=f"Retrying step {step_id}",
        message=f"Retrying step {step_id} (attempt {retry_count})",
        workflow_id=project_id,
        step_id=step_id,
        source=NotificationSource.GOVERNANCE,
        metadata={"retry_count": retry_count},
    )


def notify_governance_escalation(step_id: str, project_id: str, reason: str = "") -> Optional[str]:
    """Convenience: Governance decided escalation."""
    message = f"Step {step_id} escalated"
    if reason:
        message += f": {reason}"
    return notify(
        notification_type=NotificationType.GOVERNANCE_ESCALATION,
        severity=NotificationSeverity.ERROR,
        title=f"Step {step_id} escalated",
        message=message,
        workflow_id=project_id,
        step_id=step_id,
        source=NotificationSource.GOVERNANCE,
        metadata={"escalation_reason": reason},
    )


def notify_approval_required(
    step_id: str,
    project_id: str,
    risk_level: str = "",
    approval_id: Optional[str] = None,
) -> Optional[str]:
    """Convenience: Approval required for step (contract-safe)."""
    message = f"Approval required for step {step_id}"
    if risk_level:
        message += f" (risk: {risk_level})"
    action = {}
    if approval_id:
        action = {"type": "approval", "approval_id": approval_id}
    return notify(
        notification_type=NotificationType.APPROVAL_REQUIRED,
        severity=NotificationSeverity.WARNING,
        title=f"Approval required: step {step_id}",
        message=message,
        workflow_id=project_id,
        step_id=step_id,
        source=NotificationSource.GOVERNANCE,
        action=action,
        metadata={"risk_level": risk_level, "approval_id": approval_id},
    )


def notify_workflow_complete(project_id: str, status: str = "success") -> Optional[str]:
    """Convenience: Workflow completed."""
    notif_type = NotificationType.WORKFLOW_COMPLETED if status == "success" else NotificationType.WORKFLOW_FAILED
    sev = NotificationSeverity.SUCCESS if status == "success" else NotificationSeverity.ERROR
    return notify(
        notification_type=notif_type,
        severity=sev,
        title=f"Workflow {status}",
        message=f"Workflow {project_id} completed with status: {status}",
        workflow_id=project_id,
        source=NotificationSource.RUNTIME,
    )


def notify_user_control_required(
    step_id: str,
    project_id: str,
    risk_level: str = "",
    control_id: Optional[str] = None,
    requested_action: str = "",
) -> Optional[str]:
    """
    Convenience: User control / override / force-execution required for step (contract-safe).

    Per USER_CONTROL_CONTRACT_V2 §16:
    - Notification dismissal does NOT approve, reject, or apply user-control.
    - Notification is output/display only.
    """
    message = f"User control required for step {step_id}"
    if risk_level:
        message += f" (risk: {risk_level})"
    action = {}
    if control_id:
        action = {"type": "user_control", "control_id": control_id}
    return notify(
        notification_type=NotificationType.USER_CONTROL_REQUIRED,
        severity=NotificationSeverity.WARNING,
        title=f"User control required: step {step_id}",
        message=message,
        workflow_id=project_id,
        step_id=step_id,
        source=NotificationSource.GOVERNANCE,
        action=action,
        metadata={
            "risk_level": risk_level,
            "control_id": control_id,
            "requested_action": requested_action,
        },
    )
