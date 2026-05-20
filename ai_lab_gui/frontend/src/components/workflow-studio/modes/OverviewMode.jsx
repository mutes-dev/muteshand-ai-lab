/**
 * OVERVIEW MODE — PHASE 3 STUDIO SHELL
 *
 * Per WORKFLOW_STUDIO_PHASE3_SHELL:
 * High-level workflow progress and summary view.
 *
 * This phase: Shell only — uses existing components temporarily.
 * Future: Full Overview implementation with StepCard compact mode.
 */

import { CompactStepCard } from "../../shared/StepCard.jsx";
import { useStepIndexMap } from "../../../hooks/useStepIndexMap.js";

/**
 * OverviewMode — high-level workflow summary
 *
 * @param {Object} props
 * @param {Object} props.projection — full workflow projection
 * @param {Array} props.steps — step projections
 * @param {Array} props.outputs — step outputs
 * @param {string} props.workflowId — workflow identifier
 */
export default function OverviewMode({ projection, steps, outputs, workflowId }) {
  const stepIndexMap = useStepIndexMap(steps);

  if (!steps || steps.length === 0) {
    return (
      <div className="mode-content mode-content--empty">
        <div className="mode-placeholder muted">
          No steps in workflow.
        </div>
      </div>
    );
  }

  const completedCount = steps.filter((s) => s.status === "COMPLETED").length;
  const failedCount = steps.filter((s) => s.status === "FAILED").length;
  const activeCount = steps.filter((s) => s.status === "ACTIVE").length;
  const progressPercent = Math.round((completedCount / steps.length) * 100);

  // Find latest completed step for highlighting
  const latestCompletedIndex = steps.reduce((latest, step, index) => {
    if (step.status === "COMPLETED") return index;
    return latest;
  }, -1);

  return (
    <div className="mode-content mode-content--overview">
      {/* Progress Summary */}
      <div className="overview-summary">
        <div className="progress-bar-container">
          <div
            className="progress-bar-fill"
            style={{ width: `${progressPercent}%` }}
          />
          <span className="progress-text">{progressPercent}% complete</span>
        </div>

        <div className="overview-stats">
          <span className="stat completed">{completedCount} completed</span>
          {activeCount > 0 && <span className="stat active">{activeCount} active</span>}
          {failedCount > 0 && <span className="stat failed">{failedCount} failed</span>}
          <span className="stat pending">{steps.length - completedCount - failedCount} pending</span>
        </div>
      </div>

      {/* Compact Step List */}
      <div className="overview-steps">
        <h4 className="mode-section-title">Steps</h4>
        <div className="compact-step-list">
          {steps.map((step, index) => (
            <CompactStepCard
              key={step.step_id || index}
              step={step}
              stepNumber={index + 1}
              stepIndexMap={stepIndexMap}
              isLatestCompleted={index === latestCompletedIndex}
            />
          ))}
        </div>
      </div>

      {/* Recent Outputs (if any) */}
      {outputs && outputs.length > 0 && (
        <div className="overview-outputs">
          <h4 className="mode-section-title">Recent Outputs</h4>
          <div className="output-list">
            {outputs.slice(-3).map((output, i) => (
              <div key={i} className="output-item">
                <span className="output-step">{output.step_id?.slice(0, 8)}</span>
                <span className="output-result muted">
                  {output.execution_result?.result?.slice(0, 40) || "done"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
