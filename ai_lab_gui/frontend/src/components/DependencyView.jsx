/**
 * DEPENDENCY VIEW — PHASE 4B.0 — SUB-PHASE 3C
 *
 * Per CANONICAL_PROJECTION_MODEL_V1 §8 (Plan Projection Model):
 * - Dependency relationships rendered FROM canonical projections only
 * - Frontend MUST NOT derive hidden dependencies locally
 * - Frontend MUST NOT synthesize dependency state
 *
 * Per GUI_ARCHITECTURE.txt:
 * - Workflow-scoped visualization
 * - Deterministic ordering
 * - Continuity-safe rendering
 *
 * Per PROJECTION_CONTINUITY_CONTRACT_V1:
 * - Dependency visualization uses canonical step_projection.depends_on field
 * - No local reconstruction of implicit relationships
 *
 * PROHIBITED:
 * - No derivation of hidden or implicit dependencies
 * - No local dependency synthesis
 * - No mutation of dependency graph
 * - No reorder controls
 */

const STATUS_COLOR = {
  COMPLETED: "#22c55e",
  FAILED: "#ef4444",
  BLOCKED: "#f97316",
  ACTIVE: "#3b82f6",
  PENDING: "#94a3b8",
  PAUSED: "#a78bfa",
  SKIPPED: "#64748b",
};

/**
 * DependencyView
 *
 * Renders a read-only textual dependency graph from canonical step projections.
 * Dependencies are read ONLY from step.depends_on — the canonical field.
 * No derivation, no inference, no local synthesis.
 *
 * Props:
 *   steps           — canonical StepProjection[] from WorkflowProjection.steps
 *   workflowId      — owning workflow_id
 *   projectionVersion — current projection_version
 */
export default function DependencyView({ steps = [], workflowId, projectionVersion }) {
  if (!steps.length) {
    return (
      <div className="dep-view dep-view-empty muted">
        No dependency data in projection.
      </div>
    );
  }

  // Build step index map for display labels
  // Source: canonical step_projection.step_id — no local derivation
  const stepMap = {};
  steps.forEach((s, i) => {
    if (s.step_id) {
      stepMap[s.step_id] = { step: s, index: i + 1 };
    }
  });

  // Identify steps with dependencies vs independent steps
  const stepsWithDeps = steps.filter(s => s.depends_on && s.depends_on.length > 0);
  const independentSteps = steps.filter(s => !s.depends_on || s.depends_on.length === 0);

  return (
    <div className="dep-view">
      <div className="dep-view-header">
        <span className="dep-view-title muted">
          Dependency Map
        </span>
        <span className="plan-badge plan-badge--version">v{projectionVersion}</span>
        <span className="dep-view-note muted">
          — canonical projection source, read-only
        </span>
      </div>

      {/* Independent steps: no dependencies */}
      {independentSteps.length > 0 && (
        <div className="dep-section">
          <div className="dep-section-label muted">Independent steps</div>
          <div className="dep-row-group">
            {independentSteps.map((step, i) => {
              const status = step.status || "PENDING";
              const color = STATUS_COLOR[status] || "#94a3b8";
              const idx = stepMap[step.step_id]?.index ?? "?";
              return (
                <div key={step.step_id || i} className="dep-node dep-node--independent">
                  <span
                    className="dep-node-num"
                    style={{ borderColor: color, color }}
                    title={`Step ${idx}: ${status}`}
                  >
                    {idx}
                  </span>
                  <span className="dep-node-label">{step.purpose || step.step_id}</span>
                  <span className="dep-node-status" style={{ color }}>{status}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Steps with explicit dependencies */}
      {stepsWithDeps.length > 0 && (
        <div className="dep-section">
          <div className="dep-section-label muted">Dependency chains</div>
          {stepsWithDeps.map((step, i) => {
            const status = step.status || "PENDING";
            const color = STATUS_COLOR[status] || "#94a3b8";
            const idx = stepMap[step.step_id]?.index ?? "?";

            return (
              <div key={step.step_id || i} className="dep-chain">
                {/* Dependency sources */}
                <div className="dep-sources">
                  {step.depends_on.map((depId) => {
                    const depInfo = stepMap[depId];
                    const depStatus = depInfo?.step?.status || "UNKNOWN";
                    const depColor = STATUS_COLOR[depStatus] || "#94a3b8";
                    const depIdx = depInfo?.index ?? depId;
                    const depLabel = depInfo?.step?.purpose || depId;

                    return (
                      <div key={depId} className="dep-source-node">
                        <span
                          className="dep-node-num"
                          style={{ borderColor: depColor, color: depColor }}
                          title={`Step ${depIdx}: ${depStatus}`}
                        >
                          {depIdx}
                        </span>
                        <span className="dep-node-label muted">{depLabel}</span>
                        <span className="dep-node-status" style={{ color: depColor }}>{depStatus}</span>
                      </div>
                    );
                  })}
                </div>

                {/* Arrow: read from canonical depends_on, not derived */}
                <div className="dep-arrow" title="canonical depends_on relationship">
                  <span className="dep-arrow-icon">→</span>
                </div>

                {/* This step */}
                <div className="dep-target-node">
                  <span
                    className="dep-node-num"
                    style={{ borderColor: color, color }}
                    title={`Step ${idx}: ${status}`}
                  >
                    {idx}
                  </span>
                  <span className="dep-node-label">{step.purpose || step.step_id}</span>
                  <span className="dep-node-status" style={{ color }}>{status}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* No dependencies at all */}
      {stepsWithDeps.length === 0 && (
        <div className="dep-no-deps muted">
          No explicit dependencies in canonical projection (all steps are independent).
        </div>
      )}
    </div>
  );
}
