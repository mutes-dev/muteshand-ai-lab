import { useState } from "react";

export default function ExecutionPanel({ result, debugMode }) {
  const [expanded, setExpanded] = useState(false);

  if (!result) {
    return (
      <section className="panel execution-panel">
        <h2>Execution Result</h2>
        <p className="muted">No result yet.</p>
      </section>
    );
  }

  const resultValue = result?.result?.result ?? result?.result ?? null;

  return (
    <section className="panel execution-panel">
      <h2>Execution Result</h2>
      <div className={`status-pill ${result.status}`}>{result.status?.toUpperCase()}</div>

      {resultValue !== null && (
        <div className="result-value">
          {typeof resultValue === "object"
            ? JSON.stringify(resultValue, null, 2)
            : String(resultValue)}
        </div>
      )}

      {result.reason && (
        <div className="error-badge">Reason: {result.reason}</div>
      )}

      {debugMode && (
        <div className="debug-block">
          <button className="btn-ghost" onClick={() => setExpanded(!expanded)}>
            {expanded ? "▲ Hide raw JSON" : "▼ Show raw JSON"}
          </button>
          {expanded && (
            <pre className="json-dump">{JSON.stringify(result, null, 2)}</pre>
          )}
        </div>
      )}
    </section>
  );
}
