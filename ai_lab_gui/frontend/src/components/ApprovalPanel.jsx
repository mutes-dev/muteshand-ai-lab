import { useState, useEffect } from "react";
import { api } from "../api.js";

// Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
// Frontend does NOT synthesize workflow ownership
// Backend provides authoritative workflow identity via projection

/**
 * ApprovalPanel — ISSUE-096B Run 2
 * Contract-safe approval surface using approval_id-keyed endpoints.
 *
 * - Polls GET /approvals/{workflow_id} for PENDING approvals
 * - Sends intent via POST /approvals/{approval_id}/approve or /reject
 * - Displays reason, risk_level, requested_action, details
 * - Does NOT mutate local workflow state — waits for backend/projection updates
 * - Handles stale/expired/already-resolved responses safely
 */
// AGENT-001J-FIX1: Events that warrant an immediate approval panel refresh.
// approval_created/resolved are the primary signals; others are broader hints.
const APPROVAL_REFRESH_EVENTS = new Set([
  "approval_created",
  "approval_resolved",
  "external_call_review_required",
  "projection_lifecycle_changed",
  "state_transition",
]);

export default function ApprovalPanel({ workflowId, onRequestProjectionRefresh = null }) {
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [submittedId, setSubmittedId] = useState(null);

  useEffect(() => {
    if (!workflowId) return;
    poll();
    const interval = setInterval(poll, 500);

    const handleEvent = (e) => {
      const event = e.detail || {};
      if (event.workflow_id !== workflowId) return;
      if (APPROVAL_REFRESH_EVENTS.has(event.event_type)) {
        poll();
      }
    };
    window.addEventListener("workflow_event", handleEvent);
    return () => {
      clearInterval(interval);
      window.removeEventListener("workflow_event", handleEvent);
    };
  }, [workflowId]);

  async function poll() {
    if (!workflowId) return;
    try {
      const res = await api.getApprovals(workflowId);
      setPending(res.pending ?? []);
      setError(null);
    } catch (e) {
      // Silent fail on poll — don't flash errors for background refresh
      console.log("[ApprovalPanel:poll_error]", e.message);
    }
  }

  async function handleDecision(approval_id, approved) {
    setError(null);
    setSubmittedId(approval_id);
    try {
      if (approved) {
        await api.approveById(approval_id);
      } else {
        await api.rejectById(approval_id);
      }
      // Refresh approval list immediately after successful intent dispatch
      await poll();
      // AGENT-001J-FIX1: Trigger authoritative projection refresh so the plan panel
      // converges without waiting for the next poll cycle.
      // NON-AUTHORITATIVE: signal only — backend remains the authority.
      if (onRequestProjectionRefresh) {
        onRequestProjectionRefresh();
        // Delayed catch-up refetch: handles event/projection-store races where the
        // projection snapshot is updated just after the first fetch.
        setTimeout(() => {
          try { onRequestProjectionRefresh(); } catch (_) { }
        }, 400);
      }
    } catch (e) {
      const msg = e.message || "";
      // Translate backend error codes to operator-friendly messages
      if (msg.includes("410") || msg.includes("expired") || msg.includes("EXPIRED")) {
        setError("This approval request has expired. The workflow may need to be restarted.");
      } else if (msg.includes("409") || msg.includes("already resolved")) {
        setError("This approval has already been resolved.");
      } else if (msg.includes("404") || msg.includes("not found")) {
        setError("Approval request not found. It may have been cancelled.");
      } else {
        setError(msg);
      }
    } finally {
      setSubmittedId(null);
    }
  }

  if (!workflowId) return null;
  if (loading && pending.length === 0) {
    return (
      <section className="panel approval-panel">
        <h2>⚠ Approval Required</h2>
        <div className="approval-loading">Loading approvals…</div>
      </section>
    );
  }
  if (pending.length === 0) return null;

  return (
    <section className="panel approval-panel">
      <h2>⚠ Approval Required</h2>
      {error && <div className="error-badge">⚠ {error}</div>}
      {pending.map((req) => (
        <div key={req.approval_id} className="approval-item">
          <div className="approval-meta">
            <span className="approval-label">Step:</span>
            <span>{req.step_id ?? "—"}</span>
          </div>
          <div className="approval-meta">
            <span className="approval-label">Reason:</span>
            <span>{req.reason ?? "—"}</span>
          </div>
          <div className="approval-meta">
            <span className="approval-label">Action:</span>
            <span>{req.requested_action ?? "—"}</span>
          </div>
          <div className="approval-meta">
            <span className="approval-label">Risk:</span>
            <span className={`risk-badge ${(req.risk_level ?? "").toLowerCase()}`}>
              {req.risk_level ?? "—"}
            </span>
          </div>
          {req.details && Object.keys(req.details).length > 0 && (
            <div className="approval-meta approval-details">
              <span className="approval-label">Details:</span>
              <span className="mono">
                {typeof req.details === "string"
                  ? req.details
                  : JSON.stringify(req.details)}
              </span>
            </div>
          )}
          <div className="approval-meta">
            <span className="approval-label">Status:</span>
            <span>{req.status}</span>
          </div>
          <div className="approval-actions">
            <button
              className="btn-approve"
              onClick={() => handleDecision(req.approval_id, true)}
              disabled={submittedId === req.approval_id}
            >
              {submittedId === req.approval_id ? "Submitting…" : "✓ Approve"}
            </button>
            <button
              className="btn-deny"
              onClick={() => handleDecision(req.approval_id, false)}
              disabled={submittedId === req.approval_id}
            >
              {submittedId === req.approval_id ? "Submitting…" : "✗ Reject"}
            </button>
          </div>
        </div>
      ))}
    </section>
  );
}
