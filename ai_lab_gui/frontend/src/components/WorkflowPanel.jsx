const STATUS_COLOR = {
  COMPLETED: "#22c55e",
  FAILED: "#ef4444",
  BLOCKED: "#f97316",
  ACTIVE: "#3b82f6",
  PENDING: "#94a3b8",
};

export default function WorkflowPanel({ result }) {
  const trace = result?.trace;

  // trace.steps contains mixed events: step_execution, governance_decision,
  // state_transition. Filter to step_execution events only — these carry
  // the real step data nested under .data per TraceCollector schema.
  const allEntries = trace?.steps ?? [];
  const steps = allEntries.filter((e) => e.event === "step_execution");

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
        {result.reason && <span className="reason-badge">reason: {result.reason}</span>}
      </div>

      {steps.length > 0 ? (
        <ol className="step-list">
          {steps.map((entry, i) => {
            const d = entry.data ?? {};
            const status = d.status ?? "UNKNOWN";
            const color = STATUS_COLOR[status] ?? "#94a3b8";
            return (
              <li key={d.step_id ?? i} className="step-item">
                <span className="step-dot" style={{ background: color }} />
                <span className="step-name">{d.purpose || d.step_id || `Step ${i + 1}`}</span>
                <span className="step-status" style={{ color }}>{status}</span>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="muted">No step trace available.</p>
      )}
    </section>
  );
}
