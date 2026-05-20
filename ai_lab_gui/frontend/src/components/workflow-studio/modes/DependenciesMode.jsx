/**
 * DEPENDENCIES MODE — PHASE 4 MODE CONSOLIDATION
 *
 * Per WORKFLOW_STUDIO_PHASE4_MODE_CONSOLIDATION:
 * Canonical dependency visualization using shared rendering primitives.
 *
 * Replaces Phase 3 DependencyView wrapper with direct shared component usage.
 */

import { useStepMap } from "../../../hooks/useStepIndexMap.js";
import { DependencyChain, IndependentStepList } from "../../shared/DependencyNode.jsx";
import { CompactStepCard } from "../../shared/StepCard.jsx";

/**
 * DependenciesMode — PHASE 4 CONSOLIDATED — canonical dependency visualization
 *
 * Uses shared dependency rendering primitives:
 * - DependencyChain for steps with dependencies
 * - IndependentStepList for steps without dependencies
 * - CompactStepCard for step context cards
 *
 * Per CANONICAL_PROJECTION_MODEL_V1 §8:
 * Dependencies rendered ONLY from step_projection.depends_on — no local synthesis.
 *
 * @param {Object} props
 * @param {Object} props.projection — full workflow projection
 * @param {Array} props.steps — step projections
 * @param {string} props.workflowId — workflow identifier
 */
export default function DependenciesMode({ projection, steps, workflowId }) {
  const stepMap = useStepMap(steps);

  if (!steps || steps.length === 0) {
    return (
      <div className="mode-content mode-content--empty">
        <div className="mode-placeholder muted">No dependency data available.</div>
      </div>
    );
  }

  // Separate steps by dependency status
  const stepsWithDeps = steps.filter((s) => s.depends_on && s.depends_on.length > 0);
  const independentSteps = steps.filter((s) => !s.depends_on || s.depends_on.length === 0);

  return (
    <div className="mode-content mode-content--dependencies">
      {/* Header */}
      <div className="dep-mode-header">
        <span className="dep-mode-title muted">Dependency Map</span>
        <span className="dep-mode-note muted">
          — canonical projection source, read-only
        </span>
      </div>

      {/* Independent Steps */}
      {independentSteps.length > 0 && (
        <IndependentStepList steps={independentSteps} stepMap={stepMap} />
      )}

      {/* Steps with Dependencies */}
      {stepsWithDeps.length > 0 && (
        <div className="dep-section">
          <div className="dep-section-label muted">Dependency Chains</div>
          {stepsWithDeps.map((step) => {
            const stepInfo = stepMap[step.step_id];
            const stepIndex = stepInfo?.index ?? "?";

            // Resolve dependency step objects
            const sourceSteps = step.depends_on
              .map((depId) => stepMap[depId]?.step)
              .filter(Boolean);

            return (
              <DependencyChain
                key={step.step_id}
                step={step}
                stepIndex={stepIndex}
                sourceSteps={sourceSteps}
                stepMap={stepMap}
              />
            );
          })}
        </div>
      )}

      {/* Context Cards */}
      <div className="dep-context">
        <div className="dep-section-label muted">All Steps</div>
        <div className="dep-context-grid">
          {steps.map((step, index) => (
            <CompactStepCard
              key={step.step_id}
              step={step}
              stepNumber={index + 1}
            />
          ))}
        </div>
      </div>

      {/* No dependencies message */}
      {stepsWithDeps.length === 0 && (
        <div className="dep-no-deps muted">
          No explicit dependencies in canonical projection (all steps are independent).
        </div>
      )}
    </div>
  );
}
