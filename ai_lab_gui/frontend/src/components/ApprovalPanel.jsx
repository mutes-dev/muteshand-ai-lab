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
export default function ApprovalPanel({ workflowId }) {
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [submittedId, setSubmittedId] = useState(null);

  useEffect(() => {
    if (!workflowId) return;
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
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
      // Refresh list after successful intent dispatch
      await poll();
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
