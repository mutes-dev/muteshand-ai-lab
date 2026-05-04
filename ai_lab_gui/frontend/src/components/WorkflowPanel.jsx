const STATUS_COLOR = {
  COMPLETED: "#22c55e",
  FAILED: "#ef4444",
  BLOCKED: "#f97316",
  ACTIVE: "#3b82f6",
  PENDING: "#94a3b8",
};

export default function WorkflowPanel({ result }) {
  const trace = result?.trace;
  const steps = trace?.steps ?? [];

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
          {steps.map((step, i) => {
            const status = step.status ?? "UNKNOWN";
            const color = STATUS_COLOR[status] ?? "#94a3b8";
            return (
              <li key={step.id ?? i} className="step-item">
                <span className="step-dot" style={{ background: color }} />
                <span className="step-name">{step.purpose ?? step.id ?? `Step ${i + 1}`}</span>
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
