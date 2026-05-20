/**
 * STUDIO FOOTER — PHASE 3 STUDIO SHELL
 *
 * Per WORKFLOW_STUDIO_PHASE3_SHELL:
 * Projection metadata and workflow statistics display.
 *
 * Authority: GUI_ARCHITECTURE.txt
 *
 * RULES:
 * - Non-authoritative metadata display only
 * - NO synthesis — renders provided projection data
 * - Observability tier per OBSERVABILITY_AND_DASHBOARD_ARCHITECTURE_CONTRACT_V1
 */

/**
 * StudioFooter — projection version, state, and step statistics
 *
 * @param {Object} props
 * @param {number} props.projectionVersion — projection_version
 * @param {string} props.projectionState — projection_state
 * @param {number} props.projectionTimestamp — projection_timestamp
 * @param {number} props.stepCount — total steps
 * @param {number} props.completedCount — completed steps
 * @param {number} props.failedCount — failed steps
 * @param {string} props.workflowId — workflow identifier
 */
export default function StudioFooter({
  projectionVersion,
  projectionState,
  projectionTimestamp,
  stepCount,
  completedCount,
  failedCount,
  workflowId,
}) {
  const formatTimestamp = (ts) => {
    if (!ts) return null;
    const date = new Date(ts * 1000);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  const activeCount = stepCount - completedCount - failedCount;

  return (
    <div className="studio-footer">
      {/* Left: Projection Metadata */}
      <div className="studio-footer__projection">
        {projectionVersion !== undefined && (
          <span className="footer-badge footer-badge--version" title="Projection version">
            v{projectionVersion}
          </span>
        )}
        {projectionState && (
          <span
            className={`footer-badge footer-badge--state footer-badge--${projectionState.toLowerCase()}`}
            title="Projection synchronization state"
          >
            {projectionState}
          </span>
        )}
        {projectionTimestamp && (
          <span className="footer-timestamp muted" title="Last updated">
            {formatTimestamp(projectionTimestamp)}
          </span>
        )}
      </div>

      {/* Center: Step Statistics */}
      <div className="studio-footer__stats">
        <span className="stat-item">
          <span className="stat-value">{stepCount}</span>
          <span className="stat-label muted">steps</span>
        </span>
        {completedCount > 0 && (
          <span className="stat-item stat-item--completed">
            <span className="stat-value">{completedCount}</span>
            <span className="stat-label muted">done</span>
          </span>
        )}
        {failedCount > 0 && (
          <span className="stat-item stat-item--failed">
            <span className="stat-value">{failedCount}</span>
            <span className="stat-label muted">failed</span>
          </span>
        )}
        {activeCount > 0 && (
          <span className="stat-item stat-item--active">
            <span className="stat-value">{activeCount}</span>
            <span className="stat-label muted">active</span>
          </span>
        )}
      </div>

      {/* Right: Workflow ID (truncated) */}
      <div className="studio-footer__id">
        <span className="muted" title={workflowId}>
          {workflowId?.slice(0, 12)}...
        </span>
      </div>
    </div>
  );
}
