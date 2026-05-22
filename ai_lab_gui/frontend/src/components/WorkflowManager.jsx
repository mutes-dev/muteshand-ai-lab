import { useState, useEffect, useRef } from "react";
import { api } from "../api.js";

/**
 * Task Hub / Workflow Manager UI Component
 * 
 * Per TASK HUB UI EVOLUTION (POST-STABILIZATION):
 * - Human-readable workflow visibility and selection
 * - Explicit workflow selection with clear feedback
 * - No backend orchestration changes
 * - Lightweight single-screen UX
 * 
 * This component is UI-only and does NOT modify orchestration semantics.
 * Preserves all existing selection flow, state management, and API patterns.
 */

export default function WorkflowManager({
  currentWorkflowId,
  currentStatus,
  onWorkflowSelect,
  onNewWorkflow,
  onDetachWorkflow,
  isExecuting,
}) {
  const [workflows, setWorkflows] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isSwitching, setIsSwitching] = useState(false);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState(null);
  const [workflowHints, setWorkflowHints] = useState({});
  const switchTimeoutRef = useRef(null);

  // Fetch workflows when hub opens
  useEffect(() => {
    if (isOpen) {
      loadWorkflows();
    }
  }, [isOpen]);

  // Cleanup switch timeout on unmount
  useEffect(() => {
    return () => {
      if (switchTimeoutRef.current) {
        clearTimeout(switchTimeoutRef.current);
      }
    };
  }, []);

  // Close modal on Escape key
  useEffect(() => {
    function onKeyDown(e) {
      if (e.key === "Escape") setIsOpen(false);
    }
    if (isOpen) {
      document.addEventListener("keydown", onKeyDown);
      return () => document.removeEventListener("keydown", onKeyDown);
    }
  }, [isOpen]);

  async function loadWorkflows() {
    setIsLoading(true);
    try {
      const res = await api.getAuthoritativeWorkflows();
      const allWorkflows = res.workflows || [];
      // Sort: recoverable first, then by last_updated desc
      const sorted = allWorkflows.sort((a, b) => {
        if (a.recoverable && !b.recoverable) return -1;
        if (!a.recoverable && b.recoverable) return 1;
        return (b.last_updated || 0) - (a.last_updated || 0);
      });
      setWorkflows(sorted);

      // Fetch hints for workflows to show meaningful context
      await loadWorkflowHints(sorted);

      console.log("[GUI:TASK_HUB_LOAD]", {
        count: sorted.length,
        recoverable: sorted.filter(w => w.recoverable).length,
        timestamp: Date.now(),
      });
    } catch (err) {
      console.log("[GUI:TASK_HUB_ERROR]", {
        error: err.message,
        timestamp: Date.now(),
      });
    } finally {
      setIsLoading(false);
    }
  }

  // Load workflow hints from projections to show human-readable context
  async function loadWorkflowHints(workflowList) {
    const hints = {};
    for (const wf of workflowList.slice(0, 10)) { // Limit to first 10 to avoid overload
      try {
        const projection = await api.getProjection(wf.workflow_id);
        if (projection?.original_prompt) {
          hints[wf.workflow_id] = projection.original_prompt;
        } else if (projection?.input) {
          hints[wf.workflow_id] = projection.input;
        } else if (projection?.steps?.[0]?.purpose) {
          hints[wf.workflow_id] = projection.steps[0].purpose;
        }
      } catch (err) {
        // Projection not available - hint remains undefined
      }
    }
    setWorkflowHints(hints);
  }

  function handleSelect(workflow) {
    console.log("[GUI:TASK_HUB_SELECT]", {
      workflowId: workflow.workflow_id,
      status: workflow.status,
      recoverable: workflow.recoverable,
      action: "explicit_selection_with_feedback",
      timestamp: Date.now(),
    });

    // Show loading feedback immediately
    setSelectedWorkflowId(workflow.workflow_id);
    setIsSwitching(true);

    // Clear any existing timeout
    if (switchTimeoutRef.current) {
      clearTimeout(switchTimeoutRef.current);
    }

    // Call the selection handler
    onWorkflowSelect(workflow);

    // Keep loading state visible briefly for UX feedback, then close
    switchTimeoutRef.current = setTimeout(() => {
      setIsSwitching(false);
      setSelectedWorkflowId(null);
      setIsOpen(false);
    }, 800);
  }

  function handleNewWorkflow() {
    console.log("[GUI:TASK_HUB_NEW]", {
      action: "new_workflow_requested",
      timestamp: Date.now(),
    });
    onNewWorkflow();
    setIsOpen(false);
  }

  function formatStatus(status) {
    const statusConfig = {
      ACTIVE: { class: "status-active", label: "Running", icon: "▶" },
      COMPLETED: { class: "status-completed", label: "Completed", icon: "✓" },
      FAILED: { class: "status-failed", label: "Failed", icon: "✕" },
      PAUSED: { class: "status-paused", label: "Paused", icon: "⏸" },
      BLOCKED: { class: "status-blocked", label: "Blocked", icon: "⊘" },
      PENDING: { class: "status-pending", label: "Pending", icon: "◌" },
      INITIALIZING: { class: "status-pending", label: "Initializing", icon: "◌" },
      PLANNING: { class: "status-pending", label: "Planning", icon: "◌" },
    };
    return statusConfig[status] || { class: "status-default", label: status || "Pending", icon: "◌" };
  }

  function formatDate(timestamp) {
    if (!timestamp) return "";
    const date = new Date(timestamp * 1000);
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

  // Get human-readable task identity from hints or fallback to ID
  function getWorkflowIdentity(workflow) {
    const hint = workflowHints[workflow.workflow_id];
    if (hint) {
      // Truncate long prompts but keep them meaningful
      return hint.length > 60 ? hint.slice(0, 60) + "…" : hint;
    }

    // Fallback to workflow ID with label
    return `Task ${workflow.workflow_id?.slice(-12)}`;
  }

  // Get status progress indicator
  function getStatusProgress(workflow) {
    const statusProgress = {
      ACTIVE: { bar: 50, color: "#22c55e" },
      PENDING: { bar: 10, color: "#64748b" },
      COMPLETED: { bar: 100, color: "#3b82f6" },
      FAILED: { bar: 100, color: "#ef4444" },
      PAUSED: { bar: 50, color: "#f97316" },
      BLOCKED: { bar: 30, color: "#ef4444" },
    };
    return statusProgress[workflow.status] || { bar: 0, color: "#64748b" };
  }

  const recoverableCount = workflows.filter(w => w.recoverable).length;
  const hasMultipleRecoverable = recoverableCount > 1;
  const currentStatusConfig = formatStatus(currentStatus);

  return (
    <div className="workflow-manager">
      {/* === TOP BAR: Current Workflow Surface === */}
      <div className="workflow-surface">
        {currentWorkflowId ? (
          <>
            <span className="workflow-surface-name">
              {getWorkflowIdentity({ workflow_id: currentWorkflowId })}
            </span>
            <span className={`workflow-surface-status ${currentStatusConfig.class}`}>
              <span className="status-icon">{currentStatusConfig.icon}</span>
              {currentStatusConfig.label}
            </span>
            {/* Explicit detach — per GUI_FUNCTIONALITY_CONTRACT_V1 §FOCUSED WORKFLOW PERSISTENCE */}
            <button
              className="workflow-detach-btn"
              onClick={onDetachWorkflow}
              title="Detach workflow"
              aria-label="Detach workflow"
            >
              ×
            </button>
          </>
        ) : (
          <span className="workflow-surface-placeholder">No active workflow</span>
        )}
      </div>

      {/* === TASK HUB ACCESS BUTTON === */}
      <button
        className="task-hub-access-btn"
        onClick={() => setIsOpen(true)}
        disabled={isExecuting}
        title={isExecuting ? "Cannot open while task is running" : "Open Task Hub"}
      >
        <span className="task-hub-access-label">
          {hasMultipleRecoverable ? `Task Hub · ${recoverableCount}` : "Task Hub"}
        </span>
      </button>

      {/* === TASK HUB MODAL === */}
      {isOpen && (
        <div
          className="task-hub-modal-backdrop"
          onClick={(e) => {
            if (e.target === e.currentTarget) setIsOpen(false);
          }}
        >
          <div className="task-hub-modal" role="dialog" aria-modal="true" aria-label="Task Hub">
            {/* Modal Header */}
            <div className="task-hub-modal-header">
              <div className="task-hub-modal-title">
                <h3>Task Hub</h3>
                <span className="task-hub-modal-subtitle">
                  {workflows.length} workflow{workflows.length !== 1 ? "s" : ""}
                </span>
              </div>
              <div className="task-hub-modal-actions">
                <button
                  className="task-hub-new-btn"
                  onClick={handleNewWorkflow}
                  disabled={isExecuting}
                >
                  <span className="btn-icon">+</span>
                  New Task
                </button>
                <button
                  className="task-hub-close-btn"
                  onClick={() => setIsOpen(false)}
                  aria-label="Close Task Hub"
                >
                  &#10005;
                </button>
              </div>
            </div>

            {/* Modal Body */}
            <div className="task-hub-modal-body">
              {isSwitching && (
                <div className="task-hub-switching-overlay">
                  <div className="task-hub-switching-content">
                    <div className="spinner-medium" />
                    <span className="switching-text">Loading workflow…</span>
                  </div>
                </div>
              )}

              {isLoading ? (
                <div className="task-hub-loading">
                  <div className="spinner-medium" />
                  <span>Loading workflows…</span>
                </div>
              ) : workflows.length === 0 ? (
                <div className="task-hub-empty">
                  <div className="empty-icon">◬</div>
                  <h4>Welcome to AI Lab</h4>
                  <p>No tasks yet. Create your first workflow to get started.</p>
                  <button className="task-hub-empty-btn" onClick={handleNewWorkflow}>
                    <span className="btn-icon">+</span>
                    Create First Task
                  </button>
                </div>
              ) : (
                <div className="task-hub-list task-hub-modal-list">
                  {workflows.map((workflow) => {
                    const statusConfig = formatStatus(workflow.status);
                    const progress = getStatusProgress(workflow);
                    const isSelected = selectedWorkflowId === workflow.workflow_id;
                    const isActive = workflow.workflow_id === currentWorkflowId;

                    return (
                      <div
                        key={workflow.workflow_id}
                        className={`task-hub-item ${isActive ? "active" : ""} ${isSelected ? "selected" : ""}`}
                        onClick={() => !isSwitching && setSelectedWorkflowId(workflow.workflow_id)}
                      >
                        <div
                          className="task-progress-bar"
                          style={{
                            width: `${progress.bar}%`,
                            backgroundColor: progress.color,
                          }}
                        />
                        <div className="task-hub-item-content">
                          <div className="task-hub-item-header">
                            <span className={`task-status-badge ${statusConfig.class}`}>
                              <span className="status-icon">{statusConfig.icon}</span>
                              {statusConfig.label}
                            </span>
                            {workflow.recoverable && (
                              <span className="task-resumable-badge">↻ Resumable</span>
                            )}
                            {isActive && (
                              <span className="task-active-indicator">Current</span>
                            )}
                          </div>
                          <div className="task-hub-item-identity">
                            <span className="task-name">{getWorkflowIdentity(workflow)}</span>
                          </div>
                          <div className="task-hub-item-meta">
                            <span className="task-id">{workflow.workflow_id.slice(-8)}</span>
                            <span className="task-time">{formatDate(workflow.last_updated)}</span>
                          </div>
                          {/* Explicit attachment action — per GUI_FUNCTIONALITY_CONTRACT_V1 §FOCUSED WORKFLOW PERSISTENCE */}
                          {isSelected && (
                            <div className="task-hub-item-actions">
                              {isActive ? (
                                <span className="task-hub-current-badge">Currently attached</span>
                              ) : (
                                <button
                                  className="task-hub-attach-btn"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleSelect(workflow);
                                  }}
                                  disabled={isSwitching}
                                >
                                  {isSwitching ? "Attaching…" : "Attach Workflow"}
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                        {isSelected && isSwitching && (
                          <div className="task-switching-indicator">
                            <div className="spinner-tiny" />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="task-hub-modal-footer">
              <span className="task-hub-hint">
                {recoverableCount > 0
                  ? `${recoverableCount} task${recoverableCount > 1 ? "s" : ""} can be resumed`
                  : "All tasks completed or failed"}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
