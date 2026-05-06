import { useState, useEffect, useRef } from "react";
import { api } from "../api";

const STATUS_COLOR = {
  COMPLETED: "#22c55e",
  FAILED: "#ef4444",
  BLOCKED: "#f97316",
  ACTIVE: "#3b82f6",
  PENDING: "#94a3b8",
};

const POLL_INTERVAL_MS = 700;

export default function WorkflowPanel({ result, isExecuting }) {
  const [trace, setTrace] = useState(null);
  const intervalRef = useRef(null);

  const workflowId = result?.workflow_id;

  function stopPolling() {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }

  function fetchTrace(id) {
    api.getTrace(id)
      .then((traceData) => {
        setTrace(traceData);
      })
      .catch(() => {
        // 404 or network error — keep polling silently
      });
  }

  useEffect(() => {
    stopPolling();

    if (!workflowId) return;

    fetchTrace(workflowId);

    intervalRef.current = setInterval(() => fetchTrace(workflowId), POLL_INTERVAL_MS);

    return () => stopPolling();
  }, [workflowId]);

  // Stop polling once execution has finished (isExecuting transitions false→false)
  useEffect(() => {
    if (!isExecuting && workflowId) {
      // Do one final fetch after execution completes, then stop
      fetchTrace(workflowId);
      stopPolling();
    }
  }, [isExecuting]);

  // trace.steps entries are flat per TRACE_LOGGING_CONTRACT_V1:
  // { timestamp, project_id, step_id, level, event, data }
  const steps = (trace?.steps ?? []).filter((s) => s.event === "step_execution");

  if (isExecuting && !result) {
    return (
      <section className="panel workflow-panel">
        <h2>Workflow</h2>
        <p className="muted running-indicator">⟳ Executing…</p>
      </section>
    );
  }

  if (!result) {
    return (
      <section className="panel workflow-panel">
        <h2>Workflow</h2>
        <p className="muted">No execution yet.</p>
      </section>
    );
  }

  return (
    <section className="panel workflow-panel">
      <h2>Workflow</h2>
      <div className="workflow-meta">
        <span className={`status-pill ${result.status}`}>{result.status?.toUpperCase()}</span>
        {isExecuting && <span className="running-indicator"> ⟳ Running…</span>}
        {result.reason && <span className="reason-badge">reason: {result.reason}</span>}
      </div>

      {steps.length > 0 ? (
        <ol className="step-list">
          {steps.map((step, i) => {
            const d = step.data ?? {};
            const status = d.status ?? "UNKNOWN";
            const color = STATUS_COLOR[status] ?? "#94a3b8";
            return (
              <li key={step.step_id ?? d.step_id ?? i} className="step-item">
                <span className="step-dot" style={{ background: color }} />
                <span className="step-name">{d.purpose || d.step_id || `Step ${i + 1}`}</span>
                <span className="step-status" style={{ color }}>{status}</span>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="muted">{isExecuting ? "Waiting for trace…" : "No step trace available."}</p>
      )}
    </section>
  );
}
