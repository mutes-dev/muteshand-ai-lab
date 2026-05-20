/**
 * GLOBAL RUNTIME STATUS — PHASE 4G-A.6
 *
 * Per OBSERVABILITY_AND_DASHBOARD_ARCHITECTURE_CONTRACT_V1:
 * - Single authoritative operator observability surface
 * - Renders backend-authoritative runtime_activity ONLY
 * - NOT projection metadata, NOT lifecycle authority
 *
 * Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
 * - runtime_activity is backend-owned transient observability
 * - Frontend is passive observer only
 *
 * Placement: near chat/operator interaction surface (global, not projection-scoped)
 *
 * PROHIBITED:
 * - No frontend synthesis
 * - No optimistic UI
 * - No local timers
 * - No lifecycle authority rendering
 */

const ACTIVITY_LABEL = {
  BOOTSTRAPPING: "⚙ Bootstrapping…",
  PLANNING: "📝 Planning…",
  REGISTERING: "🔗 Registering…",
  EXECUTING: "⚡ Executing…",
  RESOLVING: "🔧 Resolving…",
  PAUSING: "⏸ Pausing…",
  PAUSED: "⏸ Paused",
  RESUMING: "▶ Resuming…",
  IDLE: "● Idle",
};

const ACTIVITY_COLOR = {
  BOOTSTRAPPING: "#94a3b8",
  PLANNING: "#3b82f6",
  REGISTERING: "#8b5cf6",
  EXECUTING: "#22c55e",
  RESOLVING: "#f59e0b",
  PAUSING: "#f97316",
  PAUSED: "#a78bfa",
  RESUMING: "#3b82f6",
  IDLE: "#94a3b8",
};

export default function GlobalRuntimeStatus({ runtimeActivity }) {
  // No synthesis: if backend has not emitted runtime_activity yet, render nothing.
  // This avoids fake frontend loading states.
  if (!runtimeActivity || runtimeActivity === "IDLE") {
    return null;
  }

  const label = ACTIVITY_LABEL[runtimeActivity] || runtimeActivity;
  const color = ACTIVITY_COLOR[runtimeActivity] || "#94a3b8";

  return (
    <div
      className="global-runtime-status"
      role="status"
      aria-live="polite"
      style={{
        padding: "6px 12px",
        borderRadius: "6px",
        background: `${color}15`,
        color,
        border: `1px solid ${color}40`,
        fontSize: "0.85rem",
        fontWeight: 500,
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        animation: "fadeIn 200ms ease-out",
      }}
    >
      <span
        className="runtime-pulse"
        style={{
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          background: color,
          display: "inline-block",
          animation: "pulse 1.5s infinite",
        }}
        aria-hidden="true"
      />
      <span>{label}</span>
    </div>
  );
}
