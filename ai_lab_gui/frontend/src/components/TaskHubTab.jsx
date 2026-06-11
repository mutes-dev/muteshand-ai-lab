import { useState, useEffect, useRef } from "react";
import { api } from "../api.js";

/**
 * Task Hub Tab - Extracted from WorkflowManager for Phase 1 Shell
 * 
 * Preserves all existing Task Hub behavior while adapting to tab context.
 * 
 * Per WORKFLOW_RETENTION_AND_ARCHIVAL_CONTRACT_V1 + KNOWN_ISSUES_V2 ISSUE-061:
 * Task Hub must be actionable/recoverable only. Immutable terminal inspection-only
 * workflows (CANCELLED, COMPLETED) belong in future History, not active Task Hub.
 */

// Per GUI_FUNCTIONALITY_CONTRACT_V1 + KNOWN_ISSUES_V2 ISSUE-061:
// QUARANTINED is non-recoverable and must be excluded from actionable surfaces.
const TASK_HUB_EXCLUDED_STATUSES = new Set(["CANCELLED", "COMPLETED", "QUARANTINED"]);

function isTaskHubEligible(workflow) {
  // === ISSUE-062: Backend-authored taskhub_eligible takes precedence ===
  // Per LIFECYCLE_AUTHORITY_CONTRACT_V1: lifecycle state ≠ actionability.
  // Frontend MUST NOT infer actionability from status alone.
  if (typeof workflow.taskhub_eligible === "boolean") {
    return workflow.taskhub_eligible;
  }

  // === ISSUE-098KX: Defensive fallback for FAILED recoverable workflows ===
  // If backend-authored taskhub_eligible is missing, FAILED + failed_recoverable
  // must still appear in Task Hub so Retry Failed Step remains accessible.
  if (workflow.status === "FAILED" && workflow.failed_recoverable === true) {
    const retention = workflow.retention_state || "retained";
    if (retention !== "archived" && retention !== "dismissed") {
      return true;
    }
  }

  // Backward compatibility: fall back to status-based eligibility for old workflows
  // Per WORKFLOW_RETENTION_AND_ARCHIVAL_CONTRACT_V1:
  // Task Hub excludes archived and dismissed workflows.
  const retention = workflow.retention_state || "retained";
  if (retention === "archived" || retention === "dismissed") {
    return false;
  }

  // Exclude immutable terminal states (CANCELLED, COMPLETED)
  if (TASK_HUB_EXCLUDED_STATUSES.has(workflow.status)) {
    return false;
  }

  // Exclude inspection-only workflows
  if (workflow.inspection_only === true) {
    return false;
  }

  return true;
}

function formatStatus(status) {
  const statusMap = {
    QUEUED: { color: "#64748b", label: "Queued" },
    ACTIVE: { color: "#22c55e", label: "Active" },
    PAUSED: { color: "#f97316", label: "Paused" },
    BLOCKED: { color: "#f97316", label: "Blocked" },
    PENDING_RECOVERY: { color: "#fbbf24", label: "Recovering" },
    FAILED: { color: "#ef4444", label: "Failed" },
    COMPLETED: { color: "#64748b", label: "Completed" },
    CANCELLED: { color: "#64748b", label: "Cancelled" },
  };
  return statusMap[status] || { color: "#64748b", label: status };
}

// === ISSUE-055B Phase 2: Safe actionability helpers ===
// Tolerate missing backend fields for old workflows
function isQueuedReplanRequired(workflow) {
  if (!workflow) return false;
  if (workflow.status !== "QUEUED") return false;
  if (workflow.actionability === "PLANNING_REPLAN") return true;
  if (workflow.planning_actionability === "REPLAN_REQUIRED") return true;
  return false;
}

function isQueuedLivePlanning(workflow) {
  if (!workflow) return false;
  if (workflow.status !== "QUEUED") return false;
  if (workflow.live_planning === true) return true;
  if (workflow.actionability === "LIVE_PLANNING") return true;
  return false;
}

function getActionability(workflow) {
  if (workflow && typeof workflow.actionability === "string") {
    return workflow.actionability;
  }
  if (workflow?.inspection_only === true) return "INSPECTION_ONLY";
  if (workflow?.recoverable === true) return "RUNTIME_RECOVERABLE";
  return "INSPECTION_ONLY";
}

function getStatusProgress(workflow) {
  if (!workflow.steps || workflow.steps.length === 0) return 0;
  const completed = workflow.steps.filter(step =>
    step.status === "COMPLETED" || step.status === "FAILED"
  ).length;
  return Math.round((completed / workflow.steps.length) * 100);
}

function hasBlockedApprovalStep(workflow) {
  if (!workflow.steps || workflow.steps.length === 0) return false;
  return workflow.steps.some(
    (step) =>
      step.status === "BLOCKED" &&
      step.blocked_reason &&
      (step.blocked_reason === "approval_required" || step.blocked_reason.includes("approval"))
  );
}

function formatDate(timestamp) {
  if (!timestamp) return "";
  // Defensive: handle ISO strings, milliseconds, and Unix seconds
  let date;
  if (typeof timestamp === "string" && timestamp.includes("T")) {
    date = new Date(timestamp);
  } else if (typeof timestamp === "number" && timestamp > 1e10) {
    date = new Date(timestamp);
  } else {
    date = new Date(timestamp * 1000);
  }
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

// TASK_HUB_SEARCH: Storage key for search query persistence
const TASKHUB_SEARCH_KEY = "taskhub_search_query";

function normalizeSearchText(value) {
  return (value || "").toLowerCase().trim();
}

function buildWorkflowSearchText(workflow, hint) {
  const parts = [];
  const push = (val) => {
    if (val != null) parts.push(String(val));
  };
  // Operator-visible identity fields (shown on Task Hub cards)
  push(workflow.workflow_id);
  // suffix without "workflow_"
  if (workflow.workflow_id) {
    push(workflow.workflow_id.replace(/^workflow_/, ""));
  }
  // Resolved visible card title (what the operator actually sees as the task description)
  // This is the same hint rendered as humanHint on the card.
  push(hint);
  // Visible text fallback fields (used when hint is absent — same priority chain as humanHint render)
  push(workflow.title);
  push(workflow.goal);
  push(workflow.original_prompt);
  push(workflow.prompt);
  // Visible status badge label (e.g. "Active", "Failed", "Blocked", "Paused")
  push(formatStatus(workflow.status).label);
  // Raw status value for case-insensitive match (e.g. "BLOCKED", "FAILED")
  push(workflow.status);
  return normalizeSearchText(parts.join(" "));
}

export default function TaskHubTab({
  currentWorkflowId,
  currentStatus,
  onWorkflowSelect,
  onNewWorkflow,
  onDetachWorkflow,
  isExecuting,
  onReplan,
}) {
  const [workflows, setWorkflows] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSwitching, setIsSwitching] = useState(false);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState(null);
  const [workflowHints, setWorkflowHints] = useState({});
  const [replanningId, setReplanningId] = useState(null);
  // TASK_HUB_SEARCH: Search query state with sessionStorage persistence
  const [searchQuery, setSearchQuery] = useState(() => {
    return sessionStorage.getItem(TASKHUB_SEARCH_KEY) || "";
  });
  const scrollRef = useRef(null);
  const switchTimeoutRef = useRef(null);
  const hintsLoadingRef = useRef(false);

  // Load workflows from authoritative source
  async function loadWorkflows() {
    setIsLoading(true);
    try {
      const res = await api.getAuthoritativeWorkflows();
      const allWorkflows = res.workflows || [];

      // Filter to actionable/recoverable workflows only
      const taskHubWorkflows = allWorkflows.filter(isTaskHubEligible);

      // TASK_HUB_ORDERING_FIX: Strict newest-to-oldest sort using backend timestamp
      const getSortTs = (w) => {
        // Prefer backend taskhub_sort_timestamp, then fallback chain
        return w.taskhub_sort_timestamp || w.last_updated || w.updated_at || w.created_at || 0;
      };
      // Strict timestamp descending - no recoverable-first prioritization
      const sorted = taskHubWorkflows.sort((a, b) => getSortTs(b) - getSortTs(a));
      setWorkflows(sorted);



      // Fetch hints in background — non-blocking, optional enrichment only.
      // Per TASK_HUB_FOREVER_LOADING_FIX: base list must render even if hints fail.
      loadWorkflowHints(sorted);
    } catch (err) {
      console.error("[GUI:TASK_HUB_LOAD_ERROR]", {
        error: err.message,
        timestamp: Date.now(),
      });
    } finally {
      setIsLoading(false);
    }
  }

  // Load workflow hints for better UX
  // Per TASK_HUB_FOREVER_LOADING_FIX:
  // - Hints are optional enrichment only; one failed hint must not block the whole Task Hub.
  // - Uses Promise.allSettled + per-hint timeout so slow/failed projections do not stall.
  // - Overlapping calls are suppressed via hintsLoadingRef.
  async function loadWorkflowHints(workflowList) {
    if (hintsLoadingRef.current) {
      console.log("[GUI:TASK_HUB_HINT_LOAD_SUPPRESSED]", {
        reason: "already_in_progress",
        workflowCount: workflowList.length,
        timestamp: Date.now(),
      });
      return;
    }
    hintsLoadingRef.current = true;

    const HINT_FETCH_TIMEOUT_MS = 2000;

    try {
      const hintPromises = workflowList.map(async (workflow) => {
        // ISSUE-055B Phase 2: skip projection fetch when backend says it's expected missing
        if (workflow.projection_expected_missing === true) {
          const prompt = workflow.planning_request?.original_prompt || workflow.goal;
          return {
            workflowId: workflow.workflow_id,
            hint: prompt || null,
            source: "planning_request",
          };
        }

        const fetchPromise = (async () => {
          try {
            const projection = await api.getProjection(workflow.workflow_id);
            if (projection?.original_prompt) {
              return { workflowId: workflow.workflow_id, hint: projection.original_prompt, source: "original_prompt" };
            } else if (projection?.input) {
              return { workflowId: workflow.workflow_id, hint: projection.input, source: "input" };
            } else if (projection?.steps?.[0]?.purpose) {
              return { workflowId: workflow.workflow_id, hint: projection.steps[0].purpose, source: "step_purpose" };
            }
            return { workflowId: workflow.workflow_id, hint: null, source: "none" };
          } catch (err) {
            console.log("[GUI:TASK_HUB_HINT_LOAD_FAILED]", {
              workflowId: workflow.workflow_id,
              error: err.message,
              timestamp: Date.now(),
            });
            return { workflowId: workflow.workflow_id, hint: null, source: "error" };
          }
        })();

        const timeoutPromise = new Promise((resolve) => {
          setTimeout(() => {
            resolve({ workflowId: workflow.workflow_id, hint: null, source: "timeout" });
          }, HINT_FETCH_TIMEOUT_MS);
        });

        return Promise.race([fetchPromise, timeoutPromise]);
      });

      const results = await Promise.allSettled(hintPromises);

      const hints = {};
      let successCount = 0;
      let timeoutCount = 0;
      let failCount = 0;

      for (const result of results) {
        if (result.status === "fulfilled") {
          const { workflowId, hint, source } = result.value;
          if (hint) {
            hints[workflowId] = hint;
            successCount++;
          } else if (source === "timeout") {
            timeoutCount++;
          } else if (source === "error") {
            failCount++;
          }
        } else {
          failCount++;
        }
      }

      setWorkflowHints(hints);

      console.log("[GUI:TASK_HUB_HINT_LOAD_COMPLETE]", {
        total: workflowList.length,
        success: successCount,
        timeout: timeoutCount,
        fail: failCount,
        timestamp: Date.now(),
      });
    } finally {
      hintsLoadingRef.current = false;
    }
  }

  // Handle workflow selection with loading feedback
  function handleSelect(workflow) {


    // Show loading feedback immediately
    setSelectedWorkflowId(workflow.workflow_id);
    setIsSwitching(true);

    // Clear any existing timeout
    if (switchTimeoutRef.current) {
      clearTimeout(switchTimeoutRef.current);
    }

    // Call the selection handler
    onWorkflowSelect(workflow);

    // Keep loading state visible briefly for UX feedback, then clear
    switchTimeoutRef.current = setTimeout(() => {
      setIsSwitching(false);
      setSelectedWorkflowId(null);
    }, 800);
  }

  // Handle new workflow creation
  function handleNewWorkflow() {

    onNewWorkflow();
  }

  // Handle workflow archive
  async function handleArchive(workflow) {
    try {


      await api.archiveWorkflow(workflow.workflow_id);

      // Reload workflows after successful archive
      await loadWorkflows();


    } catch (err) {
      console.error("[GUI:TASK_HUB_ARCHIVE_ERROR]", {
        workflowId: workflow.workflow_id,
        error: err.message,
        timestamp: Date.now(),
      });
    }
  }

  // Handle workflow dismiss
  async function handleDismiss(workflow) {
    try {


      await api.dismissWorkflow(workflow.workflow_id);

      // Reload workflows after successful dismiss
      await loadWorkflows();


    } catch (err) {
      console.error("[GUI:TASK_HUB_DISMISS_ERROR]", {
        workflowId: workflow.workflow_id,
        error: err.message,
        timestamp: Date.now(),
      });
    }
  }

  // Initial load and periodic refresh
  useEffect(() => {
    loadWorkflows();
  }, []);

  // Periodic refresh while Task Hub tab is active
  useEffect(() => {
    const intervalId = setInterval(() => {
      loadWorkflows();
    }, 3000);
    return () => clearInterval(intervalId);
  }, []);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (switchTimeoutRef.current) {
        clearTimeout(switchTimeoutRef.current);
      }
    };
  }, []);

  // TASK_HUB_SEARCH: Persist search query to sessionStorage
  useEffect(() => {
    if (searchQuery) {
      sessionStorage.setItem(TASKHUB_SEARCH_KEY, searchQuery);
    } else {
      sessionStorage.removeItem(TASKHUB_SEARCH_KEY);
    }
  }, [searchQuery]);

  const recoverableCount = workflows.filter(w => w.recoverable && !isQueuedReplanRequired(w)).length;

  // TASK_HUB_SEARCH: Apply search filter to workflows
  // Pass workflowHints so search matches the actual visible card title text.
  const normalizedQuery = normalizeSearchText(searchQuery);
  const filteredWorkflows = normalizedQuery
    ? workflows.filter((w) => buildWorkflowSearchText(w, workflowHints[w.workflow_id] || null).includes(normalizedQuery))
    : workflows;

  return (
    <div className="task-hub-tab">
      {/* Task Hub Header */}
      <div className="task-hub-tab-header">
        <div className="task-hub-tab-title">
          <h4>Active Tasks</h4>
          <span className="task-hub-tab-count">
            {normalizedQuery
              ? `${filteredWorkflows.length} matching workflow${filteredWorkflows.length === 1 ? "" : "s"}`
              : `${workflows.length} workflows`}
          </span>
        </div>
        <button
          className="task-hub-new-btn"
          onClick={handleNewWorkflow}
          disabled={isExecuting}
        >
          <span className="btn-icon">+</span>
          New Task
        </button>
      </div>

      {/* TASK_HUB_SEARCH: Search input bar - styled to match History */}
      <div className="task-hub-search-bar">
        <input
          type="text"
          className="task-hub-search-input"
          placeholder="Search tasks..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          aria-label="Search tasks"
        />
        {searchQuery && (
          <button
            className="task-hub-search-clear"
            onClick={() => setSearchQuery("")}
            aria-label="Clear search"
          >
            ✕
          </button>
        )}
      </div>

      {/* Task Hub Content */}
      <div className="task-hub-tab-content">
        {isSwitching && (
          <div className="task-hub-switching-overlay">
            <div className="task-hub-switching-content">
              <div className="spinner-medium" />
              <span className="switching-text">Loading workflow…</span>
            </div>
          </div>
        )}

        {isLoading && workflows.length === 0 ? (
          <div className="task-hub-loading">
            <div className="spinner-medium" />
            <span>Loading workflows…</span>
          </div>
        ) : workflows.length === 0 ? (
          <div className="task-hub-empty">
            <div className="task-hub-empty-icon">📋</div>
            <h4>No active tasks</h4>
            <p>Create your first task to get started.</p>
            <button
              className="task-hub-empty-create-btn"
              onClick={handleNewWorkflow}
              disabled={isExecuting}
            >
              <span className="btn-icon">+</span>
              Create First Task
            </button>
          </div>
        ) : normalizedQuery && filteredWorkflows.length === 0 ? (
          // TASK_HUB_SEARCH: Empty search results state
          <div className="task-hub-empty">
            <div className="task-hub-empty-icon">🔍</div>
            <h4>No active tasks match this search</h4>
            <p>Try a different search term or clear the filter.</p>
            <button
              className="task-hub-empty-create-btn"
              onClick={() => setSearchQuery("")}
            >
              Clear Search
            </button>
          </div>
        ) : (
          <div ref={scrollRef} className="task-hub-list">
            {filteredWorkflows.map((workflow) => {
              const statusConfig = formatStatus(workflow.status);
              const progress = getStatusProgress(workflow);
              const isSelected = selectedWorkflowId === workflow.workflow_id;
              const isActive = workflow.workflow_id === currentWorkflowId;
              // Get human-readable task hint (inline to avoid scope issues)
              const hint = workflowHints[workflow.workflow_id];
              let humanHint;
              if (hint) {
                humanHint = hint.length > 60 ? hint.slice(0, 60) + "…" : hint;
              } else {
                // Priority 2: Existing safe workflow fields
                const safeFields = [
                  workflow.title,
                  workflow.name,
                  workflow.summary,
                  workflow.goal,
                  workflow.prompt,
                  workflow.original_prompt
                ];

                let found = false;
                for (const field of safeFields) {
                  if (field && typeof field === 'string' && field.trim()) {
                    humanHint = field.length > 60 ? field.slice(0, 60) + "…" : field;
                    found = true;
                    break;
                  }
                }

                if (!found) {
                  // Priority 3: Final fallback to workflow ID
                  humanHint = `Task ${workflow.workflow_id?.slice(-12)}`;
                }
              }

              return (
                <div
                  key={workflow.workflow_id}
                  className={`task-hub-item ${isActive ? "active" : ""} ${isSelected ? "selected" : ""}`}
                >
                  <div className="task-hub-item-header">
                    <div className="task-hub-item-title">
                      <span className="task-hub-item-id">{workflow.workflow_id.slice(-8)}</span>
                      {isActive && <span className="task-hub-current-indicator">Current</span>}
                    </div>
                    <div className="task-hub-item-status">
                      <span
                        className="status-badge"
                        style={{ backgroundColor: statusConfig.color }}
                      >
                        {statusConfig.label}
                      </span>
                      {isQueuedReplanRequired(workflow) && (
                        <span className="recoverable-badge">Planning Interrupted</span>
                      )}
                      {isQueuedLivePlanning(workflow) && (
                        <span className="recoverable-badge">Planning…</span>
                      )}
                      {workflow.recoverable && !isQueuedReplanRequired(workflow) && !isQueuedLivePlanning(workflow) && (
                        <span className="recoverable-badge">Resumable</span>
                      )}
                      {workflow.inspection_only && (
                        <span className="inspection-badge">Inspection</span>
                      )}
                      {hasBlockedApprovalStep(workflow) && (
                        <span className="approval-required-badge">Approval required</span>
                      )}
                    </div>
                  </div>

                  <div className="task-hub-item-identity">
                    <span className="task-name">{humanHint}</span>
                  </div>

                  <div className="task-hub-item-meta">
                    <span className="task-id">{workflow.workflow_id.slice(-8)}</span>
                    <span className="task-time">{workflow.last_updated ? formatDate(workflow.last_updated) : ""}</span>
                  </div>

                  {workflow.steps && workflow.steps.length > 0 && (
                    <div className="task-hub-item-progress">
                      <div className="progress-bar">
                        <div
                          className="progress-fill"
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                      <span className="progress-text">{progress}%</span>
                    </div>
                  )}

                  <div className="task-hub-item-actions">
                    {isActive ? (
                      <button
                        className="task-hub-detach-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDetachWorkflow();
                        }}
                        disabled={isSwitching}
                      >
                        Detach
                      </button>
                    ) : isQueuedReplanRequired(workflow) ? (
                      <button
                        className="task-hub-attach-btn"
                        onClick={async (e) => {
                          e.stopPropagation();
                          setReplanningId(workflow.workflow_id);
                          try {
                            await onReplan?.(workflow.workflow_id);
                          } finally {
                            setReplanningId(null);
                          }
                        }}
                        disabled={isSwitching || replanningId === workflow.workflow_id}
                      >
                        {replanningId === workflow.workflow_id ? "Replanning…" : (workflow.action_label || "Resume Planning / Replan")}
                      </button>
                    ) : isQueuedLivePlanning(workflow) ? (
                      // PLANNING_VISIBILITY_FIX: LIVE_PLANNING shows disabled Planning... button (no action)
                      <button
                        className="task-hub-attach-btn"
                        disabled={true}
                        title="Planning in progress..."
                      >
                        {workflow.action_label || "Planning..."}
                      </button>
                    ) : (
                      <button
                        className="task-hub-attach-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSelect(workflow);
                        }}
                        disabled={isSwitching}
                      >
                        {isSwitching ? "Attaching…" : (workflow.inspection_only ? "Inspect Workflow" : "Attach Workflow")}
                      </button>
                    )}

                    {/* ISSUE-060: Minimal archive/dismiss controls */}
                    <button
                      className="task-hub-archive-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleArchive(workflow);
                      }}
                      disabled={isSwitching}
                      title="Archive workflow"
                    >
                      📁
                    </button>
                    <button
                      className="task-hub-dismiss-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDismiss(workflow);
                      }}
                      disabled={isSwitching}
                      title="Dismiss workflow"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Task Hub Footer */}
      <div className="task-hub-tab-footer">
        <span className="task-hub-hint">
          {recoverableCount > 0
            ? `${recoverableCount} task${recoverableCount > 1 ? "s" : ""} can be resumed`
            : "All tasks completed or failed"}
        </span>
      </div>
    </div>
  );
}
