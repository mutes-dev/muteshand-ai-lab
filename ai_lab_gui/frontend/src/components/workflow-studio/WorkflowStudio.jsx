/**
 * WORKFLOW STUDIO — PHASE 3 STUDIO SHELL
 *
 * Per WORKFLOW_STUDIO_PHASE3_SHELL:
 * Container shell for unified workflow projection workspace.
 *
 * Authority: GUI_ARCHITECTURE.txt, CANONICAL_PROJECTION_MODEL_V1
 *
 * RESPONSIBILITIES:
 * - Container shell layout
 * - Mode state management (UI-only)
 * - Projection presentation orchestration
 * - Toolbar/Footer coordination
 *
 * NOT RESPONSIBLE FOR:
 * - Authority ownership (projection comes from parent)
 * - Polling ownership (polling happens in WorkflowProjectionView)
 * - Orchestration (mutation intents dispatched to parent)
 *
 * Architecture: WorkflowProjectionView → WorkflowStudio → Mode → Existing Components
 */

import { useState, useEffect } from "react";
import { api } from "../../api.js";
import StudioToolbar from "./StudioToolbar.jsx";
import StudioFooter from "./StudioFooter.jsx";
import OverviewMode from "./modes/OverviewMode.jsx";
import PlanMode from "./modes/PlanMode.jsx";
import DependenciesMode from "./modes/DependenciesMode.jsx";
import EditMode from "./modes/EditMode.jsx";
import ChronologyPanel from "../shared/ChronologyPanel.jsx";

const MODES = {
  OVERVIEW: "overview",
  PLAN: "plan",
  DEPENDENCIES: "dependencies",
  EDIT: "edit",
};

/**
 * WorkflowStudio — unified projection workspace container
 *
 * @param {Object} props
 * @param {Object} props.projection — canonical WorkflowProjection
 * @param {string} props.workflowId — current workflow_id
 * @param {boolean} props.isExecuting — execution state (for edit lockout)
 * @param {Function} props.onMutationIntent — mutation intent dispatcher
 * @param {Function} props.onProjectionRefresh — manual refresh request
 * @param {string} [props.initialMode] — starting mode
 */
export default function WorkflowStudio({
  projection,
  workflowId,
  isExecuting,
  onMutationIntent,
  onProjectionRefresh,
  initialMode = MODES.PLAN,
}) {
  // UI-only mode state — NO authority, NO projection impact
  const [activeMode, setActiveMode] = useState(initialMode);

  // Mode switching is pure UI — no workflow reload, no projection invalidation
  const handleModeChange = (mode) => {
    if (mode === activeMode) return;
    setActiveMode(mode);
  };

  // Per WORKFLOWSTUDIO TIMELINE SIDEBAR:
  // Chronology sidebar toggle — observability-only, closed by default
  const [showChronology, setShowChronology] = useState(false);

  // Event polling for chronology sidebar — observational only, no authority
  const [events, setEvents] = useState([]);
  useEffect(() => {
    if (!workflowId) return;
    // Per REPLAY_QUERY_PAGINATION:
    // Mutable state object ensures async poll callbacks see latest values.
    // latestBusSeq is the authoritative monotonic cursor (bus_sequence_id).
    const state = { latestBusSeq: 0 };
    let cancelled = false;

    const fetchEvents = async () => {
      try {
        // Per REPLAY_QUERY_PAGINATION:
        // Use since_sequence (bus_sequence_id) as the authoritative cursor.
        // -1 on initial load; latestBusSeq on incremental polls.
        const sinceSeq = state.latestBusSeq > 0 ? state.latestBusSeq : -1;
        const data = await api.getEvents(workflowId, -1, sinceSeq, 100);
        if (cancelled || !data?.events) return;

        // Continuity validation on incremental polls
        if (
          sinceSeq >= 0 &&
          state.latestBusSeq > 0 &&
          data.events.length > 0
        ) {
          const firstNewSeq = data.events[0].bus_sequence_id || 0;
          const expectedSeq = state.latestBusSeq + 1;
          if (firstNewSeq > expectedSeq) {
            // Gap detected — safe full rehydrate from backend authority
            const fullData = await api.getEvents(workflowId, -1, -1, 100);
            if (!cancelled && fullData?.events) {
              setEvents(fullData.events);
              state.latestBusSeq = fullData.latest_bus_sequence_id;
            }
            return;
          }
        }

        // Append-only merge: deduplicate by bus_sequence_id, preserve ordering
        if (data.events.length > 0) {
          setEvents((prev) => {
            const existingSeqs = new Set(prev.map((e) => e.bus_sequence_id));
            const newEvents = data.events.filter(
              (e) => !existingSeqs.has(e.bus_sequence_id)
            );
            if (newEvents.length === 0) return prev;
            const merged = [...prev, ...newEvents];
            merged.sort(
              (a, b) => (a.bus_sequence_id || 0) - (b.bus_sequence_id || 0)
            );
            return merged;
          });
          state.latestBusSeq = data.latest_bus_sequence_id;
        }
      } catch {
        // Silently ignore — chronology is advisory only
      }
    };

    fetchEvents();
    const interval = setInterval(fetchEvents, 500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [workflowId]);

  if (!projection) {
    return (
      <div className="workflow-studio workflow-studio--empty">
        <div className="studio-placeholder muted">
          No projection data available.
        </div>
      </div>
    );
  }

  const {
    workflow_id,
    workflow_name,
    lifecycle_status,
    projection_version,
    projection_state,
    projection_timestamp,
    steps = [],
    outputs = [],
    step_count,
  } = projection;

  // Toolbar configuration
  const toolbarProps = {
    workflowId: workflow_id || workflowId,
    workflowName: workflow_name,
    lifecycleStatus: lifecycle_status,
    projectionVersion: projection_version,
    projectionState: projection_state,
    activeMode,
    availableModes: Object.values(MODES),
    onModeChange: handleModeChange,
    onRefresh: onProjectionRefresh,
    showChronology,
    onToggleChronology: () => setShowChronology((s) => !s),
  };

  // Footer configuration
  const footerProps = {
    projectionVersion: projection_version,
    projectionState: projection_state,
    projectionTimestamp: projection_timestamp,
    stepCount: step_count ?? steps.length,
    completedCount: steps.filter((s) => s.status === "COMPLETED").length,
    failedCount: steps.filter((s) => s.status === "FAILED").length,
    workflowId: workflow_id || workflowId,
  };

  // Mode content props
  const modeProps = {
    projection,
    steps,
    outputs,
    workflowId: workflow_id || workflowId,
    isExecuting,
    onMutationIntent,
    lifecycleStatus: lifecycle_status,
  };

  return (
    <div className="workflow-studio">
      {/* Studio Toolbar — identity, lifecycle, mode navigation */}
      <StudioToolbar {...toolbarProps} />

      {/* Mode Content Area — horizontal split with optional chronology sidebar */}
      <div className={`workflow-studio__content${showChronology ? " workflow-studio__content--with-sidebar" : ""}`}>
        <div className="workflow-studio__main">
          {activeMode === MODES.OVERVIEW && <OverviewMode {...modeProps} />}
          {activeMode === MODES.PLAN && <PlanMode {...modeProps} />}
          {activeMode === MODES.DEPENDENCIES && <DependenciesMode {...modeProps} />}
          {activeMode === MODES.EDIT && (
            <EditMode {...modeProps} disabled={isExecuting} />
          )}
        </div>
        {showChronology && (
          <div className="chronology-sidebar">
            <ChronologyPanel
              events={events}
              steps={steps}
              executionGeneration={projection?.execution_generation}
              onClose={() => setShowChronology(false)}
            />
          </div>
        )}
      </div>

      {/* Studio Footer — projection metadata */}
      <StudioFooter {...footerProps} />
    </div>
  );
}

// Export mode constants for external use
export { MODES };
