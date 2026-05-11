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
import DependencyView from "./DependencyView.jsx";

const STATUS_COLOR = {
  COMPLETED: "#22c55e",
  FAILED: "#ef4444",
  BLOCKED: "#f97316",
  ACTIVE: "#3b82f6",
  PENDING: "#94a3b8",
  PAUSED: "#a78bfa",
  SKIPPED: "#64748b",
};

const RISK_COLOR = {
  LOW: "#22c55e",
  MEDIUM: "#f97316",
  HIGH: "#ef4444",
  CRITICAL: "#dc2626",
};

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

  if (!steps.length) {
    return (
      <div className="plan-view-empty muted">No plan steps in projection.</div>
    );
  }

  // Build step-id → index map for dependency labeling
  const stepIndexMap = {};
  steps.forEach((s, i) => {
    if (s.step_id) stepIndexMap[s.step_id] = i + 1;
  });

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

      {/* Step list */}
      <ol className="plan-step-list">
        {steps.map((step, i) => {
          const status = step.status || "PENDING";
          const color = STATUS_COLOR[status] || "#94a3b8";
          const riskColor = RISK_COLOR[step.risk] || "#94a3b8";
          const isExpanded = expandedStepId === step.step_id;
          const hasDeps = step.depends_on && step.depends_on.length > 0;

          return (
            <li
              key={step.step_id || i}
              className={`plan-step${status === "ACTIVE" ? " plan-step--active" : ""}${status === "COMPLETED" ? " plan-step--done" : ""}${status === "BLOCKED" ? " plan-step--blocked" : ""}`}
            >
              {/* Step number + status indicator */}
              <div className="plan-step-number-col">
                <span
                  className="plan-step-num"
                  style={{ borderColor: color, color }}
                  title={`Step ${i + 1}: ${status}`}
                >
                  {i + 1}
                </span>
                {i < steps.length - 1 && (
                  <div className="plan-step-connector" />
                )}
              </div>

              {/* Step content */}
              <div className="plan-step-body">
                <div className="plan-step-header">
                  <span className="plan-step-purpose">
                    {step.purpose || step.step_id || `Step ${i + 1}`}
                  </span>
                  <div className="plan-step-badges">
                    <span
                      className="plan-step-status-badge"
                      style={{ color, borderColor: color }}
                    >
                      {status}
                    </span>
                    {step.risk && (
                      <span
                        className="plan-step-risk-badge"
                        style={{ color: riskColor }}
                        title="Risk level"
                      >
                        {step.risk}
                      </span>
                    )}
                    {step.retries > 0 && (
                      <span className="plan-step-retry-badge">
                        ↩ {step.retries}
                      </span>
                    )}
                  </div>
                </div>

                {/* Expected outcome */}
                {step.expected_outcome && (
                  <div className="plan-step-outcome muted">
                    Expected: {step.expected_outcome}
                  </div>
                )}

                {/* Dependency labels — from canonical depends_on, NO local synthesis */}
                {hasDeps && (
                  <div className="plan-step-deps muted">
                    Depends on:{" "}
                    {step.depends_on.map((depId, di) => (
                      <span key={depId} className="dep-label">
                        #{stepIndexMap[depId] ?? depId}
                        {di < step.depends_on.length - 1 ? ", " : ""}
                      </span>
                    ))}
                  </div>
                )}

                {/* Blocked reason */}
                {status === "BLOCKED" && step.blocked_reason && (
                  <div className="step-blocked-reason">{step.blocked_reason}</div>
                )}

                {/* Expand detail toggle */}
                <button
                  className="btn-ghost plan-step-expand-btn"
                  onClick={() => setExpandedStepId(isExpanded ? null : step.step_id)}
                  aria-expanded={isExpanded}
                >
                  {isExpanded ? "▲ Less" : "▼ Detail"}
                </button>

                {/* Expanded: projection identity + fields */}
                {isExpanded && (
                  <div className="plan-step-detail fade-in">
                    <div className="plan-step-detail-row">
                      <span className="detail-label">Step ID:</span>
                      <span className="detail-val muted">{step.step_id}</span>
                    </div>
                    <div className="plan-step-detail-row">
                      <span className="detail-label">Type:</span>
                      <span className="detail-val muted">{step.step_type}</span>
                    </div>
                    <div className="plan-step-detail-row">
                      <span className="detail-label">Importance:</span>
                      <span className="detail-val muted">{step.importance}</span>
                    </div>
                    {step.resource_targets && step.resource_targets.length > 0 && (
                      <div className="plan-step-detail-row">
                        <span className="detail-label">Resources:</span>
                        <span className="detail-val muted">{step.resource_targets.join(", ")}</span>
                      </div>
                    )}
                    <div className="plan-step-detail-row">
                      <span className="detail-label">Projection v:</span>
                      <span className="detail-val muted">{step.projection_version}</span>
                    </div>
                    <div className="plan-step-detail-row">
                      <span className="detail-label">Proj state:</span>
                      <span className="detail-val muted">{step.projection_state}</span>
                    </div>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {/* Projection state footer */}
      {projectionState === "TERMINAL" && (
        <div className="plan-terminal-notice muted">
          Plan finalized — workflow {steps.some(s => s.status === "FAILED") ? "failed" : "completed"}.
        </div>
      )}
    </div>
  );
}
