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
import { formatDisplayValue, formatDisplayValueCompact } from "../../utils/formatDisplayValue.js";

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
 * @param {string|Object} [props.editError] — validation/error message or { message, category }
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
  // Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
  // Optional transition history derived from authoritative events.
  transitionHistory = [],
}) {
  if (!step) return null;

  const { step_id, purpose, status, step_type, risk, importance, expected_outcome, depends_on, retries, retry_generation, blocked_reason, resource_targets, projection_version, projection_state } = step;

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
  const displayRisk = isEditing && draftValues?.risk !== undefined
    ? draftValues.risk
    : risk;
  const displayImportance = isEditing && draftValues?.importance !== undefined
    ? draftValues.importance
    : importance;

  return (
    <div
      className={`step-card step-card--${mode} ${expanded ? "step-card--expanded" : ""} ${isActive ? "step-card--active" : ""} ${isEditing ? "step-card--editing" : ""}`}
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
        {retry_generation > 0 && !isEditing && (
          <span
            className="retry-generation-badge"
            style={{ fontSize: "0.7rem", color: "#94a3b8", marginLeft: "0.25rem" }}
            title="User-initiated retry attempts"
          >
            ({retry_generation} user retry{retry_generation !== 1 ? "s" : ""})
          </span>
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
            title="Retry step — new execution attempt"
            disabled={!onRetry || isSaving}
          >
            ⟳
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

      {/* Edit Error Display — governance vs system categorization */}
      {isEditing && editError && (
        <div
          className={`step-card__error ${typeof editError === "object" && editError.category === "governance"
            ? "step-card__error--governance"
            : ""
            }`}
        >
          {typeof editError === "object" ? editError.message : editError}
        </div>
      )}

      {/* Edit Form — operational metadata fields */}
      {isEditing && (
        <div className="step-card__edit-form">
          {/* Expected Outcome — visually subordinate, multiline */}
          <label className="step-card__edit-label muted">Expected Outcome</label>
          <textarea
            className="step-card__expected-outcome-input"
            value={displayExpectedOutcome || ""}
            onChange={(e) => onDraftChange?.({ expected_outcome: e.target.value })}
            placeholder="Describe the expected outcome..."
            disabled={isSaving}
            rows={3}
          />
        </div>
      )}

      {/* Metadata Row: Type + Risk + Importance */}
      {!isCompact && (
        <div className="step-card__meta">
          {step_type && !isEditing && (
            <span className="step-card__type">{step_type}</span>
          )}

          {/* Risk — editable select in edit mode, static badge otherwise */}
          {isEditing ? (
            <span className="step-card__meta-field">
              <span className="step-card__meta-label muted">Risk</span>
              <select
                className="step-card__select"
                value={displayRisk || "MEDIUM"}
                onChange={(e) => onDraftChange?.({ risk: e.target.value })}
                disabled={isSaving}
              >
                <option value="LOW">LOW</option>
                <option value="MEDIUM">MEDIUM</option>
                <option value="HIGH">HIGH</option>
                <option value="CRITICAL">CRITICAL</option>
              </select>
            </span>
          ) : (
            displayRisk && (
              <span
                className="step-card__risk"
                style={{ color: RISK_COLOR[displayRisk] || "#94a3b8" }}
              >
                {displayRisk}
              </span>
            )
          )}

          {/* Importance — editable select in edit mode, static badge otherwise */}
          {isEditing ? (
            <span className="step-card__meta-field">
              <span className="step-card__meta-label muted">Importance</span>
              <select
                className="step-card__select"
                value={displayImportance || "MEDIUM"}
                onChange={(e) => onDraftChange?.({ importance: e.target.value })}
                disabled={isSaving}
              >
                <option value="LOW">LOW</option>
                <option value="MEDIUM">MEDIUM</option>
                <option value="HIGH">HIGH</option>
                <option value="CRITICAL">CRITICAL</option>
              </select>
            </span>
          ) : (
            displayImportance && displayImportance !== "MEDIUM" && (
              <span
                className="step-card__importance"
                style={{ color: RISK_COLOR[displayImportance] || "#94a3b8" }}
              >
                {displayImportance}
              </span>
            )
          )}

          {depends_on && depends_on.length > 0 && (
            <DependencyLabel dependsOn={depends_on} stepIndexMap={stepIndexMap} />
          )}

          {blocked_reason && status === "BLOCKED" && (
            <BlockedReason reason={blocked_reason} stepIndexMap={stepIndexMap} />
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
          // Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
          transitionHistory={transitionHistory}
        />
      )}
    </div>
  );
}

/**
 * Humanize raw backend dependency messages into operator-readable text.
 * Preserves raw data in tooltip for debugging.
 */
function humanizeBlockedReason(reason, stepIndexMap = {}) {
  if (!reason) return null;

  // Pattern: approval_required — operator-facing, not raw backend string
  if (reason === "approval_required" || reason.includes("approval")) {
    return "Waiting for approval";
  }

  // Pattern: external_call_risk — user-control review, not raw backend string
  if (reason === "external_call_risk" || reason.includes("external_call")) {
    return "Waiting for review";
  }

  // Pattern: dependency_not_completed:step_id:ANY_STATUS (generic trailing status)
  const depMatch = reason.match(/^dependency_not_completed:([^:]+):([A-Z]+)$/);
  if (depMatch) {
    const depId = depMatch[1];
    const depIdx = stepIndexMap[depId];
    const depLabel = depIdx ? `Step ${depIdx}` : depId.slice(0, 8);
    return `Waiting for ${depLabel} to complete`;
  }

  // Pattern: dependency_not_completed:step_id (without trailing status)
  const depSimpleMatch = reason.match(/^dependency_not_completed:([^:]+)$/);
  if (depSimpleMatch) {
    const depId = depSimpleMatch[1];
    const depIdx = stepIndexMap[depId];
    const depLabel = depIdx ? `Step ${depIdx}` : depId.slice(0, 8);
    return `Waiting for ${depLabel}`;
  }

  // Graceful fallback: NEVER show raw backend string in primary UI
  return "Blocked";
}

/**
 * BlockedReason — renders blocked status with humanized operator-facing message
 */
function BlockedReason({ reason, stepIndexMap = {} }) {
  if (!reason) return null;

  const humanized = humanizeBlockedReason(reason, stepIndexMap);

  return (
    <span className="step-card__blocked" title={`Raw: ${reason}`}>
      ⊘ {humanized}
    </span>
  );
}

/**
 * StepDetailSection — PHASE 4 ENHANCED — expanded detail view for full mode
 */
function StepDetailSection({ step, stepNumber, stepIndexMap, output, transitionHistory = [] }) {
  const { step_id, purpose, step_type, expected_outcome, depends_on, blocked_reason, retries, retry_generation, status, resource_targets, projection_version, projection_state } = step;
  const [showDebugDetails, setShowDebugDetails] = useState(false);

  return (
    <div className="step-card__detail">
      {/* CORE INFO — operator-critical */}
      <div className="detail-section">
        <div className="detail-section__title">Step Information</div>
        <DetailRow label="Purpose" value={purpose} />
        <DetailRow label="Expected Outcome" value={expected_outcome} />
        {step_type && <DetailRow label="Type" value={step_type} />}
      </div>

      {/* EXECUTION — results, resources, blocked */}
      <div className="detail-section">
        <div className="detail-section__title">Execution</div>
        <DetailRow label="Status" value={status} badge={status} />
        {retries > 0 && (
          <DetailRow label="System Retries" value={`${retries} automatic attempt${retries !== 1 ? "s" : ""}`} />
        )}
        {retry_generation > 0 && (
          <DetailRow label="User Retries" value={`${retry_generation} manual attempt${retry_generation !== 1 ? "s" : ""}`} />
        )}
        {output && output.execution_result && (
          <DetailRow
            label="Result"
            value={formatDisplayValue(output.execution_result.result)}
            className="detail-row--result"
          />
        )}
        {resource_targets && resource_targets.length > 0 && (
          <DetailRow label="Resources" value={resource_targets.join(", ")} />
        )}
        {blocked_reason && (
          <DetailRow
            label="Blocked"
            value={blocked_reason}
            className="detail-row--blocked"
          />
        )}
      </div>

      {/* TRANSITION HISTORY — Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT */}
      {transitionHistory && transitionHistory.length > 0 && (
        <div className="detail-section">
          <div className="detail-section__title">Transition History</div>
          {transitionHistory.map((t, idx) => (
            <DetailRow
              key={idx}
              label={idx === 0 ? "Transitions" : ""}
              value={`${t.from} → ${t.to}`}
            />
          ))}
        </div>
      )}

      {/* DEPENDENCIES */}
      {depends_on && depends_on.length > 0 && (
        <div className="detail-section">
          <div className="detail-section__title">Dependencies</div>
          <DependencyDetail dependsOn={depends_on} stepIndexMap={stepIndexMap} />
        </div>
      )}

      {/* AGENT-001F-IMPL1: Agent Info — compact capability route attribution */}
      {(projection_version !== undefined || projection_state || step_id || step.agent_metadata || step.capability_metadata) && (
        <div className="detail-section detail-section--debug">
          <div className="detail-section__title">
            {step.agent_metadata || step.capability_metadata ? "Agent Info" : "Projection Metadata"}
          </div>

          {/* === COMPACT DEFAULT — operator-facing route attribution === */}
          {step.capability_metadata && step.capability_metadata.capability_id ? (
            <DetailRow label="Route" value={step.capability_metadata.capability_id} />
          ) : (
            <DetailRow label="Route" value="planner" />
          )}
          {step.agent_metadata && (
            <>
              <DetailRow label="Tool selector" value={step.agent_metadata.selected_agent || "—"} />
              <DetailRow label="Selected tool" value={step.agent_metadata.selected_tool || "—"} />
            </>
          )}
          {step.capability_metadata && step.capability_metadata.allowed_tool ? (
            <DetailRow label="Allowed tool" value={step.capability_metadata.allowed_tool} />
          ) : (
            step.agent_metadata && <DetailRow label="Allowed tool" value="—" />
          )}
          {step.agent_metadata && (
            <DetailRow label="Authority" value={step.agent_metadata.agent_authority || "advisory_only"} />
          )}

          {/* === EXPANDABLE DEBUG DETAILS === */}
          {(step.agent_metadata || step_id || projection_version !== undefined || projection_state) && (
            <>
              <button
                className="step-card__debug-toggle"
                onClick={() => setShowDebugDetails((v) => !v)}
                style={{
                  background: "none",
                  border: "1px solid var(--border)",
                  borderRadius: "4px",
                  color: "var(--muted)",
                  cursor: "pointer",
                  fontSize: "0.75rem",
                  padding: "2px 8px",
                  marginTop: "4px",
                }}
              >
                {showDebugDetails ? "▲ Hide debug details" : "▼ Show debug details"}
              </button>
              {showDebugDetails && (
                <>
                  <div className="detail-section__subtitle">Debug Details</div>
                  {step_id && <DetailRow label="Step ID" value={step_id} monospace />}
                  {projection_version !== undefined && (
                    <DetailRow label="Version" value={projection_version} />
                  )}
                  {projection_state && <DetailRow label="State" value={projection_state} />}
                  {step.agent_metadata && (
                    <>
                      <DetailRow label="Agent Type" value={step.agent_metadata.selected_agent_type} />
                      <DetailRow label="Routing Source" value={step.agent_metadata.routing_source} />
                      <DetailRow label="System Entry" value={step.agent_metadata.system_entry_routed ? "routed" : "not routed"} />
                      {step.agent_metadata.selected_agent_version && (
                        <DetailRow label="Agent Version" value={step.agent_metadata.selected_agent_version} />
                      )}
                      {step.agent_metadata.selected_agent_capabilities && (
                        <DetailRow label="Agent abilities" value={step.agent_metadata.selected_agent_capabilities.join(", ")} />
                      )}
                    </>
                  )}
                  {step.capability_metadata && (
                    <>
                      {step.capability_metadata.route_confidence !== undefined && (
                        <DetailRow label="Route confidence" value={String(step.capability_metadata.route_confidence)} />
                      )}
                      {step.capability_metadata.route_reason_code && (
                        <DetailRow label="Route reason" value={step.capability_metadata.route_reason_code} />
                      )}
                      {step.capability_metadata.allowed_tool_family && (
                        <DetailRow label="Allowed family" value={step.capability_metadata.allowed_tool_family} />
                      )}
                    </>
                  )}
                </>
              )}
            </>
          )}
        </div>
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
  const compact = formatDisplayValueCompact(result);

  return (
    <div className="step-card__output">
      <span className="output-label">→</span>
      <span className="output-value" title={formatDisplayValue(result)}>
        {compact || "done"}
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
      <span className="detail-row__value">
        {dependsOn.map((depId) => {
          const idx = stepIndexMap[depId];
          return (
            <span key={depId} className="dep-chip">
              {idx ? `Step ${idx}` : depId.slice(0, 8)}
            </span>
          );
        })}
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
  // Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
  // Optional transition history per step for chronology visibility.
  stepTransitions = {},
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
          // Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
          transitionHistory={stepTransitions[step.step_id]}
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
