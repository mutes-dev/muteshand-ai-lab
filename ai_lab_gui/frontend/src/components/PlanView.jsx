/**
 * PLAN VIEW — PHASE 4B.0 — SUB-PHASE 3B
 *
 * Per CANONICAL_PROJECTION_MODEL_V1 §8 (Plan Projection Model):
 * - Renders canonical PlanProjection (step list with order, dependencies, lifecycle visibility)
 * - Read-only: no edit controls, no reorder controls, no mutation handlers
 *
 * Per PLAN_CONTROL_CONTRACT_V1 (PLAN VISIBILITY):
 * - Displays plan steps with order and dependency relationships
 * - Renders lifecycle visibility per step
 * - Renders projection metadata
 *
 * Per GUI_FUNCTIONALITY_CONTRACT_V1:
 * - Plan interaction renders canonical plan projections
 * - Edits are requests, NOT mutations; but this phase implements READ-ONLY only
 *
 * PROHIBITED:
 * - No editable plan controls
 * - No reorder controls
 * - No mutation handlers
 * - No lifecycle synthesis
 * - No local dependency reconstruction
 * - No hidden dependency derivation
 */

import { useState } from "react";
import { StepCardList } from "./shared/StepCard.jsx";
import { useStepIndexMap } from "../hooks/useStepIndexMap.js";
import DependencyView from "./DependencyView.jsx";

/**
 * PlanView
 *
 * Renders canonical step projections as a read-only plan list.
 * Dependencies are rendered from canonical step_projection.depends_on field.
 *
 * Props:
 *   steps           — canonical StepProjection[] from WorkflowProjection.steps
 *   workflowId      — owning workflow_id (for identity display)
 *   projectionVersion — current projection_version (for display)
 *   projectionState — current projection_state
 */
export default function PlanView({ steps = [], workflowId, projectionVersion, projectionState }) {
  const [showDeps, setShowDeps] = useState(false);
  const [expandedStepId, setExpandedStepId] = useState(null);

  // Shared hook: step_id → index map for dependency labeling
  const stepIndexMap = useStepIndexMap(steps);

  if (!steps.length) {
    return (
      <div className="plan-view-empty muted">No plan steps in projection.</div>
    );
  }

  const completedCount = steps.filter(s => s.status === "COMPLETED").length;
  const activeCount = steps.filter(s => s.status === "ACTIVE").length;

  return (
    <div className="plan-view">
      {/* Plan header */}
      <div className="plan-view-header">
        <div className="plan-view-title-row">
          <h3 className="plan-view-title">Plan</h3>
          <span className="plan-badge plan-badge--readonly">read-only</span>
          {projectionVersion && (
            <span className="plan-badge plan-badge--version">v{projectionVersion}</span>
          )}
        </div>
        <div className="plan-progress-row">
          <span className="plan-progress-text muted">
            {completedCount}/{steps.length} complete
            {activeCount > 0 && `, ${activeCount} active`}
          </span>
          <button
            className="btn-ghost"
            onClick={() => setShowDeps(s => !s)}
            aria-label={showDeps ? "Hide dependency map" : "Show dependency map"}
          >
            {showDeps ? "▲ Hide dependencies" : "▼ Show dependencies"}
          </button>
        </div>
      </div>

      {/* Dependency visualization (SUB-PHASE 3C) */}
      {showDeps && (
        <DependencyView
          steps={steps}
          workflowId={workflowId}
          projectionVersion={projectionVersion}
        />
      )}

      {/* Step list — using shared StepCardList component */}
      <StepCardList
        steps={steps}
        mode="full"
        expandedStepId={expandedStepId}
        onExpand={setExpandedStepId}
        stepIndexMap={stepIndexMap}
      />

      {/* Projection state footer */}
      {projectionState === "TERMINAL" && (
        <div className="plan-terminal-notice muted">
          Plan finalized — workflow {steps.some(s => s.status === "FAILED") ? "failed" : "completed"}.
        </div>
      )}
    </div>
  );
}
