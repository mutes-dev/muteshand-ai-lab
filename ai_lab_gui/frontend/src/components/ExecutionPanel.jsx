import { useState, useEffect } from "react";
import { api } from "../api";

export default function ExecutionPanel({ result, debugMode }) {
  const [expanded, setExpanded] = useState(false);
  const [trace, setTrace] = useState(null);
  const [traceExpanded, setTraceExpanded] = useState(false);

  // Fetch trace when workflow_id is available
  useEffect(() => {
    if (result?.workflow_id) {
      api.getTrace(result.workflow_id)
        .then(traceData => setTrace(traceData))
        .catch(() => setTrace(null)); // 404 or other errors
    }
  }, [result?.workflow_id]);

  if (!result) {
    return (
      <section className="panel execution-panel">
        <h2>Execution Result</h2>
        <p className="muted">No result yet.</p>
      </section>
    );
  }

  const resultValue = result?.execution_result?.result ?? result?.result?.result ?? result?.result ?? null;

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

      {/* Trace Display Section */}
      {trace && (
        <div className="trace-block">
          <h3>Execution Trace</h3>
          <div className="trace-summary">
            <span>Workflow ID: {trace.workflow_id}</span>
            <span>Steps: {trace.step_count || trace.steps?.length || 0}</span>
          </div>

          <button className="btn-ghost" onClick={() => setTraceExpanded(!traceExpanded)}>
            {traceExpanded ? "▲ Hide Trace Steps" : "▼ Show Trace Steps"}
          </button>

          {traceExpanded && trace.steps && (
            <div className="trace-steps">
              {trace.steps.map((step, index) => (
                <div key={index} className="trace-step">
                  <div className="step-header">
                    <span className="step-id">{step.step_id}</span>
                    <span className={`step-status ${step.status?.toLowerCase()}`}>
                      {step.status?.toUpperCase()}
                    </span>
                    {step.retries > 0 && (
                      <span className="step-retries">Retries: {step.retries}</span>
                    )}
                  </div>
                  <div className="step-purpose">{step.purpose}</div>
                  {step.execution_result && (
                    <div className="step-result">
                      Result: {JSON.stringify(step.execution_result.result)}
                    </div>
                  )}
                  {step.governance_decision && (
                    <div className="step-governance">
                      Decision: {step.governance_decision}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
