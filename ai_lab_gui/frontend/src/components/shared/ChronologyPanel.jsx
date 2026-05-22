import { useState, useMemo, useRef, useEffect } from "react";

// Per REPLAY_VIRTUALIZATION_CHECKPOINT:
// Render-only window size. Full authoritative event array remains in memory.
// DOM rendering is virtualized; chronology semantics are NOT.
const VISIBLE_EVENT_LIMIT = 150;

// Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
// Human-readable event type labels for operator chronology visibility.
const EVENT_TYPE_LABEL = {
  step_started: "Step Started",
  step_completed: "Step Completed",
  step_failed: "Step Failed",
  step_blocked: "Step Blocked",
  step_retry: "Step Retry",
  state_transition: "State Transition",
  workflow_started: "Workflow Started",
  workflow_completed: "Workflow Completed",
  governance_decision: "Governance Decision",
  PROJECT_PAUSED: "Project Paused",
  PROJECT_RESUMED: "Project Resumed",
  PROJECT_FAILED: "Project Failed",
  PROJECT_BLOCKED: "Project Blocked",
  MESSAGE: "Message",
};

// Per LOW-RISK TIMELINE DRAWER EXPANSION:
// Frontend-only filter categories — purely passive grouping of authoritative event types.
// No synthetic categorization. No replay semantics. No causality inference.
const EVENT_FILTER_CATEGORIES = {
  all: { label: "All Events", types: null },
  lifecycle: {
    label: "Lifecycle",
    types: ["workflow_started", "workflow_completed", "PROJECT_PAUSED", "PROJECT_RESUMED", "PROJECT_FAILED", "PROJECT_BLOCKED"],
  },
  retries: { label: "Retries", types: ["step_retry"] },
  governance: { label: "Governance", types: ["governance_decision"] },
  failures: { label: "Failures", types: ["step_failed", "PROJECT_FAILED"] },
  steps: {
    label: "Step Events",
    types: ["step_started", "step_completed", "step_failed", "step_blocked", "step_retry", "state_transition"],
  },
};

/**
 * ChronologyPanel — WorkflowStudio-internal timeline sidebar component.
 *
 * Per WORKFLOWSTUDIO TIMELINE SIDEBAR IMPLEMENTATION:
 * Extracted from WorkflowPanel into a dedicated observability companion.
 *
 * Authority: CANONICAL_PROJECTION_MODEL_V1, EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1
 *
 * RULES:
 * - Renders authoritative events only — no synthesis
 * - Filtering is passive frontend grouping only
 * - No replay semantics, no causality inference
 */
export default function ChronologyPanel({ events, steps, executionGeneration, onClose }) {
  const [activeFilter, setActiveFilter] = useState("all");
  const [selectedStepId, setSelectedStepId] = useState("all");
  const [showAll, setShowAll] = useState(false);

  // Per REPLAY_VIRTUALIZATION_CHECKPOINT:
  // Scroll container ref for anchoring stability.
  const scrollRef = useRef(null);
  const prevEventCountRef = useRef(0);
  const shouldAutoScrollRef = useRef(true);

  // ── Memoized derived data (Sub-phase 3C: filter memoization) ─────────────

  // Sort by bus_sequence_id for deterministic chronological order
  const sortedEvents = useMemo(() => {
    return [...events].sort(
      (a, b) => (a.bus_sequence_id || 0) - (b.bus_sequence_id || 0)
    );
  }, [events]);

  const stepMap = useMemo(() => {
    const map = {};
    for (const s of steps) {
      map[s.id] = s;
    }
    return map;
  }, [steps]);

  // Build step options from authoritative events only — no synthesis
  const stepOptions = useMemo(() => {
    const options = [];
    const seen = new Set();
    for (const event of sortedEvents) {
      const sid = event.data?.step_id;
      if (sid && !seen.has(sid)) {
        seen.add(sid);
        options.push({ id: sid, name: stepMap[sid]?.purpose || sid });
      }
    }
    return options;
  }, [sortedEvents, stepMap]);

  const filteredEvents = useMemo(() => {
    const category = EVENT_FILTER_CATEGORIES[activeFilter];
    return sortedEvents.filter((event) => {
      if (category?.types && !category.types.includes(event.event_type)) {
        return false;
      }
      if (selectedStepId !== "all" && event.data?.step_id !== selectedStepId) {
        return false;
      }
      return true;
    });
  }, [sortedEvents, activeFilter, selectedStepId]);

  // ── Render-only virtualization (Sub-phase 3A) ─────────────────────────

  const isTruncated = !showAll && filteredEvents.length > VISIBLE_EVENT_LIMIT;
  const sliceStart = isTruncated
    ? Math.max(0, filteredEvents.length - VISIBLE_EVENT_LIMIT)
    : 0;
  const visibleEvents = isTruncated
    ? filteredEvents.slice(sliceStart)
    : filteredEvents;

  // Preserve generation boundary at virtual window start
  const windowStartBoundary = useMemo(() => {
    if (sliceStart === 0 || !filteredEvents[sliceStart]) return null;
    const prevGen = filteredEvents[sliceStart - 1]?.data?.execution_generation;
    const currGen = filteredEvents[sliceStart]?.data?.execution_generation;
    if (prevGen != null && currGen != null && prevGen !== currGen) {
      return currGen;
    }
    return null;
  }, [filteredEvents, sliceStart]);

  // ── Scroll anchoring stability (Sub-phase 3B) ───────────────────────────

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const handleScroll = () => {
      const threshold = 40; // pixels from bottom
      shouldAutoScrollRef.current =
        el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
    };

    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, []);

  // Auto-scroll to bottom on new event append
  useEffect(() => {
    const currentCount = filteredEvents.length;
    const prevCount = prevEventCountRef.current;
    prevEventCountRef.current = currentCount;

    const el = scrollRef.current;
    if (!el) return;

    if (currentCount > prevCount && shouldAutoScrollRef.current) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [filteredEvents.length]);

  function formatTime(isoString) {
    if (!isoString) return "";
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      return isoString;
    }
  }

  function eventSummary(event) {
    const { event_type, data } = event;
    const label = EVENT_TYPE_LABEL[event_type] || event_type;
    const stepId = data?.step_id;
    const stepName = stepMap[stepId]?.purpose || stepId || "";

    switch (event_type) {
      case "step_started":
        return `${label}${stepName ? ` — ${stepName}` : ""}`;
      case "step_completed":
        return `${label} (${data?.status || "unknown"})${stepName ? ` — ${stepName}` : ""}`;
      case "step_failed":
        return `${label}${stepName ? ` — ${stepName}` : ""}${data?.reason ? `: ${data.reason}` : ""}`;
      case "step_blocked":
        return `${label}${stepName ? ` — ${stepName}` : ""}${data?.blocked_reason ? `: ${data.blocked_reason}` : ""}`;
      case "step_retry":
        return `${label} #${data?.retry_count ?? "?"}${stepName ? ` — ${stepName}` : ""}`;
      case "state_transition":
        return `${label}: ${data?.previous_state || "?"} → ${data?.new_state || "?"}${stepName ? ` (${stepName})` : ""}`;
      case "workflow_started":
        return `${label}${data?.workflow_name ? ` — ${data.workflow_name}` : ""}`;
      case "workflow_completed":
        return `${label} (${data?.status || "unknown"})`;
      case "governance_decision":
        return `${label}: ${data?.decision || "?"}${stepName ? ` — ${stepName}` : ""}`;
      case "PROJECT_PAUSED":
      case "PROJECT_RESUMED":
      case "PROJECT_FAILED":
        return label;
      case "MESSAGE":
        return `${label}${data?.message ? `: ${data.message}` : ""}`;
      default:
        return label;
    }
  }

  const isGovEvent = (type) => type === "governance_decision";
  const isRetryEvent = (type) => type === "step_retry";

  return (
    <div
      className="chronology-panel"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        fontSize: "0.75rem",
        background: "#0f172a",
      }}
    >
      {/* Header */}
      <div
        className="chronology-panel__header"
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "0.5rem 0.75rem",
          borderBottom: "1px solid #334155",
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          <span style={{ fontWeight: 600, color: "#e2e8f0" }}>Chronology</span>
          {executionGeneration > 1 && (
            <span
              style={{
                fontSize: "0.65rem",
                color: "#94a3b8",
                background: "#1e293b",
                padding: "0.1rem 0.4rem",
                borderRadius: "0.125rem",
              }}
              title="Current execution generation"
            >
              Gen {executionGeneration}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <span style={{ color: "#64748b" }}>{filteredEvents.length} events</span>
          {onClose && (
            <button
              onClick={onClose}
              title="Close chronology"
              style={{
                background: "none",
                border: "none",
                color: "#94a3b8",
                cursor: "pointer",
                fontSize: "0.8rem",
                lineHeight: 1,
                padding: "0.1rem",
              }}
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Filters */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.35rem",
          padding: "0.5rem 0.75rem",
          borderBottom: "1px solid #1e293b",
          alignItems: "center",
          flexShrink: 0,
        }}
      >
        {Object.entries(EVENT_FILTER_CATEGORIES).map(([key, cfg]) => {
          const active = activeFilter === key;
          return (
            <button
              key={key}
              onClick={() => setActiveFilter(key)}
              style={{
                fontSize: "0.65rem",
                padding: "0.2rem 0.5rem",
                borderRadius: "0.25rem",
                border: "none",
                cursor: "pointer",
                background: active ? "#3b82f6" : "#1e293b",
                color: active ? "#fff" : "#94a3b8",
                whiteSpace: "nowrap",
              }}
            >
              {cfg.label}
            </button>
          );
        })}

        {stepOptions.length > 0 && (
          <select
            value={selectedStepId}
            onChange={(e) => setSelectedStepId(e.target.value)}
            style={{
              marginLeft: "auto",
              fontSize: "0.7rem",
              background: "#1e293b",
              color: "#e2e8f0",
              border: "1px solid #334155",
              borderRadius: "0.25rem",
              padding: "0.2rem 0.4rem",
              cursor: "pointer",
            }}
          >
            <option value="all">All Steps</option>
            {stepOptions.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Event list */}
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "0.5rem 0.75rem",
          minHeight: 0,
        }}
      >
        {filteredEvents.length === 0 ? (
          <div style={{ color: "#64748b", textAlign: "center", padding: "1rem 0" }}>
            No events match the selected filters.
          </div>
        ) : (
          <ol className="event-list" style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {/* Render-only virtualization: expansion controls at truncation boundary */}
            {isTruncated && (
              <li style={{ textAlign: "center", padding: "0.5rem 0" }}>
                <button
                  onClick={() => setShowAll(true)}
                  className="chronology-show-all-btn"
                  title={`Show all ${filteredEvents.length} events`}
                >
                  Show All Events ({filteredEvents.length})
                </button>
              </li>
            )}
            {showAll && filteredEvents.length > VISIBLE_EVENT_LIMIT && (
              <li style={{ textAlign: "center", padding: "0.5rem 0" }}>
                <button
                  onClick={() => setShowAll(false)}
                  className="chronology-show-all-btn"
                >
                  Show Less
                </button>
              </li>
            )}

            {/* Generation boundary at virtual window start — purely visual */}
            {windowStartBoundary && (
              <li key="window-gen-boundary">
                <div className="generation-boundary">
                  <span>━━ Execution Generation {windowStartBoundary} ━━</span>
                </div>
              </li>
            )}

            {visibleEvents.map((event, i) => {
              const { event_type, bus_sequence_id, timestamp } = event;
              const label = EVENT_TYPE_LABEL[event_type] || event_type;
              const summary = eventSummary(event);
              const time = formatTime(timestamp || event.data?.timestamp);
              const gov = isGovEvent(event_type);
              const retry = isRetryEvent(event_type);

              // Per INCREMENTAL CHRONOLOGY HYDRATION:
              // Detect execution_generation boundary between adjacent events.
              // Purely visual grouping — no inferred causality.
              // Use actual index in filteredEvents for correctness under virtualization.
              const actualIndex = sliceStart + i;
              const prevGen =
                actualIndex > 0 ? filteredEvents[actualIndex - 1]?.data?.execution_generation : null;
              const currGen = event.data?.execution_generation;
              const showGenBoundary =
                prevGen != null && currGen != null && prevGen !== currGen;

              return (
                <li key={event.event_id || i}>
                  {showGenBoundary && (
                    <div className="generation-boundary">
                      <span>━━ Execution Generation {currGen} ━━</span>
                    </div>
                  )}
                  {retry && (
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.35rem",
                        color: "#8b5cf6",
                        fontSize: "0.65rem",
                        fontWeight: 600,
                        margin: "0.35rem 0 0.15rem",
                        paddingLeft: "0.25rem",
                      }}
                    >
                      <span>↻</span>
                      <span>Retry boundary — {summary}</span>
                    </div>
                  )}
                  <div
                    className="event-item"
                    style={{
                      padding: "0.35rem 0.25rem",
                      borderBottom: actualIndex < filteredEvents.length - 1 ? "1px solid #1e293b" : "none",
                      display: "flex",
                      alignItems: "baseline",
                      gap: "0.5rem",
                      borderLeft: gov ? "2px solid #f59e0b" : "2px solid transparent",
                      marginLeft: gov ? "-0.25rem" : undefined,
                      paddingLeft: gov ? "0.25rem" : undefined,
                      borderRadius: gov ? "0 0.125rem 0.125rem 0" : undefined,
                      background: gov ? "rgba(245, 158, 11, 0.06)" : undefined,
                    }}
                  >
                    <span style={{ color: "#64748b", whiteSpace: "nowrap", minWidth: "4.5rem", fontVariantNumeric: "tabular-nums" }}>
                      {time}
                    </span>
                    <span
                      className="event-type-badge"
                      style={{
                        fontSize: "0.65rem",
                        padding: "0.1rem 0.35rem",
                        borderRadius: "0.125rem",
                        background: eventTypeColor(event_type),
                        color: "#fff",
                        whiteSpace: "nowrap",
                        minWidth: "6.5rem",
                        textAlign: "center",
                        fontWeight: 500,
                      }}
                    >
                      {label}
                    </span>
                    <span style={{ color: "#cbd5e1", lineHeight: 1.4 }}>{summary}</span>
                    {bus_sequence_id && (
                      <span style={{ color: "#475569", fontSize: "0.65rem", marginLeft: "auto", fontVariantNumeric: "tabular-nums" }} title="Event sequence order">
                        #{bus_sequence_id}
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}

function eventTypeColor(eventType) {
  switch (eventType) {
    case "step_started": return "#3b82f6";
    case "step_completed": return "#22c55e";
    case "step_failed": return "#ef4444";
    case "step_blocked": return "#f59e0b";
    case "step_retry": return "#8b5cf6";
    case "state_transition": return "#06b6d4";
    case "workflow_started": return "#10b981";
    case "workflow_completed": return "#059669";
    case "governance_decision": return "#6366f1";
    case "PROJECT_PAUSED": return "#f59e0b";
    case "PROJECT_RESUMED": return "#10b981";
    case "PROJECT_FAILED": return "#ef4444";
    case "MESSAGE": return "#64748b";
    default: return "#475569";
  }
}
