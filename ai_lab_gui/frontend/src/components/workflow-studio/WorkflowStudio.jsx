/**
 * WORKFLOW STUDIO — PHASE 3 STUDIO SHELL
 *
 * Per WORKFLOW_STUDIO_PHASE3_SHELL:
 * Container shell for unified workflow projection workspace.
 *
 * Authority: GUI_ARCHITECTURE.txt, CANONICAL_PROJECTION_MODEL_V1
 *
 * RESPONSIBILITIES:
 * - Container shell layout
 * - Mode state management (UI-only)
 * - Projection presentation orchestration
 * - Toolbar/Footer coordination
 *
 * NOT RESPONSIBLE FOR:
 * - Authority ownership (projection comes from parent)
 * - Polling ownership (polling happens in WorkflowProjectionView)
 * - Orchestration (mutation intents dispatched to parent)
 *
 * Architecture: WorkflowProjectionView → WorkflowStudio → Mode → Existing Components
 */

import { useState } from "react";
import StudioToolbar from "./StudioToolbar.jsx";
import StudioFooter from "./StudioFooter.jsx";
import OverviewMode from "./modes/OverviewMode.jsx";
import PlanMode from "./modes/PlanMode.jsx";
import DependenciesMode from "./modes/DependenciesMode.jsx";
import EditMode from "./modes/EditMode.jsx";

const MODES = {
  OVERVIEW: "overview",
  PLAN: "plan",
  DEPENDENCIES: "dependencies",
  EDIT: "edit",
};

/**
 * WorkflowStudio — unified projection workspace container
 *
 * @param {Object} props
 * @param {Object} props.projection — canonical WorkflowProjection
 * @param {string} props.workflowId — current workflow_id
 * @param {boolean} props.isExecuting — execution state (for edit lockout)
 * @param {Function} props.onMutationIntent — mutation intent dispatcher
 * @param {Function} props.onProjectionRefresh — manual refresh request
 * @param {string} [props.initialMode] — starting mode
 */
export default function WorkflowStudio({
  projection,
  workflowId,
  isExecuting,
  onMutationIntent,
  onProjectionRefresh,
  initialMode = MODES.PLAN,
}) {
  // UI-only mode state — NO authority, NO projection impact
  const [activeMode, setActiveMode] = useState(initialMode);

  // Mode switching is pure UI — no workflow reload, no projection invalidation
  const handleModeChange = (mode) => {
    if (mode === activeMode) return;
    setActiveMode(mode);
  };

  if (!projection) {
    return (
      <div className="workflow-studio workflow-studio--empty">
        <div className="studio-placeholder muted">
          No projection data available.
        </div>
      </div>
    );
  }

  const {
    workflow_id,
    workflow_name,
    lifecycle_status,
    projection_version,
    projection_state,
    projection_timestamp,
    steps = [],
    outputs = [],
    step_count,
  } = projection;

  // Toolbar configuration
  const toolbarProps = {
    workflowId: workflow_id || workflowId,
    workflowName: workflow_name,
    lifecycleStatus: lifecycle_status,
    projectionVersion: projection_version,
    projectionState: projection_state,
    activeMode,
    availableModes: Object.values(MODES),
    onModeChange: handleModeChange,
    onRefresh: onProjectionRefresh,
  };

  // Footer configuration
  const footerProps = {
    projectionVersion: projection_version,
    projectionState: projection_state,
    projectionTimestamp: projection_timestamp,
    stepCount: step_count ?? steps.length,
    completedCount: steps.filter((s) => s.status === "COMPLETED").length,
    failedCount: steps.filter((s) => s.status === "FAILED").length,
    workflowId: workflow_id || workflowId,
  };

  // Mode content props
  const modeProps = {
    projection,
    steps,
    outputs,
    workflowId: workflow_id || workflowId,
    isExecuting,
    onMutationIntent,
    lifecycleStatus: lifecycle_status,
  };

  return (
    <div className="workflow-studio">
      {/* Studio Toolbar — identity, lifecycle, mode navigation */}
      <StudioToolbar {...toolbarProps} />

      {/* Mode Content Area */}
      <div className="workflow-studio__content">
        {activeMode === MODES.OVERVIEW && <OverviewMode {...modeProps} />}
        {activeMode === MODES.PLAN && <PlanMode {...modeProps} />}
        {activeMode === MODES.DEPENDENCIES && <DependenciesMode {...modeProps} />}
        {activeMode === MODES.EDIT && (
          <EditMode {...modeProps} disabled={isExecuting} />
        )}
      </div>

      {/* Studio Footer — projection metadata */}
      <StudioFooter {...footerProps} />
    </div>
  );
}

// Export mode constants for external use
export { MODES };
