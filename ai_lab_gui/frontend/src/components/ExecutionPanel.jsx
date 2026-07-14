import { useState, useEffect } from "react";
import { api } from "../api";
import { log } from "../utils/log.js";
import { normalizeResult } from "../utils/normalizeResult.js";
import {
  formatDisplayValue,
  getStructuredPresentationText,
} from "../utils/formatDisplayValue.js";

function renderCleanValue(entry) {
  const er = entry?.execution_result;
  if (!er) return "None";
  // Prefer a clean .result value for successful execution_results
  if (er.status === "success" && er.result !== undefined) {
    return formatDisplayValue(er.result);
  }
  if (typeof er === "object") {
    return formatDisplayValue(er);
  }
  return String(er);
}

function hasCompactPresentation(executionResult) {
  return getStructuredPresentationText(executionResult) !== null;
}

function CompactResult({ executionResult }) {
  const [expanded, setExpanded] = useState(false);
  const text = getStructuredPresentationText(executionResult);

  if (!text) {
    return renderCleanValue({ execution_result: executionResult });
  }

  return (
    <div>
      <div
        className="compact-result"
        style={{
          fontSize: "15px",
          lineHeight: 1.5,
          color: "#e8e8e8",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {text}
      </div>
      <button
        className="btn-ghost"
        onClick={() => setExpanded(!expanded)}
        style={{ marginTop: "8px" }}
      >
        {expanded ? "▲ Hide details" : "▼ Details / Evidence"}
      </button>
      {expanded && (
        <pre className="json-dump" style={{ marginTop: "8px" }}>
          {JSON.stringify(executionResult?.result ?? executionResult, null, 2)}
        </pre>
      )}
    </div>
  );
}

function humanizeFailureReason(reason) {
  if (!reason) return reason;
  // Handle object reasons by converting to string first
  if (typeof reason === "object") {
    reason = formatDisplayValue(reason);
  }
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
  const [aggExpanded, setAggExpanded] = useState(false);


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

  // ISSUE-PDIAG-004: backend-authored output aggregation (read-only display)
  const agg = result?.output_aggregation || null;
  const outputMode = agg?.output_mode || null;
  const sourceOutputs = agg?.source_outputs || [];
  const successfulStepOutputs = agg?.successful_step_outputs || [];
  const terminalSuccessOutputs = agg?.terminal_success_outputs || [];
  const synthesisOutput = agg?.synthesis_output || null;
  const synthesisStepId = agg?.synthesis_step_id || null;
  const aggregationWarnings = agg?.aggregation_warnings || [];
  const finalOutput = agg?.final_output || null;

  // Determine if the details toggle has useful non-primary content
  const primaryOutputCount = (() => {
    if (!outputMode) return 0;
    if (outputMode === "multi_output_aggregate" || outputMode === "partial_result_with_warning") {
      return sourceOutputs.length > 0 ? sourceOutputs.length : terminalSuccessOutputs.length;
    }
    if (outputMode === "explicit_final_synthesis_output") return 0;
    if (outputMode === "single" || outputMode === "last_step_output") return terminalSuccessOutputs.length;
    if (outputMode === "failed_or_incomplete") return 0;
    return 0;
  })();

  const hasCompactPrimary = successfulStepOutputs.some((src) =>
    hasCompactPresentation(src.execution_result)
  );

  const hasUsefulDetails = (() => {
    if (aggregationWarnings.length > 0) return true;
    if (debugMode) return true;
    if (hasCompactPrimary) return true;
    if (outputMode === "multi_output_aggregate" || outputMode === "single" || outputMode === "last_step_output" || outputMode === "partial_result_with_warning") {
      return successfulStepOutputs.length > primaryOutputCount;
    }
    if (outputMode === "explicit_final_synthesis_output") {
      return sourceOutputs.length > 0;
    }
    if (outputMode === "failed_or_incomplete") {
      return successfulStepOutputs.length > 0 || terminalSuccessOutputs.length > 0;
    }
    return false;
  })();

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
  const isPaused = status?.toLowerCase() === "paused";
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

  if (!result || (!result.outputs?.length && !result.workflow_output && !isFailed && !isCancelled && !isBlocked && !isPaused)) {
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
      {outputMode && (
        <div className="output-mode-badge">{outputMode.replace(/_/g, " ")}</div>
      )}

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

      {/* === PAUSED clarity === */}
      {isPaused && (
        <div className="paused-context">
          <div className="paused-notice">
            <strong>Workflow is paused.</strong>
            <div className="muted">No final result yet. Resume to continue execution.</div>
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

      {/* Legacy primary result: suppressed when aggregation provides its own primary display */}
      {!isFailed && !isCancelled && !isExternalCallBlocked && resultValue !== null && (!outputMode || (outputMode !== "multi_output_aggregate" && outputMode !== "explicit_final_synthesis_output" && outputMode !== "partial_result_with_warning" && outputMode !== "single" && outputMode !== "last_step_output")) && (
        <div className="result-value">
          {(outputs.length > 0 && hasCompactPresentation(outputs[outputs.length - 1].execution_result))
            ? <CompactResult executionResult={outputs[outputs.length - 1].execution_result} />
            : (typeof resultValue === "object"
              ? JSON.stringify(resultValue, null, 2)
              : String(resultValue))}
        </div>
      )}

      {/* === ISSUE-PDIAG-004: Workflow output aggregation primary display === */}
      {agg && (
        <div className="aggregation-block" style={{ marginTop: "12px" }}>

          {/* === multi_output_aggregate: primary Workflow Outputs === */}
          {outputMode === "multi_output_aggregate" && (sourceOutputs.length > 0 || terminalSuccessOutputs.length > 0) && (
            <div style={{ marginBottom: "16px" }}>
              <div style={{ fontWeight: 700, fontSize: "15px", marginBottom: "10px", color: "#e8e8e8" }}>Workflow Outputs</div>
              {(sourceOutputs.length > 0 ? sourceOutputs : terminalSuccessOutputs).map((src, idx) => (
                <div key={src.step_id || idx} style={{ marginBottom: "10px", padding: "8px", borderRadius: "4px", background: "rgba(0,0,0,0.15)" }}>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "8px", flexWrap: "wrap", marginBottom: "4px" }}>
                    <strong style={{ wordBreak: "break-word", lineHeight: 1.4 }}>{src.step_label || src.step_id}</strong>
                    <span className={`step-status ${src.status?.toLowerCase()}`} style={{ flexShrink: 0 }}>{src.status?.toUpperCase()}</span>
                  </div>
                  <div className="result-value muted" style={{ padding: "6px 4px", lineHeight: 1.5 }}>
                    <CompactResult executionResult={src.execution_result} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* === explicit_final_synthesis_output: primary Final Answer only === */}
          {outputMode === "explicit_final_synthesis_output" && (
            <div style={{ marginBottom: "16px" }}>
              <div style={{ fontWeight: 700, fontSize: "15px", marginBottom: "10px", color: "#e8e8e8" }}>Final Answer</div>
              <div className="result-value muted" style={{ padding: "8px", borderRadius: "4px", background: "rgba(0,0,0,0.2)", lineHeight: 1.5 }}>
                {synthesisOutput ? (
                  hasCompactPresentation(synthesisOutput) ? (
                    <CompactResult executionResult={synthesisOutput} />
                  ) : (
                    renderCleanValue({ execution_result: synthesisOutput })
                  )
                ) : finalOutput ? (
                  hasCompactPresentation(finalOutput) ? (
                    <CompactResult executionResult={finalOutput} />
                  ) : typeof finalOutput === "object" && finalOutput.result !== undefined ? (
                    String(finalOutput.result)
                  ) : typeof finalOutput === "object" ? (
                    JSON.stringify(finalOutput, null, 2)
                  ) : (
                    String(finalOutput)
                  )
                ) : (
                  "None"
                )}
              </div>
            </div>
          )}

          {/* === partial_result_with_warning: primary Partial Successful Outputs (terminal/source only) === */}
          {outputMode === "partial_result_with_warning" && (sourceOutputs.length > 0 || terminalSuccessOutputs.length > 0) && (
            <div style={{ marginBottom: "16px" }}>
              <div style={{ fontWeight: 700, fontSize: "15px", marginBottom: "10px", color: "#e8e8e8" }}>Partial Successful Outputs</div>
              {(sourceOutputs.length > 0 ? sourceOutputs : terminalSuccessOutputs).map((src, idx) => (
                <div key={src.step_id || idx} style={{ marginBottom: "10px", padding: "8px", borderRadius: "4px", background: "rgba(0,0,0,0.15)" }}>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "8px", flexWrap: "wrap", marginBottom: "4px" }}>
                    <strong style={{ wordBreak: "break-word", lineHeight: 1.4 }}>{src.step_label || src.step_id}</strong>
                    <span className={`step-status ${src.status?.toLowerCase()}`} style={{ flexShrink: 0 }}>{src.status?.toUpperCase()}</span>
                  </div>
                  <div className="result-value muted" style={{ padding: "6px 4px", lineHeight: 1.5 }}>
                    <CompactResult executionResult={src.execution_result} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* === single: primary Output === */}
          {outputMode === "single" && terminalSuccessOutputs.length > 0 && (
            <div style={{ marginBottom: "16px" }}>
              <div style={{ fontWeight: 700, fontSize: "15px", marginBottom: "10px", color: "#e8e8e8" }}>Output</div>
              {terminalSuccessOutputs.map((src, idx) => (
                <div key={src.step_id || idx} style={{ marginBottom: "10px", padding: "8px", borderRadius: "4px", background: "rgba(0,0,0,0.15)" }}>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "8px", flexWrap: "wrap", marginBottom: "4px" }}>
                    <strong style={{ wordBreak: "break-word", lineHeight: 1.4 }}>{src.step_label || src.step_id}</strong>
                    <span className={`step-status ${src.status?.toLowerCase()}`} style={{ flexShrink: 0 }}>{src.status?.toUpperCase()}</span>
                  </div>
                  <div className="result-value muted" style={{ padding: "6px 4px", lineHeight: 1.5 }}>
                    <CompactResult executionResult={src.execution_result} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* === last_step_output / fallback: primary Output === */}
          {outputMode === "last_step_output" && terminalSuccessOutputs.length > 0 && (
            <div style={{ marginBottom: "16px" }}>
              <div style={{ fontWeight: 700, fontSize: "15px", marginBottom: "10px", color: "#e8e8e8" }}>Output</div>
              {terminalSuccessOutputs.map((src, idx) => (
                <div key={src.step_id || idx} style={{ marginBottom: "10px", padding: "8px", borderRadius: "4px", background: "rgba(0,0,0,0.15)" }}>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: "8px", flexWrap: "wrap", marginBottom: "4px" }}>
                    <strong style={{ wordBreak: "break-word", lineHeight: 1.4 }}>{src.step_label || src.step_id}</strong>
                    <span className={`step-status ${src.status?.toLowerCase()}`} style={{ flexShrink: 0 }}>{src.status?.toUpperCase()}</span>
                  </div>
                  <div className="result-value muted" style={{ padding: "6px 4px", lineHeight: 1.5 }}>
                    <CompactResult executionResult={src.execution_result} />
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* === failed_or_incomplete: no successful outputs to show === */}
          {outputMode === "failed_or_incomplete" && (
            <div style={{ marginBottom: "16px", padding: "8px", borderRadius: "4px", background: "rgba(0,0,0,0.15)", color: "#aaa" }}>
              No successful outputs available.
            </div>
          )}

          {/* === PDIAG-005 Phase 1: Advisory false-success warnings === */}
          {agg?.false_success_analysis?.warning && (
            <div style={{ marginBottom: "16px", padding: "10px", borderRadius: "4px", background: "rgba(255, 165, 0, 0.08)", border: "1px solid rgba(255, 165, 0, 0.25)" }}>
              <div style={{ fontWeight: 600, fontSize: "14px", marginBottom: "6px", color: "#f5a623" }}>
                Advisory warning: possible false-success pattern detected
              </div>
              <div style={{ fontSize: "12px", color: "#ccc", marginBottom: "8px" }}>
                Execution status was not changed.
              </div>
              {(agg.false_success_analysis.warnings || []).map((w, i) => (
                <div key={i} style={{ fontSize: "13px", color: "#ddd", padding: "3px 0", lineHeight: 1.4 }}>
                  <span style={{ color: "#f5a623", fontWeight: 500 }}>[{w.code}]</span> {w.message}
                  {w.evidence && <span className="muted" style={{ fontSize: "11px", marginLeft: "6px" }}>({w.evidence})</span>}
                </div>
              ))}
            </div>
          )}

          {/* === Warnings (always visible if present) === */}
          {aggregationWarnings.length > 0 && (
            <div style={{ marginBottom: "10px" }}>
              <div style={{ fontWeight: 600, fontSize: "14px", marginBottom: "6px", color: "#e0e0e0" }}>Warnings</div>
              {aggregationWarnings.map((w, i) => (
                <div key={i} className="warning-item muted" style={{ padding: "4px 0", lineHeight: 1.4 }}>{w}</div>
              ))}
            </div>
          )}

          {/* === Details toggle: only shown if useful non-primary content exists === */}
          {hasUsefulDetails && (
            <>
              <button className="btn-ghost" onClick={() => setAggExpanded(!aggExpanded)}>
                {aggExpanded ? "▲ Hide details" : "▼ Show details"}
              </button>
              {aggExpanded && (
                <div className="aggregation-details" style={{ marginTop: "10px", padding: "10px", borderRadius: "6px", background: "rgba(255,255,255,0.03)" }}>

                  {/* Source Outputs for explicit synthesis */}
                  {outputMode === "explicit_final_synthesis_output" && sourceOutputs.length > 0 && (
                    <div style={{ marginBottom: "16px" }}>
                      <div style={{ fontWeight: 600, fontSize: "14px", marginBottom: "8px", color: "#e0e0e0" }}>Source Outputs</div>
                      {sourceOutputs.map((src, idx) => (
                        <div key={src.step_id || idx} style={{ marginBottom: "10px", padding: "8px", borderRadius: "4px", background: "rgba(0,0,0,0.15)" }}>
                          <div style={{ display: "flex", alignItems: "flex-start", gap: "8px", flexWrap: "wrap", marginBottom: "4px" }}>
                            <strong style={{ wordBreak: "break-word", lineHeight: 1.4 }}>{src.step_label || src.step_id}</strong>
                            <span className={`step-status ${src.status?.toLowerCase()}`} style={{ flexShrink: 0 }}>{src.status?.toUpperCase()}</span>
                          </div>
                          <div className="result-value muted" style={{ padding: "6px 4px", lineHeight: 1.5 }}>
                            {renderCleanValue(src)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* All Successful Step Outputs when primary is a subset */}
                  {(outputMode === "multi_output_aggregate" || outputMode === "single" || outputMode === "last_step_output" || outputMode === "partial_result_with_warning") && successfulStepOutputs.length > primaryOutputCount && (
                    <div style={{ marginBottom: "16px" }}>
                      <div style={{ fontWeight: 600, fontSize: "14px", marginBottom: "8px", color: "#e0e0e0" }}>All Successful Step Outputs</div>
                      {successfulStepOutputs.map((src, idx) => (
                        <div key={src.step_id || idx} style={{ marginBottom: "10px", padding: "8px", borderRadius: "4px", background: "rgba(0,0,0,0.15)" }}>
                          <div style={{ display: "flex", alignItems: "flex-start", gap: "8px", flexWrap: "wrap", marginBottom: "4px" }}>
                            <strong style={{ wordBreak: "break-word", lineHeight: 1.4 }}>{src.step_label || src.step_id}</strong>
                            <span className={`step-status ${src.status?.toLowerCase()}`} style={{ flexShrink: 0 }}>{src.status?.toUpperCase()}</span>
                          </div>
                          <div className="result-value muted" style={{ padding: "6px 4px", lineHeight: 1.5 }}>
                            {renderCleanValue(src)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Partial outputs for failed_or_incomplete */}
                  {outputMode === "failed_or_incomplete" && (successfulStepOutputs.length > 0 || terminalSuccessOutputs.length > 0) && (
                    <div style={{ marginBottom: "16px" }}>
                      <div style={{ fontWeight: 600, fontSize: "14px", marginBottom: "8px", color: "#e0e0e0" }}>Partial Successful Outputs</div>
                      {(successfulStepOutputs.length > 0 ? successfulStepOutputs : terminalSuccessOutputs).map((src, idx) => (
                        <div key={src.step_id || idx} style={{ marginBottom: "10px", padding: "8px", borderRadius: "4px", background: "rgba(0,0,0,0.15)" }}>
                          <div style={{ display: "flex", alignItems: "flex-start", gap: "8px", flexWrap: "wrap", marginBottom: "4px" }}>
                            <strong style={{ wordBreak: "break-word", lineHeight: 1.4 }}>{src.step_label || src.step_id}</strong>
                            <span className={`step-status ${src.status?.toLowerCase()}`} style={{ flexShrink: 0 }}>{src.status?.toUpperCase()}</span>
                          </div>
                          <div className="result-value muted" style={{ padding: "6px 4px", lineHeight: 1.5 }}>
                            {renderCleanValue(src)}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* === Debug Mode: raw technical aggregation payload === */}
                  {debugMode && (
                    <div style={{ marginTop: "16px", padding: "10px", borderRadius: "4px", background: "rgba(0,0,0,0.25)", border: "1px dashed rgba(255,255,255,0.15)" }}>
                      <div style={{ fontWeight: 600, fontSize: "13px", marginBottom: "8px", color: "#aaa" }}>Backend Aggregation Debug</div>
                      <div className="muted" style={{ fontSize: "12px", lineHeight: 1.5 }}>
                        <div><strong>output_mode:</strong> {outputMode || "none"}</div>
                        <div style={{ marginTop: "8px" }}><strong>synthesis_step_id:</strong> {synthesisStepId || "none"}</div>
                        <div style={{ marginTop: "8px" }}><strong>final_output (legacy compat):</strong></div>
                        <pre style={{ margin: "4px 0", fontSize: "12px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                          {finalOutput ? JSON.stringify(finalOutput, null, 2) : "None"}
                        </pre>
                        <div style={{ marginTop: "8px" }}><strong>source_outputs ({sourceOutputs.length}):</strong></div>
                        <pre style={{ margin: "4px 0", fontSize: "12px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                          {JSON.stringify(sourceOutputs, null, 2)}
                        </pre>
                        <div style={{ marginTop: "8px" }}><strong>terminal_success_outputs ({terminalSuccessOutputs.length}):</strong></div>
                        <pre style={{ margin: "4px 0", fontSize: "12px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                          {JSON.stringify(terminalSuccessOutputs, null, 2)}
                        </pre>
                        <div style={{ marginTop: "8px" }}><strong>successful_step_outputs ({successfulStepOutputs.length}):</strong></div>
                        <pre style={{ margin: "4px 0", fontSize: "12px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                          {JSON.stringify(successfulStepOutputs, null, 2)}
                        </pre>
                        <div style={{ marginTop: "8px" }}><strong>aggregation_warnings ({aggregationWarnings.length}):</strong></div>
                        <pre style={{ margin: "4px 0", fontSize: "12px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                          {JSON.stringify(aggregationWarnings, null, 2)}
                        </pre>
                        <div style={{ marginTop: "8px" }}><strong>false_success_analysis:</strong></div>
                        <pre style={{ margin: "4px 0", fontSize: "12px", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                          {JSON.stringify(agg?.false_success_analysis || {}, null, 2)}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}
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
