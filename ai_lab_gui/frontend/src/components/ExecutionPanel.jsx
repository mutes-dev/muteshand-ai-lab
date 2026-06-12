import { useState, useEffect } from "react";
import { api } from "../api";
import { log } from "../utils/log.js";
import { normalizeResult } from "../utils/normalizeResult.js";

function humanizeFailureReason(reason) {
  if (!reason) return reason;
  const map = {
    division_by_zero: "Division by zero",
    dependency_not_declared: "Dependency not declared",
    planner_parse_failure: "Planner parse failure",
    http_error: "HTTP error from target site",
    connection_error: "Connection error",
    timeout: "Request timed out",
    network_error: "Network error",
    retry_not_eligible: "Retry not eligible",
    validation_failed: "Validation failed",
    workflow_failed: "Workflow failed",
  };
  if (map[reason]) return map[reason];
  // Fallback: title-case snake_case strings
  if (typeof reason === "string" && reason.includes("_")) {
    return reason
      .split("_")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  }
  return reason;
}

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
  const isBlocked = status?.toLowerCase() === "blocked" || normalized?.displayStatus?.toLowerCase() === "blocked";
  const blockedReason = normalized?.displayReason || result?.reason || null;
  const isExternalCallBlocked = (
    blockedReason === "external_call_risk" ||
    blockedReason?.includes("external_call") ||
    displayResult === "external_call_risk" ||
    (typeof displayResult === "string" && displayResult.includes("external_call"))
  );
  // ISSUE-092B: Prefer human-readable display message for pre-step planner failures,
  // then failure_reason, then normalized displayReason. Raw JSON still shows all fields.
  const rawFailureReason = result?.failure_reason || normalized?.displayReason || null;
  const failureReason = result?.failure_display_message || humanizeFailureReason(rawFailureReason) || null;
  const failedStepId = result?.failed_step_id || null;
  const failedStepLabel = result?.failed_step_label || null;
  const retryTargetStepId = result?.retry_target_step_id || null;
  const lastSuccessfulOutput = result?.last_successful_output || null;
  const lastSuccessfulStepId = result?.last_successful_step_id || null;
  // Display-only: propagate detail from tool failure output if available
  const failureDetail = result?.detail || outputs?.[outputs.length - 1]?.execution_result?.detail || null;

  if (!result || (!result.outputs?.length && !result.workflow_output && !isFailed && !isCancelled && !isBlocked)) {
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
              {failureDetail && <span className="muted"> ({failureDetail})</span>}
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

      {/* === External-call BLOCKED operator guidance === */}
      {isBlocked && isExternalCallBlocked && (
        <div className="blocked-context">
          <div className="blocked-notice">
            <strong>External call review required</strong>
            <div className="muted">Review the External Call Risk panel below and choose Accept or Reject.</div>
          </div>
        </div>
      )}

      {/* For non-failed and non-cancelled results, show the primary result value */}
      {!isFailed && !isCancelled && !isExternalCallBlocked && resultValue !== null && (
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
      {!failureReason && normalized?.displayReason && !isExternalCallBlocked && (
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
            <div>Workflow ID: {trace.workflow_id}</div>
            <div>Steps: {trace.step_count || trace.steps?.length || 0}</div>
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
