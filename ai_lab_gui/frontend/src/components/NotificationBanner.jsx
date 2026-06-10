import { useState, useEffect, useCallback } from "react";
import { api } from "../api.js";

// Severity priority for sorting notifications (highest first)
const SEVERITY_PRIORITY = {
  CRITICAL: 5,
  ERROR: 4,
  WARNING: 3,
  SUCCESS: 2,
  INFO: 1,
};

// Actionable notification types that deserve top-banner operator attention.
// Per ISSUE-096B Run 2 fix: routine step_success / info noise must not interrupt UI.
const ACTIONABLE_TYPES = new Set([
  "approval_required",
  "workflow_failed",
  "workflow_blocked",
  "step_failed",
  "governance_escalation",
  "workflow_retry_available",
  "conflict_detected",
  "privacy_approval_required",
  "external_call_warning",
  "tool_failure",
  "memory_warning",
  "performance_warning",
  "system_warning",
]);

const ALWAYS_SHOW_SEVERITIES = new Set(["CRITICAL", "ERROR", "WARNING"]);

function isBannerWorthy(n) {
  const type = n.type || "";
  const severity = n.severity || "INFO";
  // Always show CRITICAL/ERROR/WARNING
  if (ALWAYS_SHOW_SEVERITIES.has(severity)) return true;
  // Show actionable types regardless of severity
  if (ACTIONABLE_TYPES.has(type)) return true;
  // Block routine success/info noise (step success, workflow completed, learning suggestions, etc.)
  return false;
}

/**
 * NotificationBanner — ISSUE-096B Run 2
 * Minimal notification surface polling GET /notifications.
 *
 * - Polls every 5 seconds
 * - Shows the highest-severity unread notification
 * - Dismiss calls POST /notifications/{id}/dismiss
 * - Does NOT approve/reject/mutate workflow state
 * - approval action links to the approval surface but does not act as approval
 */
export default function NotificationBanner() {
  const [notifications, setNotifications] = useState([]);
  const [dismissingId, setDismissingId] = useState(null);
  const [error, setError] = useState(null);

  const loadNotifications = useCallback(async () => {
    try {
      const res = await api.getNotifications();
      const notifs = res.notifications ?? [];
      // Filter to UNREAD and banner-worthy (actionable/attention-only)
      const unread = notifs.filter(
        (n) => n.status === "UNREAD" && isBannerWorthy(n)
      );
      setNotifications(unread);
      setError(null);
    } catch (e) {
      console.log("[NotificationBanner:poll_error]", e.message);
    }
  }, []);

  useEffect(() => {
    loadNotifications();
    const id = setInterval(loadNotifications, 5000);
    return () => clearInterval(id);
  }, [loadNotifications]);

  async function handleDismiss(notification_id) {
    setDismissingId(notification_id);
    try {
      await api.dismissNotification(notification_id);
      await loadNotifications();
    } catch (e) {
      setError(e.message || "Failed to dismiss notification");
    } finally {
      setDismissingId(null);
    }
  }

  // Pick highest severity unread notification
  const top = notifications
    .slice()
    .sort(
      (a, b) =>
        (SEVERITY_PRIORITY[b.severity] || 0) -
        (SEVERITY_PRIORITY[a.severity] || 0)
    )[0];

  if (!top) return null;

  const isApprovalAction =
    top.action?.type === "approval" && top.action?.approval_id;

  const isUserControlAction =
    top.action?.type === "user_control" && top.action?.control_id;

  return (
    <div className={`notification-banner notification-banner--${top.severity?.toLowerCase() || "info"}`}>
      <div className="notification-banner__content">
        <span className="notification-banner__title">
          {top.title || top.type || "Notification"}
        </span>
        {top.message && (
          <span className="notification-banner__message">{top.message}</span>
        )}
        {isApprovalAction && (
          <span
            className="notification-banner__action-hint"
            title="Open the ApprovalPanel for this workflow to review — this banner does not approve or reject"
          >
            Review approval
          </span>
        )}
        {isUserControlAction && (
          <span
            className="notification-banner__action-hint"
            title="Open the UserControlPanel for this workflow to review — this banner does not accept or reject user-control"
          >
            Review user control
          </span>
        )}
      </div>
      <div className="notification-banner__actions">
        <button
          className="notification-banner__dismiss"
          onClick={() => handleDismiss(top.notification_id)}
          disabled={dismissingId === top.notification_id}
          title="Dismiss notification — this does not change workflow state"
        >
          {dismissingId === top.notification_id ? "…" : "✕"}
        </button>
      </div>
      {error && (
        <span className="notification-banner__error">{error}</span>
      )}
    </div>
  );
}
