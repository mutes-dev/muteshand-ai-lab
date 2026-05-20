/**
 * STATUS BADGE — PHASE 1 FOUNDATION
 * 
 * Per WORKFLOW_STUDIO_ARCHITECTURE_AUDIT.md §PHASE 1:
 * Single reusable lifecycle/status badge renderer.
 * 
 * Authority: PROJECTION_CONTINUITY_CONTRACT_V1, GUI_ARCHITECTURE.txt
 * 
 * RULES:
 * - Purely presentational — NO authority logic
 * - NO status derivation — receives status as prop
 * - NO synthesis — renders exactly what is provided
 * 
 * Previously duplicated in: WorkflowProjectionView, PlanView, DependencyView, WorkflowPanel
 */

import { STATUS_COLOR, STATUS_LABEL } from "../../constants/workflow.js";

/**
 * StatusBadge — unified lifecycle/status display component
 * 
 * @param {Object} props
 * @param {string} props.status — lifecycle status (REQUIRED)
 * @param {string} [props.size="medium"] — badge size: "small" | "medium" | "large"
 * @param {boolean} [props.showIcon=false] — whether to show status icon
 * @param {boolean} [props.showLabel=true] — whether to show status text
 * @param {string} [props.className] — additional CSS classes
 * @param {Object} [props.style] — additional inline styles
 */
export default function StatusBadge({
  status,
  size = "medium",
  showIcon = false,
  showLabel = true,
  className = "",
  style = {},
}) {
  // Guard: undefined/null status renders as "pending" fallback
  const safeStatus = status || "PENDING";
  const color = STATUS_COLOR[safeStatus] || STATUS_COLOR.PENDING;
  const labelConfig = STATUS_LABEL[safeStatus] || STATUS_LABEL.PENDING;

  const sizeClasses = {
    small: "status-badge--small",
    medium: "status-badge--medium",
    large: "status-badge--large",
  };

  const baseClasses = [
    "status-badge",
    sizeClasses[size] || sizeClasses.medium,
    className,
  ].join(" ");

  const badgeStyle = {
    background: `${color}22`,  // 13% opacity background
    color: color,
    border: `1px solid ${color}`,
    ...style,
  };

  return (
    <span className={baseClasses} style={badgeStyle}>
      {showIcon && labelConfig.icon && (
        <span className="status-badge__icon">{labelConfig.icon}</span>
      )}
      {showLabel && (
        <span className="status-badge__label">{safeStatus}</span>
      )}
    </span>
  );
}

/**
 * WorkflowStatusBadge — specialized for workflow-level lifecycle
 * Thin wrapper around StatusBadge with workflow-specific defaults.
 */
export function WorkflowStatusBadge({ status, size = "medium", className = "" }) {
  return (
    <StatusBadge
      status={status}
      size={size}
      showIcon={false}
      showLabel={true}
      className={`workflow-status-badge ${className}`}
    />
  );
}

/**
 * StepStatusBadge — specialized for step-level lifecycle
 * Includes icon by default for step visualization.
 */
export function StepStatusBadge({ status, size = "small", className = "" }) {
  return (
    <StatusBadge
      status={status}
      size={size}
      showIcon={false}
      showLabel={true}
      className={`step-status-badge ${className}`}
    />
  );
}

/**
 * ProjectionStateBadge — for projection state (non-authoritative)
 * Per CANONICAL_PROJECTION_MODEL_V1: projection_state is metadata, not authority
 */
export function ProjectionStateBadge({ state, size = "small", className = "" }) {
  // Projection states have different color semantics
  const projectionColors = {
    ACTIVE: "#3b82f6",
    TERMINAL: "#94a3b8",
    STALE: "#f97316",
    INVALIDATED: "#ef4444",
  };

  const color = projectionColors[state] || "#94a3b8";

  return (
    <span
      className={`projection-state-badge ${className}`}
      style={{
        fontSize: size === "small" ? "0.75rem" : "0.875rem",
        color: color,
        fontWeight: 500,
      }}
      title="Projection synchronization state — not lifecycle authority"
    >
      {state || "UNKNOWN"}
    </span>
  );
}
