/**
 * STUDIO TOOLBAR — PHASE 3 STUDIO SHELL
 *
 * Per WORKFLOW_STUDIO_PHASE3_SHELL:
 * Workflow identity display, lifecycle indicator, and mode navigation.
 *
 * Authority: GUI_ARCHITECTURE.txt
 *
 * RULES:
 * - Presentation only — no authority logic
 * - Renders provided projection metadata
 * - Mode switching is pure UI (no projection impact)
 */

import { WorkflowStatusBadge, ProjectionStateBadge } from "../shared/StatusBadge.jsx";
import { isImmutableTerminal, isRecoverableTerminal } from "../../constants/workflow.js";

const MODE_LABELS = {
  overview: { label: "Overview", icon: "⊞" },
  plan: { label: "Plan", icon: "☰" },
  dependencies: { label: "Dependencies", icon: "⬡" },
  edit: { label: "Edit", icon: "✎" },
};

/**
 * StudioToolbar — workflow identity + lifecycle + mode navigation
 *
 * @param {Object} props
 * @param {string} props.workflowId — workflow identifier
 * @param {string} props.workflowName — human-readable name
 * @param {string} props.lifecycleStatus — QUEUED | ACTIVE | PAUSED | BLOCKED | COMPLETED | FAILED
 * @param {number} props.projectionVersion — projection version
 * @param {string} props.projectionState — ACTIVE | TERMINAL | STALE | INVALIDATED
 * @param {string} props.activeMode — current mode key
 * @param {Array} props.availableModes — array of mode keys
 * @param {Function} props.onModeChange — mode switch handler
 * @param {Function} props.onRefresh — manual refresh request
 */
export default function StudioToolbar({
  workflowId,
  workflowName,
  lifecycleStatus,
  projectionVersion,
  projectionState,
  activeMode,
  availableModes,
  onModeChange,
  onRefresh,
  showChronology,
  onToggleChronology,
}) {
  const displayName = workflowName || workflowId?.slice(0, 16) || "Workflow";
  const isImmutable = isImmutableTerminal(lifecycleStatus);
  const isRecoverable = isRecoverableTerminal(lifecycleStatus);

  return (
    <div className="studio-toolbar">
      {/* Left: Workflow Identity */}
      <div className="studio-toolbar__identity">
        <span className="studio-toolbar__descriptor muted">Workflow</span>
        <h2 className="studio-toolbar__title" title={workflowId}>
          {displayName}
        </h2>
        <span className="studio-toolbar__id" title={workflowId}>
          {workflowId?.slice(0, 10)}
        </span>
      </div>

      {/* Center: Lifecycle (dominant) + Projection State (subordinate) */}
      <div className="studio-toolbar__status">
        {lifecycleStatus && (
          <WorkflowStatusBadge status={lifecycleStatus} size="medium" />
        )}
        {/* FAILED recoverable semantics badge */}
        {isRecoverable && (
          <span
            className="studio-toolbar__recoverable-badge"
            title="Recoverable terminal state — retry and edit are permitted"
          >
            ↻ Recoverable
          </span>
        )}
        {projectionState && (
          <span className="studio-toolbar__projection-qualifier muted" title="Projection synchronization state — not lifecycle authority">
            Projection: <ProjectionStateBadge state={projectionState} size="small" />
          </span>
        )}
      </div>

      {/* Right: Mode Navigation */}
      <div className="studio-toolbar__modes">
        {availableModes.map((mode) => {
          const config = MODE_LABELS[mode];
          const isActive = mode === activeMode;
          const lifecycleIsActive = lifecycleStatus === "ACTIVE";
          const isDisabled = (isImmutable || lifecycleIsActive) && mode === "edit"; // Disable edit for immutable terminals AND active execution

          return (
            <button
              key={mode}
              className={`studio-toolbar__mode-btn ${isActive ? "studio-toolbar__mode-btn--active" : ""
                } ${isDisabled ? "studio-toolbar__mode-btn--disabled" : ""}`}
              onClick={() => !isDisabled && onModeChange(mode)}
              disabled={isDisabled}
              title={
                isDisabled
                  ? lifecycleIsActive
                    ? "Editing disabled — workflow is ACTIVE. Mutations are prohibited during execution. Pause to enable editing."
                    : `Editing disabled — workflow is ${lifecycleStatus?.toLowerCase() || "completed"} (immutable terminal state)`
                  : isRecoverable && mode === "edit"
                    ? "Edit mode — recoverable terminal state allows mutation and retry"
                    : config.label
              }
            >
              <span className="mode-btn__icon">{config.icon}</span>
              <span className="mode-btn__label">{config.label}</span>
            </button>
          );
        })}

        {/* Refresh button */}
        {onRefresh && (
          <button
            className="studio-toolbar__refresh-btn"
            onClick={onRefresh}
            title="Refresh projection"
          >
            ↻
          </button>
        )}

        {/* Chronology sidebar toggle — observability-only companion */}
        {onToggleChronology && (
          <button
            className={`studio-toolbar__chronology-btn${showChronology ? " studio-toolbar__chronology-btn--active" : ""}`}
            onClick={onToggleChronology}
            title={showChronology ? "Hide chronology" : "Show execution chronology"}
          >
            ◷
          </button>
        )}
      </div>
    </div>
  );
}
