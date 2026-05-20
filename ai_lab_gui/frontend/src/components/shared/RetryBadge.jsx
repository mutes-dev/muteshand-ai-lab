/**
 * RETRY BADGE — PHASE 1 FOUNDATION
 * 
 * Per WORKFLOW_STUDIO_ARCHITECTURE_AUDIT.md §PHASE 1:
 * Reusable retry-count display component.
 * 
 * Authority: PROJECTION_CONTINUITY_CONTRACT_V1
 * 
 * RULES:
 * - Pure presentation only — receives retry count as prop
 * - NO retry logic — NO derivation
 * - Renders null if retries is 0 or undefined
 * 
 * Previously duplicated in: WorkflowProjectionView, PlanView, WorkflowPanel
 */

import { formatRetryCount } from "../../constants/workflow.js";

/**
 * RetryBadge — unified retry count display
 * 
 * @param {Object} props
 * @param {number} props.retries — retry count (0 or undefined renders null)
 * @param {string} [props.size="small"] — badge size: "small" | "medium"
 * @param {string} [props.variant="default"] — visual style: "default" | "subtle" | "prominent"
 * @param {string} [props.className] — additional CSS classes
 */
export default function RetryBadge({
  retries,
  size = "small",
  variant = "default",
  className = "",
}) {
  // Guard: no retries means no badge
  if (!retries || retries <= 0) {
    return null;
  }

  const label = formatRetryCount(retries);

  const sizeStyles = {
    small: { fontSize: "0.75rem", padding: "0.1rem 0.3rem" },
    medium: { fontSize: "0.875rem", padding: "0.15rem 0.4rem" },
  };

  const variantStyles = {
    default: {
      background: "#f9731622",
      color: "#f97316",
      border: "1px solid #f97316",
    },
    subtle: {
      background: "transparent",
      color: "#94a3b8",
      border: "none",
    },
    prominent: {
      background: "#f97316",
      color: "#ffffff",
      border: "1px solid #f97316",
    },
  };

  const baseStyle = {
    display: "inline-flex",
    alignItems: "center",
    borderRadius: "0.25rem",
    fontWeight: 500,
    whiteSpace: "nowrap",
    ...sizeStyles[size],
    ...variantStyles[variant],
  };

  return (
    <span className={`retry-badge ${className}`} style={baseStyle}>
      <span className="retry-badge__icon" style={{ marginRight: "0.2rem" }}>
        ↩
      </span>
      <span className="retry-badge__label">{label}</span>
    </span>
  );
}

/**
 * CompactRetryIndicator — minimal inline retry display
 * For space-constrained contexts like step lists.
 */
export function CompactRetryIndicator({ retries }) {
  if (!retries || retries <= 0) {
    return null;
  }

  return (
    <span
      className="retry-indicator"
      style={{
        fontSize: "0.75rem",
        color: "#94a3b8",
        marginLeft: "0.5rem",
      }}
    >
      (retry {retries})
    </span>
  );
}
