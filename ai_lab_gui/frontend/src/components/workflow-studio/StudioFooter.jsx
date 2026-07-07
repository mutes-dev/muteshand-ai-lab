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
 * @param {number} props.activeCount — active steps (explicit count, not derived)
 * @param {string} props.workflowId — workflow identifier
 * @param {Object} [props.profileMetadata] — read-only profile metadata from projection
 * @param {Object} [props.routeMetadata] — read-only capability route metadata from projection
 */
export default function StudioFooter({
  projectionVersion,
  projectionState,
  projectionTimestamp,
  stepCount,
  completedCount,
  failedCount,
  activeCount,
  workflowId,
  profileMetadata,
  routeMetadata,
}) {
  const formatTimestamp = (ts) => {
    if (!ts) return null;
    const date = new Date(ts);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  const hasProfileInfo = profileMetadata || routeMetadata;

  return (
    <div className="studio-footer">
      {/* Left: Projection Metadata + Profile/Route Info */}
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
        {hasProfileInfo && <span className="studio-footer__divider" />}
        {profileMetadata?.selected_profile && (
          <span
            className="footer-badge footer-badge--profile"
            title={`Profile: ${profileMetadata.selected_profile}\nReason: ${profileMetadata.profile_reason_code || "—"}\nRecommended: ${profileMetadata.recommended_profile || "—"}`}
          >
            {profileMetadata.selected_profile}
          </span>
        )}
        {routeMetadata?.capability_id && (
          <span className="footer-badge footer-badge--route" title={`Capability: ${routeMetadata.capability_id}\nDecision: ${routeMetadata.route_decision || "—"}\nReason: ${routeMetadata.route_reason_code || "—"}`}>
            route: {routeMetadata.capability_id}
          </span>
        )}
        {routeMetadata?.route_decision && routeMetadata.route_decision !== "ROUTE_ACCEPTED" && (
          <span className="footer-badge footer-badge--route-fallback" title={`Fallback reason: ${routeMetadata.fallback_reason || "—"}`}>
            {routeMetadata.route_decision}
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
