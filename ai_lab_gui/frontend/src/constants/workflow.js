/**
 * WORKFLOW CONSTANTS — PHASE 1 FOUNDATION
 * 
 * Per WORKFLOW_STUDIO_ARCHITECTURE_AUDIT.md §PHASE 1:
 * Shared constants extracted from duplicated component definitions.
 * 
 * Authority: PROJECTION_CONTINUITY_CONTRACT_V1, GUI_ARCHITECTURE.txt
 * NO semantic changes — only consolidation.
 */

/**
 * Status color mapping for lifecycle states.
 * Previously duplicated in: WorkflowProjectionView, PlanView, DependencyView, WorkflowPanel, WorkflowManager
 */
export const STATUS_COLOR = {
  COMPLETED: "#22c55e",
  FAILED: "#ef4444",
  failure: "#ef4444",     // Legacy alias per WorkflowPanel
  CANCELLED: "#64748b",   // Immutable terminal — distinct gray
  BLOCKED: "#f97316",
  ACTIVE: "#3b82f6",
  PENDING: "#94a3b8",
  PAUSED: "#a78bfa",
  SKIPPED: "#64748b",
  UNKNOWN: "#64748b",     // Fallback for undefined states
};

/**
 * Risk level color mapping.
 * Previously duplicated in: PlanView
 */
export const RISK_COLOR = {
  LOW: "#22c55e",
  MEDIUM: "#f97316",
  HIGH: "#ef4444",
  CRITICAL: "#dc2626",
};

/**
 * Workflow lifecycle states per STATE_TRANSITIONS_CONTRACT_V1.
 */
export const WORKFLOW_LIFECYCLE = {
  QUEUED: "QUEUED",
  ACTIVE: "ACTIVE",
  PAUSED: "PAUSED",
  BLOCKED: "BLOCKED",
  COMPLETED: "COMPLETED",
  FAILED: "FAILED",
  CANCELLED: "CANCELLED",
};

/**
 * Step lifecycle states per STATE_TRANSITIONS_CONTRACT_V1.
 */
export const STEP_LIFECYCLE = {
  PENDING: "PENDING",
  ACTIVE: "ACTIVE",
  COMPLETED: "COMPLETED",
  FAILED: "FAILED",
  BLOCKED: "BLOCKED",
  CANCELLED: "CANCELLED",
};

/**
 * Projection states per CANONICAL_PROJECTION_MODEL_V1.
 */
export const PROJECTION_STATE = {
  ACTIVE: "ACTIVE",
  STALE: "STALE",
  INVALIDATED: "INVALIDATED",
  TERMINAL: "TERMINAL",
};

/**
 * Status label configurations for display.
 * Maps status to human-readable label with icon.
 */
export const STATUS_LABEL = {
  [WORKFLOW_LIFECYCLE.QUEUED]: { label: "Queued", icon: "◌" },
  [WORKFLOW_LIFECYCLE.ACTIVE]: { label: "Running", icon: "▶" },
  [WORKFLOW_LIFECYCLE.PAUSED]: { label: "Paused", icon: "⏸" },
  [WORKFLOW_LIFECYCLE.BLOCKED]: { label: "Blocked", icon: "⊘" },
  [WORKFLOW_LIFECYCLE.COMPLETED]: { label: "Completed", icon: "✓" },
  [WORKFLOW_LIFECYCLE.FAILED]: { label: "Failed", icon: "✕" },
  [WORKFLOW_LIFECYCLE.CANCELLED]: { label: "Cancelled", icon: "⏹" },
  // Step statuses (overlap with workflow)
  [STEP_LIFECYCLE.PENDING]: { label: "Pending", icon: "◌" },
  [STEP_LIFECYCLE.ACTIVE]: { label: "Active", icon: "▶" },
  [STEP_LIFECYCLE.COMPLETED]: { label: "Completed", icon: "✓" },
  [STEP_LIFECYCLE.FAILED]: { label: "Failed", icon: "✕" },
  [STEP_LIFECYCLE.BLOCKED]: { label: "Blocked", icon: "⊘" },
  [STEP_LIFECYCLE.CANCELLED]: { label: "Cancelled", icon: "⏹" },
};

/**
 * Recoverable terminal states per MUTATION_LEGALITY_AND_RUNTIME_ISOLATION_CONTRACT_V1.
 * These states MAY support retry and reconciliation.
 */
export const RECOVERABLE_TERMINAL_STATES = [
  WORKFLOW_LIFECYCLE.FAILED,
];

/**
 * Immutable terminal states per MUTATION_LEGALITY_AND_RUNTIME_ISOLATION_CONTRACT_V1.
 * These states do NOT support retry, continuation, or structural mutation.
 */
export const IMMUTABLE_TERMINAL_STATES = [
  WORKFLOW_LIFECYCLE.COMPLETED,
  WORKFLOW_LIFECYCLE.CANCELLED,
];

/**
 * Projection state label configurations.
 * Non-authoritative observability metadata.
 */
export const PROJECTION_STATE_LABEL = {
  [PROJECTION_STATE.ACTIVE]: { label: "ACTIVE", color: "#3b82f6" },
  [PROJECTION_STATE.TERMINAL]: { label: "TERMINAL", color: "#94a3b8" },
  [PROJECTION_STATE.STALE]: { label: "STALE", color: "#f97316" },
  [PROJECTION_STATE.INVALIDATED]: { label: "INVALIDATED", color: "#ef4444" },
};

/**
 * Format a retry count for display.
 * Pure presentation helper — no authority logic.
 * @param {number} retries — retry count
 * @returns {string | null} formatted retry label or null if no retries
 */
export function formatRetryCount(retries) {
  if (!retries || retries <= 0) return null;
  if (retries === 1) return "1 attempt";
  return `${retries} attempts`;
}

/**
 * Format a step number with ordinal suffix.
 * Pure presentation helper.
 * @param {number} index — zero-based index
 * @returns {string} formatted step number (1-based)
 */
export function formatStepNumber(index) {
  return `${index + 1}`;
}

/**
 * Get CSS class suffix for status.
 * Used for styling hooks without inline colors.
 * @param {string} status — lifecycle status
 * @returns {string} CSS-safe class suffix
 */
export function getStatusClassSuffix(status) {
  if (!status) return "pending";
  return status.toLowerCase().replace(/[^a-z0-9]/g, "-");
}

/**
 * Check if status is terminal (any terminal: recoverable or immutable).
 * Per STATE_TRANSITIONS_CONTRACT_V1 §TERMINALITY RULES.
 * @param {string} status — lifecycle status
 * @returns {boolean} true if COMPLETED, FAILED, or CANCELLED
 */
export function isTerminalStatus(status) {
  return status === WORKFLOW_LIFECYCLE.COMPLETED
    || status === WORKFLOW_LIFECYCLE.FAILED
    || status === WORKFLOW_LIFECYCLE.CANCELLED;
}

/**
 * Check if status is a recoverable terminal state.
 * Per MUTATION_LEGALITY_AND_RUNTIME_ISOLATION_CONTRACT_V1 §RECOVERABLE TERMINAL MUTATION LEGALITY.
 * FAILED is recoverable — MAY support retry and reconciliation.
 * @param {string} status — lifecycle status
 * @returns {boolean} true if FAILED
 */
export function isRecoverableTerminal(status) {
  return RECOVERABLE_TERMINAL_STATES.includes(status);
}

/**
 * Check if status is an immutable terminal state.
 * Per MUTATION_LEGALITY_AND_RUNTIME_ISOLATION_CONTRACT_V1 §TERMINAL STATE IMMUTABILITY.
 * COMPLETED and CANCELLED are immutable — do NOT support retry or continuation.
 * @param {string} status — lifecycle status
 * @returns {boolean} true if COMPLETED or CANCELLED
 */
export function isImmutableTerminal(status) {
  return IMMUTABLE_TERMINAL_STATES.includes(status);
}

/**
 * Check if status is active/non-terminal.
 * @param {string} status — lifecycle status
 * @returns {boolean} true if not terminal
 */
export function isActiveStatus(status) {
  return !isTerminalStatus(status);
}
