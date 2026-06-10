import { useState, useEffect } from "react";
import { api } from "../api.js";

// Per USER_CONTROL_CONTRACT_V2: Frontend is projection-only.
// Frontend does NOT synthesize workflow ownership or infer legality.
// Backend provides authoritative request identity and metadata.

/**
 * UserControlPanel — ISSUE-098K
 * Contract-safe user-control surface for external-call risk acceptance.
 *
 * - Polls GET /user-controls/{workflow_id} for PENDING requests
 * - Sends intent via POST /user-controls/{control_id}/accept or /reject
 * - Displays backend-provided metadata only (no frontend inference)
 * - Does NOT mutate local workflow state — waits for backend/projection updates
 * - Handles stale/expired/already-resolved responses safely
 */
export default function UserControlPanel({ workflowId }) {
  const [pending, setPending] = useState([]);
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
      const res = await api.getUserControls(workflowId);
      setPending(res.pending ?? []);
      setError(null);
    } catch (e) {
      // Silent fail on poll — don't flash errors for background refresh
      console.log("[UserControlPanel:poll_error]", e.message);
    }
  }

  async function handleDecision(control_id, accepted) {
    setError(null);
    setSubmittedId(control_id);
    try {
      if (accepted) {
        await api.acceptUserControl(control_id);
      } else {
        await api.rejectUserControl(control_id);
      }
      // Refresh list after successful intent dispatch
      await poll();
    } catch (e) {
      const msg = e.message || "";
      if (msg.includes("410") || msg.includes("expired") || msg.includes("EXPIRED")) {
        setError("This user-control request has expired. The workflow may need to be restarted.");
      } else if (msg.includes("409") || msg.includes("already resolved")) {
        setError("This user-control request has already been resolved.");
      } else if (msg.includes("404") || msg.includes("not found")) {
        setError("User-control request not found. It may have been cancelled.");
      } else {
        setError(msg);
      }
    } finally {
      setSubmittedId(null);
    }
  }

  if (!workflowId) return null;
  if (pending.length === 0) return null;

  return (
    <section className="panel user-control-panel">
      <h2>External Call Risk — Operator Review Required</h2>
      <p className="user-control-subtitle">
        This is a user-control risk acceptance request. It is distinct from normal approval.
        The backend still validates all decisions.
      </p>
      {error && <div className="error-badge">⚠ {error}</div>}
      {pending.map((req) => {
        const meta = req.metadata || {};
        const isExternalCallRisk = req.requested_action === "accept_external_call_risk";
        return (
          <div key={req.control_id} className="user-control-item">
            <div className="user-control-meta">
              <span className="user-control-label">Action:</span>
              <span>{req.requested_action ?? "—"}</span>
            </div>
            <div className="user-control-meta">
              <span className="user-control-label">Step:</span>
              <span>{req.step_id ?? "—"}</span>
            </div>
            <div className="user-control-meta">
              <span className="user-control-label">Reason:</span>
              <span>{req.reason ?? "—"}</span>
            </div>
            <div className="user-control-meta">
              <span className="user-control-label">Risk:</span>
              <span className={`risk-badge ${(req.risk_level ?? "").toLowerCase()}`}>
                {req.risk_level ?? "—"}
              </span>
            </div>
            {req.confirmation_text && (
              <div className="user-control-meta user-control-confirmation">
                <span className="user-control-label">Confirmation:</span>
                <span>{req.confirmation_text}</span>
              </div>
            )}
            {isExternalCallRisk && (
              <div className="user-control-meta user-control-external-details">
                <span className="user-control-label">Tool:</span>
                <span className="mono">{meta.tool_name ?? "—"}</span>
              </div>
            )}
            {meta.provider && (
              <div className="user-control-meta">
                <span className="user-control-label">Provider:</span>
                <span>{meta.provider}</span>
              </div>
            )}
            {meta.destination && (
              <div className="user-control-meta">
                <span className="user-control-label">Destination:</span>
                <span className="mono">{meta.destination}</span>
              </div>
            )}
            {meta.data_leaving_system && (
              <div className="user-control-meta">
                <span className="user-control-label">Data leaving system:</span>
                <span>{meta.data_leaving_system}</span>
              </div>
            )}
            {meta.privacy_classification && (
              <div className="user-control-meta">
                <span className="user-control-label">Privacy classification:</span>
                <span>{meta.privacy_classification}</span>
              </div>
            )}
            {(meta.read_only !== undefined || meta.mutating !== undefined || meta.external_call !== undefined) && (
              <div className="user-control-meta user-control-flags">
                {meta.read_only === true && <span className="flag-badge read-only">Read-only</span>}
                {meta.mutating === true && <span className="flag-badge mutating">Mutating</span>}
                {meta.external_call === true && <span className="flag-badge external">External call</span>}
              </div>
            )}
            <div className="user-control-meta">
              <span className="user-control-label">Status:</span>
              <span>{req.status}</span>
            </div>
            <div className="user-control-actions">
              <button
                className="btn-accept-risk"
                onClick={() => handleDecision(req.control_id, true)}
                disabled={submittedId === req.control_id}
              >
                {submittedId === req.control_id ? "Submitting…" : "Accept external call risk"}
              </button>
              <button
                className="btn-reject-risk"
                onClick={() => handleDecision(req.control_id, false)}
                disabled={submittedId === req.control_id}
              >
                {submittedId === req.control_id ? "Submitting…" : "Reject"}
              </button>
            </div>
          </div>
        );
      })}
    </section>
  );
}
