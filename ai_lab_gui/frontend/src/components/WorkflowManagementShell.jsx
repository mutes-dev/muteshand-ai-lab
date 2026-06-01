import { useState, useRef } from "react";
import TaskHubTab from "./TaskHubTab.jsx";
import HistoryTab from "./HistoryTab.jsx";

/**
 * Workflow Management Shell - Phase 1 Implementation
 * 
 * Provides a clean separation between Task Hub and History while preserving
 * all existing Task Hub behavior and authority contracts.
 * 
 * Per WORKFLOW_RETENTION_AND_ARCHIVAL_CONTRACT_V1:
 * - Task Hub = actionable/recoverable work management
 * - History = read-only historical inspection (Phase 2)
 * - Archive = future filter inside History
 */

export default function WorkflowManagementShell({
  currentWorkflowId,
  currentStatus,
  onWorkflowSelect,
  onNewWorkflow,
  onDetachWorkflow,
  isExecuting,
  onReplan,
}) {
  const [activeTab, setActiveTab] = useState("taskhub");
  const [isCollapsed, setIsCollapsed] = useState(false);
  const shellRef = useRef(null);

  return (
    <div
      ref={shellRef}
      className={`workflow-management-shell ${isCollapsed ? "collapsed" : "expanded"}`}
    >
      {/* Shell Header */}
      <div className="workflow-shell-header">
        <div className="workflow-shell-title">
          <h3>Workflows</h3>
        </div>
        <div className="workflow-shell-controls">
          <button
            className="workflow-shell-collapse-btn"
            onClick={() => setIsCollapsed(!isCollapsed)}
            aria-label={isCollapsed ? "Expand workflow panel" : "Collapse workflow panel"}
          >
            {isCollapsed ? "▶" : "◀"}
          </button>
        </div>
      </div>

      {/* Shell Content */}
      {!isCollapsed && (
        <div className="workflow-shell-content">
          {/* Tab Navigation */}
          <div className="workflow-shell-tabs">
            <button
              className={`workflow-tab ${activeTab === "taskhub" ? "active" : ""}`}
              onClick={() => setActiveTab("taskhub")}
            >
              Task Hub
            </button>
            <button
              className={`workflow-tab ${activeTab === "history" ? "active" : ""}`}
              onClick={() => setActiveTab("history")}
            >
              History
            </button>
          </div>

          {/* Tab Content */}
          <div className="workflow-shell-tab-content">
            {activeTab === "taskhub" && (
              <TaskHubTab
                currentWorkflowId={currentWorkflowId}
                currentStatus={currentStatus}
                onWorkflowSelect={onWorkflowSelect}
                onNewWorkflow={onNewWorkflow}
                onDetachWorkflow={onDetachWorkflow}
                isExecuting={isExecuting}
                onReplan={onReplan}
              />
            )}

            {activeTab === "history" && (
              <HistoryTab />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
