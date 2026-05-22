/**
 * WORKFLOW PROJECTION VIEW — PHASE 4B.0
 *
 * Per CANONICAL_PROJECTION_MODEL_V1:
 * - Renders ONLY from canonical WorkflowProjection
 * - Projection originates from orchestrator; GUI renders, does NOT define
 * - GUI MUST NOT synthesize workflow state or lifecycle state
 * - GUI MUST remain projection-render-only
 *
 * Per PROJECTION_CONTINUITY_CONTRACT_V1:
 * - Stale projection replacement is rejected via projection_version guard
 * - Terminal projections remain stable
 * - Workflow-scoped rendering isolation enforced
 *
 * Per GUI_ARCHITECTURE.txt:
 * - GUI consumes synchronized projections rather than synthesizing state locally
 * - Rendering MUST originate from canonical projections rather than local synthesized state
 *
 * PROHIBITED:
 * - No lifecycle synthesis
 * - No workflow truth synthesis
 * - No mutation handlers
 * - No optimistic updates
 * - No local dependency reconstruction
 */

import { useState, useEffect, useRef } from "react";
import { api } from "../api.js";
import { STATUS_COLOR } from "../constants/workflow.js";
import WorkflowStudio from "./workflow-studio/WorkflowStudio.jsx";
import PlanView from "./PlanView.jsx";
import PlanMutationPanel from "./PlanMutationPanel.jsx";

const PROJECTION_POLL_MS = 1000;
// Consecutive projection 404s before declaring this workflow orphaned and calling onOrphan().
// At PROJECTION_POLL_MS=1000ms this means ~3 seconds of sustained absence.
const PROJECTION_ORPHAN_THRESHOLD = 3;

const STATE_LABEL = {
  ACTIVE: { label: "ACTIVE", color: "#3b82f6" },
  TERMINAL: { label: "TERMINAL", color: "#94a3b8" },
  STALE: { label: "STALE", color: "#f97316" },
  INVALIDATED: { label: "INVALIDATED", color: "#ef4444" },
};

/**
 * WorkflowProjectionView
 *
 * Renders a canonical WorkflowProjection polled from /projection/{workflowId}.
 *
 * Props:
 *   workflowId  — active workflow identifier (from backend projection)
 *   isExecuting — whether workflow is currently executing
 *   showPlanView — whether to show the canonical plan view
 *
 * Per SUB-PHASE 3D: switches rendering context on workflowId change
 * with clean projection boundary (no stale carryover).
 */
export default function WorkflowProjectionView({ workflowId, isExecuting, showPlanView = false, onOrphan = null }) {
  // Per CANONICAL_PROJECTION_MODEL_V1 §3: projection identity fields drive render
  const [projection, setProjection] = useState(null);
  const [projectionError, setProjectionError] = useState(null);

  // === PHASE XV-B TRACE LOGGING ===
  console.log("[PROJECTION_BIND]", {
    workflow_id: workflowId,
    timestamp: Date.now(),
  });

  // SUB-PHASE 3E: projection version guard — reject stale updates
  const lastProjectionVersionRef = useRef(0);

  // SUB-PHASE 3D: active workflow ID ref for isolation guard
  const activeWorkflowIdRef = useRef(null);

  const pollRef = useRef(null);

  // Consecutive 404 counter — triggers onOrphan() after threshold
  const consecutive404Ref = useRef(0);

  function stopPoll(reason = "unknown") {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
      console.log("[GUI:PROJECTION_POLL_STOP]", {
        workflowId,
        reason,
        timestamp: Date.now()
      });
    }
  }

  function applyProjection(incoming, sourceWorkflowId) {
    // SUB-PHASE 3D: Workflow isolation guard
    // Reject in-flight fetch results from a previous workflow
    if (sourceWorkflowId !== activeWorkflowIdRef.current) {
      console.log("[GUI:PROJECTION_ISOLATION_REJECT]", {
        staleWorkflowId: sourceWorkflowId,
        activeWorkflowId: activeWorkflowIdRef.current,
        reason: "workflow_switched_during_fetch",
        timestamp: Date.now()
      });
      return;
    }

    // SUB-PHASE 3E: Stale projection rejection
    // Per PROJECTION_CONTINUITY_CONTRACT_V1 §6: late projections MUST NOT overwrite newer
    const incomingVersion = incoming?.projection_version ?? 0;
    if (incomingVersion < lastProjectionVersionRef.current) {
      console.log("[GUI:PROJECTION_STALE_REJECT]", {
        workflowId: sourceWorkflowId,
        incomingVersion,
        currentVersion: lastProjectionVersionRef.current,
        reason: "stale_projection_version",
        timestamp: Date.now()
      });
      return;
    }

    // SUB-PHASE 3E: Terminal projection stability
    // Per CANONICAL_PROJECTION_MODEL_V1 §14 + PROJECTION_CONTINUITY_CONTRACT_V1 §9:
    // IMMUTABLE terminal projections (COMPLETED, CANCELLED) MUST NOT be replaced by non-terminal.
    // RECOVERABLE terminals (FAILED) MAY transition to non-terminal via retry.
    const currentState = projection?.projection_state;
    const incomingState = incoming?.projection_state;
    const currentLifecycle = projection?.lifecycle_status;
    const isImmutable = currentLifecycle === "COMPLETED" || currentLifecycle === "CANCELLED";
    if (currentState === "TERMINAL" && incomingState !== "TERMINAL" && isImmutable) {
      console.log("[GUI:PROJECTION_TERMINAL_STABLE]", {
        workflowId: sourceWorkflowId,
        currentState,
        incomingState,
        lifecycleStatus: currentLifecycle,
        reason: "terminal_projection_immutable_protected",
        timestamp: Date.now()
      });
      return;
    }

    lastProjectionVersionRef.current = incomingVersion;
    setProjection(incoming);
    setProjectionError(null);

    console.log("[GUI:PROJECTION_RENDER_UPDATE]", {
      workflowId: sourceWorkflowId,
      projectionVersion: incomingVersion,
      projectionState: incomingState,
      lifecycleStatus: incoming?.lifecycle_status,
      stepCount: incoming?.step_count ?? 0,
      timestamp: Date.now()
    });
  }

  // SUB-PHASE 3B+3E: Hydration on reconnect
  // Per PROJECTION_CONTINUITY_CONTRACT_V1 §4: reconstruct latest valid projection on reconnect
  async function fetchProjection(wfId) {
    // === PHASE XV-B TRACE LOGGING ===
    console.log("[PROJECTION_FETCH]", {
      workflow_id: wfId,
      timestamp: Date.now(),
    });
    try {
      const p = await api.getProjection(wfId);
      // Successful fetch — reset orphan counter
      consecutive404Ref.current = 0;
      // === PHASE XV-B TRACE LOGGING ===
      console.log("[PROJECTION_RESULT]", {
        workflow_id: wfId,
        found: true,
        version: p?.projection_version,
        timestamp: Date.now(),
      });
      applyProjection(p, wfId);
    } catch (err) {
      const is404 = err?.message && (
        err.message.includes("404") ||
        err.message.includes("Not Found") ||
        err.message.includes("workflow not found")
      );
      if (is404) {
        consecutive404Ref.current += 1;
        console.log("[GUI:PROJECTION_404]", {
          workflowId: wfId,
          consecutiveCount: consecutive404Ref.current,
          threshold: PROJECTION_ORPHAN_THRESHOLD,
          timestamp: Date.now(),
        });
        // Before projection has ever been emitted, 404 is normal (workflow mid-planning).
        // Per PROJECTION_CONTINUITY_CONTRACT_V1 §308-319: temporary projection absence
        // during planning/convergence is legal. Only declare orphan if we HAD a
        // projection and it disappeared — indicating actual backend deletion.
        // === PHASE XV-B TRACE LOGGING ===
        console.log("[PROJECTION_RESULT]", {
          workflow_id: wfId,
          found: false,
          consecutive404: consecutive404Ref.current,
          timestamp: Date.now(),
        });
        if (consecutive404Ref.current >= PROJECTION_ORPHAN_THRESHOLD) {
          // FALSE ORPHAN GUARD:
          // If no projection has ever been received, the 404 is legal convergence lag
          // or planning-stage absence. Do NOT derive lifecycle death from projection
          // absence (per CANONICAL_PROJECTION_MODEL_V1 §132 + PROJECTION_CONTINUITY_CONTRACT_V1).
          if (projection === null) {
            return;
          }
          stopPoll("orphan_threshold_reached");
          setProjectionError("orphaned");
          console.log("[GUI:PROJECTION_ORPHAN_DETECTED]", {
            workflowId: wfId,
            consecutiveCount: consecutive404Ref.current,
            reason: "persistent_404_on_projection",
            timestamp: Date.now(),
          });
          if (onOrphan) onOrphan(`projection_consecutive_404:${consecutive404Ref.current}`);
        }
        return;
      }
      // Non-404 error (network flap) — set error but do not orphan
      consecutive404Ref.current = 0;
      setProjectionError("projection_fetch_error");
    }
  }

  // SUB-PHASE 3D: Workflow switching — clean projection boundary
  // Per PROJECTION_CONTINUITY_CONTRACT_V1 §12: continuity MUST remain isolated per workflow_id
  useEffect(() => {
    stopPoll("workflow_id_changed");

    // Clean projection boundary when switching workflows
    const prevId = activeWorkflowIdRef.current;
    if (workflowId !== prevId) {
      console.log("[GUI:PROJECTION_BOUNDARY_RESET]", {
        previousWorkflowId: prevId,
        newWorkflowId: workflowId,
        reason: "workflow_id_transition",
        timestamp: Date.now()
      });
      // SUB-PHASE 3D: Do NOT carry stale projection across workflow switch
      setProjection(null);
      setProjectionError(null);
      lastProjectionVersionRef.current = 0;
      consecutive404Ref.current = 0;
    }

    activeWorkflowIdRef.current = workflowId;

    if (!workflowId) return;

    // Initial projection hydration on workflow attach
    fetchProjection(workflowId);

    // Poll for projection updates while active
    pollRef.current = setInterval(() => {
      fetchProjection(workflowId);
    }, PROJECTION_POLL_MS);

    return () => stopPoll("effect_cleanup");
  }, [workflowId]);

  // Terminal shutdown: stop polling for immutable terminals only.
  // Keep polling for FAILED (recoverable) — retry may update projection.
  const projState = projection?.projection_state;
  const lifecycleStatus = projection?.lifecycle_status;
  useEffect(() => {
    if (projState === "TERMINAL") {
      const isImmutable = lifecycleStatus === "COMPLETED" || lifecycleStatus === "CANCELLED";
      if (isImmutable) {
        console.log("[GUI:PROJECTION_TERMINAL_SHUTDOWN]", {
          workflowId,
          projectionState: projState,
          lifecycleStatus,
          projectionVersion: projection?.projection_version,
          reason: "terminal_projection_immutable_stop_poll",
          timestamp: Date.now()
        });
        stopPoll("terminal_projection_immutable");
      } else {
        console.log("[GUI:PROJECTION_RECOVERABLE_CONTINUE]", {
          workflowId,
          projectionState: projState,
          lifecycleStatus,
          reason: "recoverable_terminal_keep_polling",
          timestamp: Date.now()
        });
      }
    }
  }, [projState]);

  // Render
  if (!workflowId) {
    return (
      <section className="panel workflow-projection-panel">
        <h2>Workflow Projection</h2>
        <p className="muted">No active workflow.</p>
      </section>
    );
  }

  if (projectionError) {
    const isOrphan = projectionError === "orphaned";
    return (
      <section className="panel workflow-projection-panel">
        <h2>Workflow Projection</h2>
        <p className="muted">
          {isOrphan
            ? "Workflow no longer exists on backend — state cleared."
            : projectionError}
        </p>
      </section>
    );
  }

  if (!projection) {
    return (
      <section className="panel workflow-projection-panel">
        <h2>Workflow Projection</h2>
        <p className="muted">{isExecuting ? "Awaiting first projection…" : "No projection available."}</p>
      </section>
    );
  }

  const {
    workflow_id,
    projection_version,
    projection_timestamp,
    projection_state,
    lifecycle_status,
    workflow_name,
    steps = [],
    outputs = [],
    step_count,
  } = projection;

  // === PHASE 3: Workflow Studio Shell Integration ===
  // WorkflowProjectionView retains projection polling authority
  // WorkflowStudio provides unified presentation shell

  const handleMutationIntent = async (intent) => {
    if (!intent?.workflowId) {
      throw new Error("Mutation intent missing workflowId");
    }

    console.log("[WorkflowProjectionView] Mutation intent:", intent);

    // Transform frontend intent to backend mutation payload
    let payload;
    if (intent.type === "edit_step") {
      payload = { step_id: intent.stepId, updates: intent.payload };
    } else if (intent.type === "retry_step") {
      payload = { step_id: intent.stepId };
    } else {
      payload = intent.payload;
    }

    const result = await api.requestMutation(intent.workflowId, intent.type, payload);

    // Force authoritative projection refresh after mutation
    // Per CANONICAL_PROJECTION_MODEL_V1 §8: projection changes occur through
    // intent → validation → runtime update → projection regeneration → re-emission → re-render
    await fetchProjection(intent.workflowId);

    return result;
  };

  return (
    <section className="panel workflow-projection-panel">
      <WorkflowStudio
        projection={projection}
        workflowId={workflowId}
        isExecuting={isExecuting}
        onMutationIntent={handleMutationIntent}
        onProjectionRefresh={() => fetchProjection(workflow_id)}
        initialMode="plan"
      />
    </section>
  );
}
