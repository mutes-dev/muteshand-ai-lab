import { useState, useEffect } from "react";
import { api } from "../api.js";

/**
 * History Tab - ISSUE-061 Phase 4C
 *
 * Loads and displays historical workflows from GET /workflows/historical.
 *
 * Per WORKFLOW_RETENTION_AND_ARCHIVAL_CONTRACT_V1:
 * - History represents previously existing workflows.
 * - History is observability-oriented and inspection-oriented.
 * - History is non-actionable. No Attach, Resume, Retry, Replan, Archive, or Dismiss buttons.
 *
 * Required behavior:
 * - Calls api.getHistoricalWorkflows() on mount.
 * - Renders loading, error, empty, and loaded states.
 * - Displays workflow_id suffix, status, retention_state, inspection_only,
 *   archived/dismissed badges, updated time, goal/prompt, and
 *   projection/trace/events availability as read-only metadata.
 * - Does not fetch projections, traces, or events.
 * - Tolerates missing or malformed fields without crashing.
 * - Sorts by backend-authored history_sort_timestamp DESC.
 * - onInspect callback tells parent to open History Inspector in main workspace.
 * - selectedWorkflowId highlights the currently inspected card.
 */

const FILTERS = ["all", "archived", "dismissed", "terminal"];

const FILTER_LABELS = {
  all: "All",
  archived: "Archived",
  dismissed: "Dismissed",
  terminal: "Terminal",
};

// ISSUE-061: Default History excludes retained actionable statuses that belong in Task Hub.
const ACTIONABLE_HISTORY_EXCLUDED_STATUSES = new Set([
  "ACTIVE",
  "PAUSED",
  "PENDING_RECOVERY",
  "QUEUED",
  "FAILED",
]);

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
  if (!ts) return "";
  let date;
  if (typeof ts === "string" && ts.includes("T")) {
    date = new Date(ts);
  } else if (typeof ts === "number" && ts > 1e10) {
    date = new Date(ts);
  } else {
    date = new Date(ts * 1000);
  }
  if (isNaN(date.getTime())) return "";
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function truncate(str, len = 80) {
  if (!str || typeof str !== "string") return null;
  const trimmed = str.trim();
  if (!trimmed) return null;
  return trimmed.length > len ? trimmed.slice(0, len) + "…" : trimmed;
}

function getSortTimestamp(w) {
  const ts = w.history_sort_timestamp ?? w.updated_at ?? w.created_at;
  if (!ts) return 0;
  if (typeof ts === "number") return ts;
  const d = new Date(ts);
  return isNaN(d.getTime()) ? 0 : d.getTime();
}

function formatRetention(state) {
  const map = {
    retained: "Retained",
    archived: "Archived",
    dismissed: "Dismissed",
  };
  return map[state] || state || "Retained";
}

const HISTORY_SEARCH_KEY = "history_search_query";

function normalizeSearchText(value) {
  return (value || "").toLowerCase().trim();
}

function buildWorkflowSearchText(workflow) {
  const parts = [];
  const push = (val) => {
    if (val != null) parts.push(String(val));
  };
  push(workflow.workflow_id);
  // suffix without "workflow_"
  if (workflow.workflow_id) {
    push(workflow.workflow_id.replace(/^workflow_/, ""));
  }
  push(workflow.goal);
  push(workflow.original_prompt);
  push(workflow.status);
  push(workflow.retention_state);
  push(workflow.source);
  push(workflow.actionability);
  push(workflow.planning_actionability);
  return normalizeSearchText(parts.join(" "));
}

export default function HistoryTab({ onInspect, selectedWorkflowId }) {
  const [workflows, setWorkflows] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState(() => {
    return sessionStorage.getItem(HISTORY_SEARCH_KEY) || "";
  });

  async function loadWorkflows() {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.getHistoricalWorkflows();
      const list = res.workflows || [];
      // Sort by backend-authored history_sort_timestamp DESC, then fallback chain
      list.sort((a, b) => getSortTimestamp(b) - getSortTimestamp(a));
      setWorkflows(list);
      console.log("[GUI:HISTORY_LOAD]", { count: list.length, timestamp: Date.now() });
    } catch (err) {
      console.error("[GUI:HISTORY_LOAD_ERROR]", { error: err.message, timestamp: Date.now() });
      setError(err.message || "Failed to load historical workflows");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadWorkflows();
  }, []);

  useEffect(() => {
    if (searchQuery) {
      sessionStorage.setItem(HISTORY_SEARCH_KEY, searchQuery);
    } else {
      sessionStorage.removeItem(HISTORY_SEARCH_KEY);
    }
  }, [searchQuery]);

  const normalizedQuery = normalizeSearchText(searchQuery);

  const filteredWorkflows = workflows.filter((w) => {
    if (filter === "archived") return w.archived === true;
    if (filter === "dismissed") return w.dismissed === true;
    if (filter === "terminal") return w.inspection_only === true;
    // "all" = default historical view.
    // === ISSUE-062: Backend-authored history_eligible takes precedence ===
    // Per LIFECYCLE_AUTHORITY_CONTRACT_V1: lifecycle state ≠ actionability.
    // Frontend MUST NOT infer History membership from status alone.
    if (typeof w.history_eligible === "boolean") {
      return w.history_eligible;
    }
    // Backward compatibility: fall back to status-based logic for old workflows
    const retention = w.retention_state || "retained";
    const isArchivedOrDismissed = retention === "archived" || retention === "dismissed";
    const isActionable = ACTIONABLE_HISTORY_EXCLUDED_STATUSES.has(w.status);
    return isArchivedOrDismissed || !isActionable;
  });

  const searchedWorkflows = normalizedQuery
    ? filteredWorkflows.filter((w) => buildWorkflowSearchText(w).includes(normalizedQuery))
    : filteredWorkflows;

  return (
    <div className="history-tab">
      {/* Header */}
      <div className="history-header">
        <div className="history-title-section">
          <h4>History</h4>
          <span className="history-count">
            {normalizedQuery
              ? `${searchedWorkflows.length} matching workflow${searchedWorkflows.length === 1 ? "" : "s"}`
              : `${workflows.length} workflow${workflows.length === 1 ? "" : "s"}`}
          </span>
        </div>
        <button className="history-refresh-btn" onClick={loadWorkflows} disabled={isLoading}>
          {isLoading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {/* Filters */}
      <div className="history-filter-bar">
        {FILTERS.map((f) => (
          <button
            key={f}
            className={`history-filter-btn ${filter === f ? "active" : ""}`}
            onClick={() => setFilter(f)}
          >
            {FILTER_LABELS[f]}
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="history-search-bar">
        <input
          type="text"
          className="history-search-input"
          placeholder="Search history…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          aria-label="Search history"
        />
        {searchQuery && (
          <button
            className="history-search-clear"
            onClick={() => setSearchQuery("")}
            aria-label="Clear search"
          >
            ✕
          </button>
        )}
      </div>

      {/* Content */}
      <div className="history-content">
        {isLoading && workflows.length === 0 ? (
          <div className="history-loading">
            <div className="spinner-medium" />
            <span>Loading history…</span>
          </div>
        ) : error ? (
          <div className="history-error">
            <div className="history-error-icon">⚠️</div>
            <p>{error}</p>
            <button className="history-retry-btn" onClick={loadWorkflows}>
              Retry
            </button>
          </div>
        ) : searchedWorkflows.length === 0 ? (
          <div className="history-empty">
            <div className="history-empty-icon">📚</div>
            <h4>{normalizedQuery ? "No workflows match this search." : "No historical workflows"}</h4>
            <p>
              {normalizedQuery
                ? `Try a different query.`
                : filter === "all"
                  ? "Completed, cancelled, archived, and dismissed workflows will appear here."
                  : `No ${FILTER_LABELS[filter].toLowerCase()} workflows found.`}
            </p>
          </div>
        ) : (
          <div className="history-list">
            {searchedWorkflows.map((w) => {
              const status = formatStatus(w.status);
              const goalLabel = truncate(w.goal || w.original_prompt, 120) || `Task ${w.workflow_id?.slice(-8)}`;
              const isSelected = w.workflow_id === selectedWorkflowId;
              return (
                <div key={w.workflow_id} className={`history-item ${isSelected ? "selected" : ""}`}>
                  <div className="history-item-top">
                    <span className="history-item-suffix">Task {w.workflow_id?.slice(-8)}</span>
                    <div className="history-item-top-badges">
                      <span
                        className="history-status-badge"
                        style={{ backgroundColor: status.color }}
                      >
                        {status.label}
                      </span>
                      <span className="history-retention-badge">
                        {formatRetention(w.retention_state)}
                      </span>
                      {w.archived && <span className="history-archive-badge">Archived</span>}
                      {w.dismissed && <span className="history-dismiss-badge">Dismissed</span>}
                      {w.inspection_only && <span className="history-inspection-badge">Inspection Only</span>}
                    </div>
                  </div>

                  <div className="history-item-goal">{goalLabel}</div>

                  <div className="history-item-footer">
                    <div className="history-item-footer-left">
                      <span className="history-item-when">
                        {w.updated_at ? formatDate(w.updated_at) : ""}
                      </span>
                      <div className="history-item-obs-dots">
                        {w.projection_available && (
                          <span className="history-obs-dot on" title="Plan details available">●</span>
                        )}
                        {w.trace_available && (
                          <span className="history-obs-dot on" title="Trace available">●</span>
                        )}
                        {w.events_available && (
                          <span className="history-obs-dot on" title={`${w.event_count || 0} events`}>●</span>
                        )}
                      </div>
                    </div>
                    <button
                      className="history-inspect-btn"
                      onClick={() => onInspect?.(w)}
                    >
                      View Details →
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
