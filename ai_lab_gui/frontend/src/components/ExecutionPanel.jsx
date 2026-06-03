import { useState, useEffect } from "react";
import { api } from "../api";
import { log } from "../utils/log.js";
import { normalizeResult } from "../utils/normalizeResult.js";

export default function ExecutionPanel({ result, status, debugMode }) {
  const [expanded, setExpanded] = useState(false);
  const [trace, setTrace] = useState(null);
  const [traceExpanded, setTraceExpanded] = useState(false);


  // Normalize result using shared normalizer
  const normalized = normalizeResult(result);

  log("NORMALIZED_RESULT", {
    type: normalized?.type,
    displayStatus: normalized?.displayStatus,
    displayReason: normalized?.displayReason,
    workflow_id: result?.workflow_id,
  });

  // Fetch trace when workflow_id is available or result meaningfully changes
  // Per GUI_SYNCHRONIZATION_AUDIT_REPORT.md: trace was fetched only on mount.
  // Adding status/steps/outputs dependencies makes trace live without refresh.
  useEffect(() => {
    if (result?.workflow_id) {
      api.getTrace(result.workflow_id)
        .then(traceData => setTrace(traceData))
        .catch(() => setTrace(null)); // 404 or other errors
    }
  }, [result?.workflow_id, result?.status, result?.steps?.length, result?.outputs?.length]);

  // Extract outputs and workflow_output from contract-compliant structure
  const outputs = result?.outputs || [];
  const workflowOutput = result?.workflow_output || null;

  // Determine display value from outputs or workflow_output
  let displayResult = null;

  // PRIMARY: outputs[] (execution-level truth)
  if (outputs.length > 0) {
    const last = outputs[outputs.length - 1];
    const execRes = last?.execution_result;

    // Handle both success (has .result) and failure (has .reason) cases
    if (execRes) {
      displayResult = execRes.result ?? execRes.reason ?? null;
    }
  }

  // FALLBACK: workflow_output (system-level)
  if (displayResult === null && workflowOutput) {
    const workflowRes = typeof workflowOutput === "object" ? workflowOutput : null;
    displayResult = workflowRes?.result ?? workflowRes?.reason ?? null;
  }

  // === ISSUE-057 FIX F: Failure context from projection enrichment ===
  const isFailed = normalized?.displayStatus?.toLowerCase() === "failed";
  // Use resolved status for CANCELLED detection to ensure convergence during projection fetch errors
  const isCancelled = status?.toLowerCase() === "cancelled";
  const failureReason = result?.failure_reason || normalized?.displayReason || null;
  const failedStepId = result?.failed_step_id || null;
  const failedStepLabel = result?.failed_step_label || null;
  const retryTargetStepId = result?.retry_target_step_id || null;
  const lastSuccessfulOutput = result?.last_successful_output || null;
  const lastSuccessfulStepId = result?.last_successful_step_id || null;

  if (!result || (!result.outputs?.length && !result.workflow_output && !isFailed && !isCancelled)) {
    return (
      <section className="panel execution-panel">
        <h2>Execution Result</h2>
        <p className="muted">No result yet.</p>
      </section>
    );
  }

  const resultValue = displayResult;

  return (
    <section className="panel execution-panel">
      <h2>Execution Result</h2>
      <div className={`status-pill ${status?.toLowerCase() || normalized?.displayStatus}`}>{(status || normalized?.displayStatus)?.toUpperCase()}</div>

      {/* === ISSUE-057 FIX F: Terminal failure clarity === */}
      {isFailed && (
        <div className="failure-context">
          {failureReason && (
            <div className="failure-reason">
              <strong>Failure reason:</strong> {failureReason}
            </div>
          )}
          {failedStepLabel && (
            <div className="failed-step">
              <strong>Failed step:</strong> {failedStepLabel}
              {failedStepId && <span className="muted"> ({failedStepId})</span>}
            </div>
          )}
          {retryTargetStepId && (
            <div className="retry-target">
              <strong>Retry target:</strong> {retryTargetStepId}
            </div>
          )}
        </div>
      )}

      {/* === ISSUE-058B FIX: CANCELLED terminal clarity === */}
      {isCancelled && (
        <div className="cancelled-context">
          <div className="cancelled-notice">
            <strong>This workflow was cancelled.</strong>
            <div className="muted">The workflow is in an immutable terminal state and cannot be resumed or retried.</div>
          </div>
        </div>
      )}

      {/* For non-failed and non-cancelled results, show the primary result value */}
      {!isFailed && !isCancelled && resultValue !== null && (
        <div className="result-value">
          {typeof resultValue === "object"
            ? JSON.stringify(resultValue, null, 2)
            : String(resultValue)}
        </div>
      )}

      {/* === ISSUE-057 FIX F: Last successful output shown separately === */}
      {isFailed && lastSuccessfulOutput !== null && (
        <div className="last-successful-output">
          <div className="last-successful-label">Last successful output</div>
          <div className="result-value muted">
            {typeof lastSuccessfulOutput === "object"
              ? JSON.stringify(lastSuccessfulOutput, null, 2)
              : String(lastSuccessfulOutput)}
            {lastSuccessfulStepId && (
              <span className="muted"> from {lastSuccessfulStepId}</span>
            )}
          </div>
        </div>
      )}

      {/* === ISSUE-058B FIX: Last successful output for CANCELLED workflows === */}
      {isCancelled && lastSuccessfulOutput !== null && (
        <div className="last-successful-output">
          <div className="last-successful-label">Last successful output (historical)</div>
          <div className="result-value muted">
            {typeof lastSuccessfulOutput === "object"
              ? JSON.stringify(lastSuccessfulOutput, null, 2)
              : String(lastSuccessfulOutput)}
            {lastSuccessfulStepId && (
              <span className="muted"> from {lastSuccessfulStepId}</span>
            )}
          </div>
        </div>
      )}

      {/* Legacy reason display for non-enriched results */}
      {!failureReason && normalized?.displayReason && (
        <div className="error-badge">Reason: {normalized?.displayReason}</div>
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
