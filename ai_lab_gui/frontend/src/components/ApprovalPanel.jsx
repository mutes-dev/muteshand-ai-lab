import { useState, useEffect } from "react";
import { api } from "../api.js";

// Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
// Frontend does NOT synthesize workflow ownership
// Backend provides authoritative workflow identity via projection

export default function ApprovalPanel({ workflowId }) {
  const [pending, setPending] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, []);

  async function poll() {
    try {
      const res = await api.approvalPending();
      setPending(res.pending ?? []);
    } catch (_) { }
  }

  async function handleDecision(step_id, approved) {
    setError(null);
    try {
      // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
      // workflowId is derived from backend projection, not synthesized locally
      if (approved) {
        await api.approve(workflowId, step_id);
      } else {
        await api.deny(workflowId, step_id);
      }
      await poll();
    } catch (e) {
      setError(e.message);
    }
  }

  if (pending.length === 0) return null;

  return (
    <section className="panel approval-panel">
      <h2>⚠ Approval Required</h2>
      {error && <div className="error-badge">⚠ {error}</div>}
      {pending.map(({ step_id, step }) => (
        <div key={step_id} className="approval-item">
          <div className="approval-meta">
            <span className="approval-label">Step:</span>
            <span>{step?.purpose ?? step_id}</span>
          </div>
          <div className="approval-meta">
            <span className="approval-label">Type:</span>
            <span>{step?.type ?? "—"}</span>
          </div>
          <div className="approval-meta">
            <span className="approval-label">Risk:</span>
            <span className={`risk-badge ${(step?.risk ?? "").toLowerCase()}`}>
              {step?.risk ?? "—"}
            </span>
          </div>
          <div className="approval-meta">
            <span className="approval-label">Tool:</span>
            <span className="mono">{step?.tool_call ?? "—"}</span>
          </div>
          <div className="approval-actions">
            <button
              className="btn-approve"
              onClick={() => handleDecision(step_id, true)}
            >
              ✓ Approve
            </button>
            <button
              className="btn-deny"
              onClick={() => handleDecision(step_id, false)}
            >
              ✗ Deny
            </button>
          </div>
        </div>
      ))}
    </section>
  );
}
