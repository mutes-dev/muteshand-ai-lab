/**
 * DEPENDENCY NODE — PHASE 2 COMPONENT EXTRACTION
 *
 * Per WORKFLOW_STUDIO_PHASE2_COMPONENT_EXTRACTION:
 * Shared dependency node renderer for visualization views.
 *
 * Authority: CANONICAL_PROJECTION_MODEL_V1 §8
 *
 * RULES:
 * - Renders ONLY from canonical step_projection.depends_on
 * - NO local dependency synthesis
 * - NO derivation of implicit relationships
 */

import { STATUS_COLOR } from "../../constants/workflow.js";

/**
 * DependencyNode — compact step reference with status
 *
 * @param {Object} props
 * @param {Object} props.step — step object
 * @param {number} props.index — 1-based step number
 * @param {string} [props.variant="default"] — "default" | "source" | "target" | "independent"
 */
export default function DependencyNode({ step, index, variant = "default" }) {
  if (!step) return null;

  const status = step.status || "PENDING";
  const color = STATUS_COLOR[status] || "#94a3b8";
  const label = step.purpose || step.step_id || `Step ${index}`;

  const variantClass = `dep-node--${variant}`;

  return (
    <div className={`dep-node ${variantClass}`}>
      <span
        className="dep-node-num"
        style={{ borderColor: color, color }}
        title={`Step ${index}: ${status}`}
      >
        {index}
      </span>
      <span className="dep-node-label">{label}</span>
      <span className="dep-node-status" style={{ color }}>
        {status}
      </span>
    </div>
  );
}

/**
 * DependencyChain — visualizes a step with its dependencies
 *
 * @param {Object} props
 * @param {Object} props.step — target step
 * @param {number} props.stepIndex — target step number
 * @param {Array} props.sourceSteps — dependency step objects
 * @param {Object} props.stepMap — step_id → { step, index } mapping
 */
export function DependencyChain({ step, stepIndex, sourceSteps, stepMap }) {
  if (!step) return null;

  const status = step.status || "PENDING";
  const color = STATUS_COLOR[status] || "#94a3b8";

  return (
    <div className="dep-chain">
      {/* Dependency sources */}
      <div className="dep-sources">
        {sourceSteps.map((sourceStep) => {
          const sourceInfo = stepMap[sourceStep.step_id];
          const sourceStatus = sourceStep.status || "PENDING";
          const sourceColor = STATUS_COLOR[sourceStatus] || "#94a3b8";
          const sourceIdx = sourceInfo?.index ?? "?";
          const sourceLabel = sourceStep.purpose || sourceStep.step_id;

          return (
            <div key={sourceStep.step_id} className="dep-source-node">
              <span
                className="dep-node-num"
                style={{ borderColor: sourceColor, color: sourceColor }}
                title={`Step ${sourceIdx}: ${sourceStatus}`}
              >
                {sourceIdx}
              </span>
              <span className="dep-node-label muted">{sourceLabel}</span>
              <span className="dep-node-status" style={{ color: sourceColor }}>
                {sourceStatus}
              </span>
            </div>
          );
        })}
      </div>

      {/* Arrow: read from canonical depends_on */}
      <div className="dep-arrow" title="canonical depends_on relationship">
        <span className="dep-arrow-icon">→</span>
      </div>

      {/* Target step */}
      <div className="dep-target-node">
        <span
          className="dep-node-num"
          style={{ borderColor: color, color }}
          title={`Step ${stepIndex}: ${status}`}
        >
          {stepIndex}
        </span>
        <span className="dep-node-label">{step.purpose || step.step_id}</span>
        <span className="dep-node-status" style={{ color }}>
          {status}
        </span>
      </div>
    </div>
  );
}

/**
 * DependencyLabel — inline dependency reference
 *
 * Used for compact dependency display in step cards.
 *
 * @param {Object} props
 * @param {Array} props.dependsOn — array of step_ids
 * @param {Object} props.stepIndexMap — step_id → index mapping
 */
export function DependencyLabel({ dependsOn, stepIndexMap }) {
  if (!dependsOn || dependsOn.length === 0) return null;

  const labels = dependsOn.map((depId) => {
    const idx = stepIndexMap[depId];
    return idx ? `#${idx}` : depId.slice(0, 8);
  });

  return (
    <span className="dependency-label" title={`Depends on: ${dependsOn.join(", ")}`}>
      → {labels.join(", ")}
    </span>
  );
}

/**
 * IndependentStepList — grid of steps without dependencies
 *
 * @param {Object} props
 * @param {Array} props.steps — steps without dependencies
 * @param {Object} props.stepMap — step_id → { step, index } mapping
 */
export function IndependentStepList({ steps, stepMap }) {
  if (!steps || steps.length === 0) return null;

  return (
    <div className="dep-section">
      <div className="dep-section-label muted">Independent steps</div>
      <div className="dep-row-group">
        {steps.map((step) => {
          const info = stepMap[step.step_id];
          const idx = info?.index ?? "?";
          return (
            <DependencyNode
              key={step.step_id}
              step={step}
              index={idx}
              variant="independent"
            />
          );
        })}
      </div>
    </div>
  );
}
