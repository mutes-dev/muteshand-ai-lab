/**
 * STEP CARD — PHASE 2 COMPONENT EXTRACTION
 *
 * Per WORKFLOW_STUDIO_PHASE2_COMPONENT_EXTRACTION:
 * Unified reusable step renderer for projection/plan/dependency views.
 *
 * Authority: CANONICAL_PROJECTION_MODEL_V1, GUI_ARCHITECTURE.txt
 *
 * RULES:
 * - PRESENTATIONAL ONLY — no authority logic
 * - NO lifecycle synthesis — receives all data as props
 * - NO polling — pure rendering
 * - NO orchestration awareness
 *
 * Modes: compact | full | editable (render only)
 *
 * Previously duplicated across: PlanView, WorkflowProjectionView, DependencyView
 */

import { useState } from "react";
import { STATUS_COLOR, RISK_COLOR, formatStepNumber } from "../../constants/workflow.js";
import StatusBadge from "./StatusBadge.jsx";
import RetryBadge from "./RetryBadge.jsx";
import { DependencyLabel } from "./DependencyNode.jsx";

/**
 * StepCard — PHASE 5 EDITABLE — unified step renderer with editing support
 *
 * @param {Object} props
 * @param {Object} props.step — step projection data
 * @param {number} props.stepNumber — 1-based step number
 * @param {string} props.mode — "compact" | "full" | "editable"
 * @param {Object} [props.stepIndexMap] — for dependency resolution
 * @param {boolean} [props.expanded] — detail expansion state
 * @param {Function} [props.onExpand] — expansion toggle handler
 * @param {Function} [props.onEdit] — edit button handler
 * @param {Function} [props.onRetry] — retry button handler
 * @param {boolean} [props.showEditButton] — show edit affordance
 * @param {boolean} [props.showRetryButton] — show retry affordance
 * @param {boolean} [props.isEditable] — enable edit styling
 * @param {Object} [props.output] — step execution output (for COMPLETED steps)
 * @param {boolean} [props.isProcessing] — show processing indicator (for ACTIVE steps)
 * @param {boolean} [props.isPaused] — show paused state
 *
 * PHASE 5 EDITABLE PROPS:
 * @param {boolean} [props.isEditing] — this step is in edit mode
 * @param {Object} [props.draftValues] — staged edit values { purpose, expected_outcome, depends_on }
 * @param {Function} [props.onDraftChange] — draft value change handler
 * @param {Function} [props.onSave] — save mutation intent handler
 * @param {Function} [props.onCancel] — cancel edit handler
 * @param {boolean} [props.isSaving] — save in progress (disables controls)
 * @param {string} [props.editError] — validation/error message
 */
export default function StepCard({
  step,
  stepNumber,
  mode = "full",
  stepIndexMap = {},
  expanded = false,
  onExpand,
  onEdit,
  onRetry,
  showEditButton = false,
  showRetryButton = false,
  isEditable = false,
  output = null,
  isProcessing = false,
  isPaused = false,
  // Phase 5 editable props
  isEditing = false,
  draftValues = null,
  onDraftChange,
  onSave,
  onCancel,
  isSaving = false,
  editError = null,
}) {
  if (!step) return null;

  const { step_id, purpose, status, step_type, risk, importance, expected_outcome, depends_on, retries, blocked_reason, resource_targets, projection_version, projection_state } = step;

  const isCompact = mode === "compact";
  const isFull = mode === "full" || mode === "editable";
  const isEditableMode = mode === "editable";
  const isCompleted = status === "COMPLETED";
  const isActive = status === "ACTIVE";
  const isBlocked = status === "BLOCKED";

  // Use draft values when editing, otherwise use canonical projection values
  const displayPurpose = isEditing && draftValues?.purpose !== undefined
    ? draftValues.purpose
    : purpose;
  const displayExpectedOutcome = isEditing && draftValues?.expected_outcome !== undefined
    ? draftValues.expected_outcome
    : expected_outcome;

  return (
    <div
      className={`step-card step-card--${mode} ${expanded ? "step-card--expanded" : ""}`}
      data-step-id={step_id}
      data-step-number={stepNumber}
    >
      {/* Header Row: Number + Status + Purpose */}
      <div className="step-card__header">
        <span className="step-card__number" title={`Step ${stepNumber}`}>
          {stepNumber}
        </span>

        <StatusBadge status={status} size={isCompact ? "small" : "medium"} />

        {/* Editable Purpose Field */}
        {isEditing ? (
          <input
            className="step-card__purpose-input"
            type="text"
            value={displayPurpose || ""}
            onChange={(e) => onDraftChange?.({ purpose: e.target.value })}
            placeholder="Step purpose..."
            disabled={isSaving}
          />
        ) : (
          <span className="step-card__purpose" title={purpose}>
            {displayPurpose || "Untitled step"}
          </span>
        )}

        {/* Dirty State Indicator */}
        {isEditing && draftValues && (
          <span className="step-card__dirty-indicator" title="Unsaved changes">
            ●
          </span>
        )}

        {retries > 0 && !isEditing && (
          <RetryBadge retries={retries} size="small" variant="subtle" />
        )}

        {/* Edit Controls */}
        {isEditableMode && !isEditing && (
          <button
            className="step-card__edit-btn"
            onClick={() => onEdit?.(step)}
            title="Edit step"
            disabled={!onEdit || isSaving}
          >
            ✎
          </button>
        )}

        {isEditing && (
          <>
            <button
              className="step-card__save-btn"
              onClick={() => onSave?.(step_id, draftValues)}
              disabled={isSaving}
              title="Save changes"
            >
              {isSaving ? "..." : "✓"}
            </button>
            <button
              className="step-card__cancel-btn"
              onClick={() => onCancel?.(step_id)}
              disabled={isSaving}
              title="Cancel editing"
            >
              ✕
            </button>
          </>
        )}

        {showRetryButton && !isEditing && (
          <button
            className="step-card__retry-btn"
            onClick={() => onRetry?.(step)}
            title="Retry step"
            disabled={!onRetry || isSaving}
          >
            ↩
          </button>
        )}

        {isFull && onExpand && !isEditing && (
          <button
            className="step-card__expand-btn"
            onClick={() => onExpand(step_id)}
            title={expanded ? "Collapse details" : "Expand details"}
          >
            {expanded ? "▲" : "▼"}
          </button>
        )}
      </div>

      {/* Edit Error Display */}
      {isEditing && editError && (
        <div className="step-card__error">
          ⚠ {editError}
        </div>
      )}

      {/* Metadata Row: Type + Risk + Importance */}
      {!isCompact && (
        <div className="step-card__meta">
          {step_type && (
            <span className="step-card__type">{step_type}</span>
          )}

          {risk && (
            <span
              className="step-card__risk"
              style={{ color: RISK_COLOR[risk] || "#94a3b8" }}
            >
              {risk}
            </span>
          )}

          {importance && importance !== "MEDIUM" && (
            <span
              className="step-card__importance"
              style={{ color: RISK_COLOR[importance] || "#94a3b8" }}
            >
              {importance}
            </span>
          )}

          {depends_on && depends_on.length > 0 && (
            <DependencyLabel dependsOn={depends_on} stepIndexMap={stepIndexMap} />
          )}

          {blocked_reason && status === "BLOCKED" && (
            <BlockedReason reason={blocked_reason} />
          )}
        </div>
      )}

      {/* Output Preview (for completed steps) */}
      {isFull && isCompleted && output && (
        <StepOutputPreview output={output} />
      )}

      {/* Processing Indicator (for active steps) */}
      {isFull && isActive && isProcessing && (
        <div className="step-card__processing">
          {isPaused ? "⏸ paused" : "… processing"}
        </div>
      )}

      {/* Expanded Detail Section */}
      {isFull && expanded && (
        <StepDetailSection
          step={step}
          stepNumber={stepNumber}
          stepIndexMap={stepIndexMap}
          output={output}
        />
      )}
    </div>
  );
}

/**
 * BlockedReason — renders blocked status with reason
 */
function BlockedReason({ reason }) {
  if (!reason) return null;

  return (
    <span className="step-card__blocked" title={reason}>
      ⊘ {reason.length > 40 ? reason.slice(0, 40) + "..." : reason}
    </span>
  );
}

/**
 * StepDetailSection — PHASE 4 ENHANCED — expanded detail view for full mode
 */
function StepDetailSection({ step, stepNumber, stepIndexMap, output }) {
  const { step_id, purpose, step_type, expected_outcome, depends_on, blocked_reason, retries, status, resource_targets, projection_version, projection_state } = step;

  return (
    <div className="step-card__detail">
      {/* Core Identity */}
      <DetailRow label="Step ID" value={step_id} monospace />
      <DetailRow label="Purpose" value={purpose} />
      <DetailRow label="Type" value={step_type} />

      {/* Lifecycle */}
      <DetailRow label="Status" value={status} badge={status} />
      {retries > 0 && (
        <DetailRow label="Retries" value={`${retries} attempt${retries !== 1 ? "s" : ""}`} />
      )}

      {/* Metadata */}
      <DetailRow label="Expected Outcome" value={expected_outcome} />

      {/* Output (if available) */}
      {output && output.execution_result && (
        <DetailRow
          label="Result"
          value={output.execution_result.result}
          className="detail-row--result"
        />
      )}

      {/* Resource Targets */}
      {resource_targets && resource_targets.length > 0 && (
        <DetailRow label="Resources" value={resource_targets.join(", ")} />
      )}

      {/* Dependencies */}
      {depends_on && depends_on.length > 0 && (
        <DependencyDetail dependsOn={depends_on} stepIndexMap={stepIndexMap} />
      )}

      {/* Blocked Reason */}
      {blocked_reason && (
        <DetailRow
          label="Blocked"
          value={blocked_reason}
          className="detail-row--blocked"
        />
      )}

      {/* Projection Metadata (debug/observability) */}
      {projection_version !== undefined && (
        <DetailRow label="Projection v" value={projection_version} />
      )}
      {projection_state && (
        <DetailRow label="Proj State" value={projection_state} />
      )}
    </div>
  );
}

/**
 * StepOutputPreview — compact output display for completed steps
 */
function StepOutputPreview({ output }) {
  if (!output || !output.execution_result) return null;

  const result = output.execution_result.result;
  const truncated = result && result.length > 60 ? result.slice(0, 60) + "..." : result;

  return (
    <div className="step-card__output">
      <span className="output-label">→</span>
      <span className="output-value" title={result}>
        {truncated || "done"}
      </span>
    </div>
  );
}

/**
 * DetailRow — reusable detail row
 */
function DetailRow({ label, value, monospace = false, badge = null, className = "" }) {
  if (!value && value !== 0) return null;

  return (
    <div className={`detail-row ${className}`}>
      <span className="detail-row__label">{label}:</span>
      <span className={`detail-row__value ${monospace ? "detail-row__value--mono" : ""}`}>
        {badge ? <StatusBadge status={badge} size="small" /> : value}
      </span>
    </div>
  );
}

/**
 * DependencyDetail — expanded dependency view
 */
function DependencyDetail({ dependsOn, stepIndexMap }) {
  return (
    <div className="detail-row detail-row--dependencies">
      <span className="detail-row__label">Dependencies:</span>
      <span className="detail-row__value">
        {dependsOn.map((depId) => {
          const idx = stepIndexMap[depId];
          return idx ? `Step ${idx}` : depId.slice(0, 8);
        }).join(", ")}
      </span>
    </div>
  );
}

/**
 * StepCardList — PHASE 5 EDITABLE — list container with draft state support
 */
export function StepCardList({
  steps,
  mode = "full",
  expandedStepId,
  onExpand,
  stepIndexMap = {},
  onEdit,
  onRetry,
  showEditButtons = false,
  showRetryButtons = false,
  isEditable = false,
  outputs = [],
  isProcessing = false,
  isPaused = false,
  // Phase 5 editable props
  editingStepId = null,
  draftValues = {},
  onDraftChange,
  onSave,
  onCancel,
  isSaving = false,
  editErrors = {},
}) {
  if (!steps || steps.length === 0) {
    return <div className="step-card-list step-card-list--empty">No steps</div>;
  }

  // Build output lookup map
  const outputMap = {};
  outputs.forEach((output) => {
    if (output.step_id) {
      outputMap[output.step_id] = output;
    }
  });

  return (
    <div className="step-card-list">
      {steps.map((step, index) => (
        <StepCard
          key={step.step_id || index}
          step={step}
          stepNumber={index + 1}
          mode={mode}
          stepIndexMap={stepIndexMap}
          expanded={expandedStepId === step.step_id}
          onExpand={onExpand}
          onEdit={onEdit}
          onRetry={onRetry}
          showEditButton={showEditButtons}
          showRetryButton={showRetryButtons}
          isEditable={isEditable}
          output={outputMap[step.step_id]}
          isProcessing={isProcessing && step.status === "ACTIVE"}
          isPaused={isPaused}
          // Phase 5 editable props
          isEditing={editingStepId === step.step_id}
          draftValues={draftValues}
          onDraftChange={onDraftChange}
          onSave={onSave}
          onCancel={onCancel}
          isSaving={isSaving}
          editError={editErrors[step.step_id]}
        />
      ))}
    </div>
  );
}

/**
 * CompactStepCard — minimal variant for dense lists
 */
export function CompactStepCard({ step, stepNumber, stepIndexMap = {} }) {
  return (
    <StepCard
      step={step}
      stepNumber={stepNumber}
      mode="compact"
      stepIndexMap={stepIndexMap}
    />
  );
}
