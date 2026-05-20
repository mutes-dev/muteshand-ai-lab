/**
 * PLAN MODE — PHASE 4 MODE CONSOLIDATION
 *
 * Per WORKFLOW_STUDIO_PHASE4_MODE_CONSOLIDATION:
 * Canonical plan inspection using shared StepCard rendering.
 *
 * Replaces Phase 3 PlanView wrapper with direct StepCardList.
 */

import { useState } from "react";
import { StepCardList } from "../../shared/StepCard.jsx";
import { useStepIndexMap } from "../../../hooks/useStepIndexMap.js";

/**
 * PlanMode — PHASE 4 CONSOLIDATED — canonical plan step inspection
 *
 * Uses StepCardList for unified rendering with:
 * - Output previews for completed steps
 * - Processing indicators for active steps
 * - Expandable detail sections
 * - Dependency resolution
 *
 * @param {Object} props
 * @param {Object} props.projection — full workflow projection
 * @param {Array} props.steps — step projections
 * @param {Array} props.outputs — step execution outputs
 * @param {string} props.workflowId — workflow identifier
 * @param {boolean} props.isExecuting — execution state for processing indicators
 */
export default function PlanMode({ projection, steps, outputs, workflowId, isExecuting }) {
  const [expandedStepId, setExpandedStepId] = useState(null);

  // Shared hook: step_id → index map for dependency labeling
  const stepIndexMap = useStepIndexMap(steps);

  const { lifecycle_status } = projection || {};
  const isPaused = lifecycle_status === "PAUSED";

  if (!steps || steps.length === 0) {
    return (
      <div className="mode-content mode-content--empty">
        <div className="mode-placeholder muted">No plan steps available.</div>
      </div>
    );
  }

  const completedCount = steps.filter((s) => s.status === "COMPLETED").length;
  const activeCount = steps.filter((s) => s.status === "ACTIVE").length;

  return (
    <div className="mode-content mode-content--plan">
      {/* Plan progress summary */}
      <div className="mode-summary">
        <span className="summary-stat">
          {completedCount}/{steps.length} complete
        </span>
        {activeCount > 0 && (
          <span className="summary-stat summary-stat--active">
            {activeCount} active
          </span>
        )}
      </div>

      {/* Canonical StepCardList rendering */}
      <StepCardList
        steps={steps}
        mode="full"
        expandedStepId={expandedStepId}
        onExpand={setExpandedStepId}
        stepIndexMap={stepIndexMap}
        outputs={outputs}
        isProcessing={isExecuting}
        isPaused={isPaused}
      />
    </div>
  );
}
