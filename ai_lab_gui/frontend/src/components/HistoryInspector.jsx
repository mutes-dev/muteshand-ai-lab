import { useState, useEffect } from "react";
import { api } from "../api.js";

function formatStatus(status) {
  const map = {
    QUEUED: { color: "#64748b", label: "Queued" },
    ACTIVE: { color: "#22c55e", label: "Active" },
    PAUSED: { color: "#f97316", label: "Paused" },
    PENDING_RECOVERY: { color: "#fbbf24", label: "Recovering" },
    FAILED: { color: "#ef4444", label: "Failed" },
    COMPLETED: { color: "#64748b", label: "Completed" },
    CANCELLED: { color: "#64748b", label: "Cancelled" },
  };
  return map[status] || { color: "#64748b", label: status || "Unknown" };
}

function formatDate(ts) {
  if (!ts) return "—";
  let date;
  if (typeof ts === "string" && ts.includes("T")) {
    date = new Date(ts);
  } else if (typeof ts === "number" && ts > 1e10) {
    date = new Date(ts);
  } else {
    date = new Date(ts * 1000);
  }
  if (isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatSource(source) {
  const map = {
    active_workflows: "Active workflow record",
    workflows_json: "Historical record",
    registry: "Runtime registry snapshot",
  };
  return map[source] || source || "Unknown";
}

function formatRetention(state) {
  const map = {
    retained: "Retained",
    archived: "Archived",
    dismissed: "Dismissed",
  };
  return map[state] || state || "Retained";
}

function formatActionability(val) {
  const map = {
    IN_PROGRESS: "In progress",
    PLANNING_REPLAN: "Planning interrupted",
    REPLAN_REQUIRED: "Replan available",
    QUEUED_REPLAN_REQUIRED: "Replan queued",
  };
  return map[val] || val || null;
}

const ROUTE_REASON_DISPLAY = {
  all_roles_local: "All roles are using local Ollama",
  role_provider_ollama: "This role used local Ollama",
  role_provider_openrouter: "This role used OpenRouter",
  budget_fallback: "Budget limit reached — fallback route used",
  provider_error_fallback: "Provider failed — fallback route used",
  openrouter_model_fallback: "OpenRouter model fallback used",
  fallback: "Fallback route used",
  default: "Default route used",
};

function humanizeRouteReason(reason) {
  if (!reason) return reason;
  return ROUTE_REASON_DISPLAY[reason] || reason;
}

/**
 * HistoryInspector — ISSUE-061 Phase 4C
 *
 * Renders a read-only historical workflow inspection in the main workspace.
 * This is NOT foreground attachment. This is NOT recovery/resume/replan/retry.
 */
function toRenderSafe(value, maxLen = 200) {
  if (value === null || value === undefined) return null;
  if (typeof value === "string") return value.length > maxLen ? value.slice(0, maxLen) + "…" : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    const s = JSON.stringify(value);
    return s.length > maxLen ? s.slice(0, maxLen) + "…" : s;
  } catch {
    return "[unreadable data]";
  }
}

function normalizeArrayPayload(payload) {
  if (Array.isArray(payload)) return payload;
  if (!payload || typeof payload !== "object") return [];
  if (Array.isArray(payload.steps)) return payload.steps;
  if (Array.isArray(payload.trace)) return payload.trace;
  if (Array.isArray(payload.traces)) return payload.traces;
  if (Array.isArray(payload.entries)) return payload.entries;
  if (Array.isArray(payload.events)) return payload.events;
  if (Array.isArray(payload.items)) return payload.items;
  if (Array.isArray(payload.data)) return payload.data;
  return [];
}

function safeTraceEntry(entry) {
  if (!entry || typeof entry !== "object") return null;
  const ts = entry.timestamp ?? entry.ts ?? entry.time ?? null;
  const step = toRenderSafe(entry.step_id ?? entry.step ?? entry.step_name ?? null);
  const type = toRenderSafe(entry.type ?? entry.event ?? entry.action ?? null);
  const status = toRenderSafe(entry.status ?? null);
  const msg = toRenderSafe(entry.message ?? entry.details ?? entry.summary ?? null);
  return { ts, step, type, status, msg };
}

function safeEventEntry(entry) {
  if (!entry || typeof entry !== "object") return null;
  const ts = entry.timestamp ?? entry.ts ?? entry.time ?? null;
  const type = toRenderSafe(entry.type ?? entry.event_type ?? entry.event ?? entry.name ?? null);
  const status = toRenderSafe(entry.status ?? null);
  const step = toRenderSafe(entry.step_id ?? entry.step ?? null);
  // entry.data is always an object in the event bus; do NOT render it raw.
  // Prefer explicit message/details/summary; fall back to stringified data only as last resort.
  const msg = toRenderSafe(entry.message ?? entry.details ?? entry.summary ?? null);
  return { ts, type, status, step, msg };
}

function formatEntryTime(ts) {
  if (!ts) return "";
  try {
    let d;
    if (typeof ts === "string" && ts.includes("T")) {
      d = new Date(ts);
    } else if (typeof ts === "number" && ts > 1e10) {
      d = new Date(ts);
    } else if (typeof ts === "number") {
      d = new Date(ts * 1000);
    } else {
      return "";
    }
    return isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}

export default function HistoryInspector({ workflow, onClose }) {
  const [projection, setProjection] = useState(null);
  const [projectionLoading, setProjectionLoading] = useState(false);
  const [techOpen, setTechOpen] = useState(false);

  // Execution History (trace + events) — Phase 5A
  const [execOpen, setExecOpen] = useState(false);
  const [traceData, setTraceData] = useState(null);
  const [eventsData, setEventsData] = useState(null);
  const [execLoading, setExecLoading] = useState(false);
  const [execError, setExecError] = useState(false);
  const [execShapeError, setExecShapeError] = useState(false);

  // LLM Calls — ISSUE-094D Phase 1
  const [llmOpen, setLlmOpen] = useState(false);
  const [llmData, setLlmData] = useState(null);
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmError, setLlmError] = useState(false);

  useEffect(() => {
    if (!workflow?.projection_available) {
      setProjection(null);
      return;
    }
    let cancelled = false;
    setProjectionLoading(true);
    api.getProjection(workflow.workflow_id)
      .then((proj) => {
        if (!cancelled) setProjection(proj || null);
      })
      .catch(() => {
        if (!cancelled) setProjection(null);
      })
      .finally(() => {
        if (!cancelled) setProjectionLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workflow?.workflow_id, workflow?.projection_available]);

  // Reset execution history when workflow changes
  useEffect(() => {
    setTraceData(null);
    setEventsData(null);
    setExecError(false);
    setExecShapeError(false);
    setExecLoading(false);
    setLlmData(null);
    setLlmError(false);
    setLlmLoading(false);
  }, [workflow?.workflow_id]);

  useEffect(() => {
    if (!execOpen || !workflow) return;
    const wfId = workflow.workflow_id;
    const needsTrace = workflow.trace_available && traceData === null;
    const needsEvents = workflow.events_available && eventsData === null;
    if (!needsTrace && !needsEvents) return;

    let cancelled = false;
    setExecLoading(true);
    setExecError(false);
    setExecShapeError(false);

    // Track fetch outcomes locally to avoid stale closure reading state.
    let traceOk = !needsTrace;
    let eventsOk = !needsEvents;
    let traceShapeBad = false;
    let eventsShapeBad = false;

    const promises = [];
    if (needsTrace) {
      promises.push(
        api.getTrace(wfId)
          .then((data) => {
            if (!cancelled) {
              const arr = normalizeArrayPayload(data);
              traceOk = arr.length > 0 || !workflow.trace_available;
              traceShapeBad = arr.length === 0 && workflow.trace_available && data !== null && data !== undefined;
              setTraceData(arr);
            }
          })
          .catch(() => { traceOk = false; })
      );
    }
    if (needsEvents) {
      promises.push(
        api.getEvents(wfId, -1, -1, 100)
          .then((data) => {
            if (!cancelled) {
              const arr = normalizeArrayPayload(data);
              eventsOk = arr.length > 0 || !workflow.events_available;
              eventsShapeBad = arr.length === 0 && workflow.events_available && data !== null && data !== undefined;
              setEventsData(arr);
            }
          })
          .catch(() => { eventsOk = false; })
      );
    }

    Promise.all(promises).finally(() => {
      if (!cancelled) {
        setExecLoading(false);
        if (traceShapeBad || eventsShapeBad) {
          setExecShapeError(true);
        } else if (!traceOk || !eventsOk) {
          setExecError(true);
        }
      }
    });

    return () => {
      cancelled = true;
    };
  }, [execOpen, workflow?.workflow_id, workflow?.trace_available, workflow?.events_available]);

  // LLM Calls fetch — ISSUE-094D Phase 1
  useEffect(() => {
    if (!llmOpen || !workflow) return;
    const wfId = workflow.workflow_id;
    if (llmData !== null) return;

    let cancelled = false;
    setLlmLoading(true);
    setLlmError(false);

    api.llmUsageWorkflow(wfId, 50)
      .then((data) => {
        if (!cancelled) {
          setLlmData(data?.entries || []);
        }
      })
      .catch(() => {
        if (!cancelled) setLlmError(true);
      })
      .finally(() => {
        if (!cancelled) setLlmLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [llmOpen, workflow?.workflow_id]);

  if (!workflow) {
    return (
      <div className="history-inspector-empty">
        <p>Select a workflow from History to inspect it.</p>
      </div>
    );
  }

  const status = formatStatus(workflow.status);
  const goalText = workflow.goal || workflow.original_prompt || "";

  return (
    <div className="history-inspector">
      <div className="history-inspector-header">
        <button className="history-inspector-back" onClick={onClose} aria-label="Back">
          ← Back to History
        </button>
        <span className="history-inspector-title">History</span>
      </div>

      <div className="history-inspector-body">
        {/* Summary card */}
        <div className="history-detail-section history-detail-section--summary">
          <div className="history-detail-summary-header">
            <span className="history-detail-summary-id">
              Task {workflow.workflow_id?.slice(-8)}
            </span>
            <span
              className="history-status-badge"
              style={{ backgroundColor: status.color }}
            >
              {status.label}
            </span>
            <span className="history-retention-badge">
              {formatRetention(workflow.retention_state)}
            </span>
            {workflow.inspection_only && (
              <span className="history-inspection-badge">Inspection Only</span>
            )}
          </div>

          {goalText && <p className="history-detail-goal">{goalText}</p>}

          <div className="history-detail-summary-meta">
            <span>Created {formatDate(workflow.created_at)}</span>
            <span>·</span>
            <span>Updated {formatDate(workflow.updated_at)}</span>
          </div>
        </div>

        {/* Plan Details */}
        <div className="history-detail-section">
          <h5>Plan Details</h5>
          {projectionLoading ? (
            <div className="history-detail-projection-loading">
              <div className="spinner-small" />
              <span>Loading plan details…</span>
            </div>
          ) : projection ? (
            <div className="history-detail-projection">
              {projection.original_prompt && (
                <div className="history-detail-row">
                  <span className="history-detail-label">Prompt</span>
                  <span className="history-detail-value">
                    {projection.original_prompt}
                  </span>
                </div>
              )}
              {Array.isArray(projection.steps) && (
                <div className="history-detail-row">
                  <span className="history-detail-label">Steps</span>
                  <span className="history-detail-value">
                    {projection.steps.length}
                  </span>
                </div>
              )}
              {projection.input && (
                <div className="history-detail-row">
                  <span className="history-detail-label">Input</span>
                  <span className="history-detail-value">
                    {projection.input}
                  </span>
                </div>
              )}
            </div>
          ) : workflow.projection_available ? (
            <p className="history-detail-projection-missing">
              Plan details are not available for this historical workflow.
            </p>
          ) : (
            <p className="history-detail-projection-missing">
              Plan details were not available for this workflow.
            </p>
          )}
        </div>

        {/* Execution History — Phase 5A: read-only trace/event observability */}
        <div className="history-detail-section">
          <button
            className="history-detail-tech-toggle"
            onClick={() => setExecOpen((v) => !v)}
            aria-expanded={execOpen}
          >
            <span>Execution History</span>
            <span className="history-detail-tech-chevron">
              {execOpen ? "▼" : "▶"}
            </span>
          </button>
          {execOpen && (
            <div className="history-detail-tech-body">
              {/* Availability summary */}
              <div className="history-detail-row">
                <span className="history-detail-label">Trace</span>
                <span className={`history-detail-value ${workflow.trace_available ? "on" : "off"}`}>
                  {workflow.trace_available ? "Available" : "Not available"}
                </span>
              </div>
              <div className="history-detail-row">
                <span className="history-detail-label">Events</span>
                <span className={`history-detail-value ${workflow.events_available ? "on" : "off"}`}>
                  {workflow.events_available
                    ? `${workflow.event_count || 0} events`
                    : "Not available"}
                </span>
              </div>

              {execLoading ? (
                <div className="history-detail-projection-loading" style={{ marginTop: 12 }}>
                  <div className="spinner-small" />
                  <span>Loading execution history…</span>
                </div>
              ) : execShapeError ? (
                <p className="history-detail-projection-missing" style={{ marginTop: 12 }}>
                  Execution history data was returned in an unsupported shape.
                </p>
              ) : execError && !traceData && !eventsData ? (
                <p className="history-detail-projection-missing" style={{ marginTop: 12 }}>
                  Execution history could not be loaded.
                </p>
              ) : !workflow.trace_available && !workflow.events_available ? (
                <p className="history-detail-projection-missing" style={{ marginTop: 12 }}>
                  Execution history data unavailable for this workflow.
                </p>
              ) : (
                <div className="history-execution-list" style={{ marginTop: 12 }}>
                  {/* Trace entries */}
                  {Array.isArray(traceData) && traceData.length > 0 && (
                    <div className="history-execution-group">
                      <h6 className="history-execution-group-title">Trace</h6>
                      {traceData.slice(0, 50).map((entry, idx) => {
                        const e = safeTraceEntry(entry);
                        if (!e) return null;
                        return (
                          <div key={`t-${idx}`} className="history-execution-item">
                            <span className="history-execution-time">{formatEntryTime(e.ts)}</span>
                            <span className="history-execution-body">
                              {e.type && <span className="history-execution-type">{e.type}</span>}
                              {e.step && <span className="history-execution-step">{e.step}</span>}
                              {e.status && <span className={`history-execution-status ${e.status}`}>{e.status}</span>}
                              {e.msg && <span className="history-execution-msg">{e.msg}</span>}
                            </span>
                          </div>
                        );
                      })}
                      {traceData.length > 50 && (
                        <p className="history-execution-note">{traceData.length - 50} more trace entries not shown.</p>
                      )}
                    </div>
                  )}

                  {/* Event entries */}
                  {Array.isArray(eventsData) && eventsData.length > 0 && (
                    <div className="history-execution-group">
                      <h6 className="history-execution-group-title">Events</h6>
                      {eventsData.slice(0, 50).map((entry, idx) => {
                        const e = safeEventEntry(entry);
                        if (!e) return null;
                        return (
                          <div key={`e-${idx}`} className="history-execution-item">
                            <span className="history-execution-time">{formatEntryTime(e.ts)}</span>
                            <span className="history-execution-body">
                              {e.type && <span className="history-execution-type">{e.type}</span>}
                              {e.step && <span className="history-execution-step">{e.step}</span>}
                              {e.status && <span className={`history-execution-status ${e.status}`}>{e.status}</span>}
                              {e.msg && <span className="history-execution-msg">{e.msg}</span>}
                            </span>
                          </div>
                        );
                      })}
                      {eventsData.length > 50 && (
                        <p className="history-execution-note">{eventsData.length - 50} more events not shown.</p>
                      )}
                    </div>
                  )}

                  {/* Neither loaded nor available */}
                  {(!traceData || traceData.length === 0) && (!eventsData || eventsData.length === 0) && !execLoading && (
                    <p className="history-detail-projection-missing">
                      No execution history entries available.
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* LLM Calls — ISSUE-094D Phase 1 */}
        <div className="history-detail-section">
          <button
            className="history-detail-tech-toggle"
            onClick={() => setLlmOpen((v) => !v)}
            aria-expanded={llmOpen}
          >
            <span>LLM Calls</span>
            <span className="history-detail-tech-chevron">
              {llmOpen ? "▼" : "▶"}
            </span>
          </button>
          {llmOpen && (
            <div className="history-detail-tech-body">
              {llmLoading ? (
                <div className="history-detail-projection-loading" style={{ marginTop: 12 }}>
                  <div className="spinner-small" />
                  <span>Loading LLM calls…</span>
                </div>
              ) : llmError ? (
                <p className="history-detail-projection-missing" style={{ marginTop: 12 }}>
                  LLM calls could not be loaded.
                </p>
              ) : !llmData || llmData.length === 0 ? (
                <p className="history-detail-projection-missing" style={{ marginTop: 12 }}>
                  No LLM calls recorded for this workflow.
                </p>
              ) : (
                <div style={{ marginTop: 12, overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                    <thead>
                      <tr style={{ textAlign: "left", borderBottom: "1px solid #cbd5e1" }}>
                        <th style={{ padding: "4px 8px" }}>Time</th>
                        <th style={{ padding: "4px 8px" }}>Role</th>
                        <th style={{ padding: "4px 8px" }}>Provider</th>
                        <th style={{ padding: "4px 8px" }}>Model</th>
                        <th style={{ padding: "4px 8px" }}>Status</th>
                        <th style={{ padding: "4px 8px" }}>Cost</th>
                        <th style={{ padding: "4px 8px" }}>Route</th>
                      </tr>
                    </thead>
                    <tbody>
                      {llmData.map((entry, idx) => {
                        const statusColor = entry.status === "success" ? "#22c55e" : entry.status === "failure" ? "#ef4444" : "#64748b";
                        return (
                          <tr key={idx} style={{ borderBottom: "1px solid #e2e8f0" }}>
                            <td style={{ padding: "4px 8px", whiteSpace: "nowrap" }}>
                              {formatEntryTime(entry.timestamp_iso)}
                            </td>
                            <td style={{ padding: "4px 8px" }}>{entry.caller_role}</td>
                            <td style={{ padding: "4px 8px" }}>{entry.provider}</td>
                            <td style={{ padding: "4px 8px", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={entry.model}>
                              {entry.model}
                            </td>
                            <td style={{ padding: "4px 8px", color: statusColor, fontWeight: 600 }}>
                              {entry.status}
                              {entry.fallback_used && (
                                <span style={{ marginLeft: 4, fontSize: 11, color: "#64748b" }} title="fallback route used">(fb)</span>
                              )}
                            </td>
                            <td style={{ padding: "4px 8px", whiteSpace: "nowrap" }}>
                              ${Number(entry.estimated_cost_usd || 0).toFixed(4)}
                            </td>
                            <td style={{ padding: "4px 8px", fontSize: 12, color: "#64748b" }} title={entry.route_reason || ""}>
                              {humanizeRouteReason(entry.route_reason)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 4 }}>
                    (fb) = fallback route used
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Collapsible Technical Details */}
        <div className="history-detail-section history-detail-section--technical">
          <button
            className="history-detail-tech-toggle"
            onClick={() => setTechOpen((v) => !v)}
            aria-expanded={techOpen}
          >
            <span>Technical Details</span>
            <span className="history-detail-tech-chevron">
              {techOpen ? "▼" : "▶"}
            </span>
          </button>
          {techOpen && (
            <div className="history-detail-tech-body">
              <div className="history-detail-row">
                <span className="history-detail-label">Workflow ID</span>
                <span className="history-detail-value mono">
                  {workflow.workflow_id}
                </span>
              </div>
              <div className="history-detail-row">
                <span className="history-detail-label">Source</span>
                <span className="history-detail-value">
                  {formatSource(workflow.source)}
                </span>
              </div>
              <div className="history-detail-row">
                <span className="history-detail-label">Status</span>
                <span className="history-detail-value">
                  {workflow.status}
                </span>
              </div>
              <div className="history-detail-row">
                <span className="history-detail-label">Retention</span>
                <span className="history-detail-value">
                  {workflow.retention_state || "—"}
                </span>
              </div>
              {workflow.archived && (
                <div className="history-detail-row">
                  <span className="history-detail-label">Archived</span>
                  <span className="history-detail-value">Yes</span>
                </div>
              )}
              {workflow.dismissed && (
                <div className="history-detail-row">
                  <span className="history-detail-label">Dismissed</span>
                  <span className="history-detail-value">Yes</span>
                </div>
              )}
              <div className="history-detail-row">
                <span className="history-detail-label">Projection</span>
                <span
                  className={`history-detail-value ${workflow.projection_available ? "on" : "off"}`}
                >
                  {workflow.projection_available
                    ? "Available"
                    : "Not available"}
                </span>
              </div>
              <div className="history-detail-row">
                <span className="history-detail-label">Trace</span>
                <span
                  className={`history-detail-value ${workflow.trace_available ? "on" : "off"}`}
                >
                  {workflow.trace_available ? "Available" : "Not available"}
                </span>
              </div>
              <div className="history-detail-row">
                <span className="history-detail-label">Events</span>
                <span
                  className={`history-detail-value ${workflow.events_available ? "on" : "off"}`}
                >
                  {workflow.events_available
                    ? `${workflow.event_count || 0} events`
                    : "Not available"}
                </span>
              </div>
              {(workflow.planning_actionability || workflow.actionability) && (
                <>
                  {workflow.planning_actionability && (
                    <div className="history-detail-row">
                      <span className="history-detail-label">Planning</span>
                      <span className="history-detail-value">
                        {formatActionability(workflow.planning_actionability)}
                      </span>
                    </div>
                  )}
                  {workflow.actionability && (
                    <div className="history-detail-row">
                      <span className="history-detail-label">Runtime</span>
                      <span className="history-detail-value">
                        {formatActionability(workflow.actionability)}
                      </span>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
