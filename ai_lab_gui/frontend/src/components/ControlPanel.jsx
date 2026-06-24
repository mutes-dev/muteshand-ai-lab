import { useState, useEffect } from "react";
import { api } from "../api.js";
import { log } from "../utils/log.js";
import { isRecoverableTerminal, WORKFLOW_LIFECYCLE } from "../constants/workflow.js";
import DangerConfirmModal from "./DangerConfirmModal.jsx";

// Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
// Frontend does NOT synthesize workflow ownership
// Backend provides authoritative workflow identity via projection

export default function ControlPanel({
  onBackgroundStart,
  onResumeStreamStart,
  onPause,
  onForceProjectionRefresh,
  onWorkflowCancelled,
  workflowId,
  status,
  pendingReattach,
  // === ISSUE-062: Backend-authored FAILED actionability metadata ===
  retryEligible,
  failedRecoverable,
  retryDisabledReason,
  // === ISSUE-092B: Step IDs for retry button visibility ===
  retryTargetStepId,
  failedStepId,
  // === ISSUE-098A: Force retry candidate metadata ===
  forceRetryCandidate,
  forceRetryRemaining,
  forceRetryDisabledReason,
}) {
  const [bgInput, setBgInput] = useState("");
  const [error, setError] = useState(null);
  const [cancelling, setCancelling] = useState(false);
  const [cancelModalOpen, setCancelModalOpen] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [forceRetrying, setForceRetrying] = useState(false);
  const [forceRetryModalOpen, setForceRetryModalOpen] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [resuming, setResuming] = useState(false);

  async function act(fn) {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handlePause() {
    setError(null);
    // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
    // workflowId is derived from backend projection, not synthesized locally
    console.log("[GUI:PAUSE_CLICK]", {
      workflowId,
      timestamp: Date.now()
    });
    log("PAUSE_CLICK", { workflowId });
    if (status !== "ACTIVE") {
      setError(`Pause not available when workflow is ${status ? status.toLowerCase() : "unknown"}.`);
      return;
    }
    setPausing(true);
    try {
      // Sprint 9C-4B: Try WebSocket first, fall back to HTTP
      const wsResult = await api.wsCommand.send(workflowId, "pause", {});
      if (wsResult.usedWebSocket && wsResult.ack?.status === "accepted") {
        log("PAUSE_WS_ACK", wsResult.ack);
        // Ack is NOT lifecycle truth. Wait for projection/events to update UI.
        if (onPause) onPause("pause");
        if (onForceProjectionRefresh) onForceProjectionRefresh();
        return;
      }
      if (wsResult.usedWebSocket) {
        log("PAUSE_WS_FALLBACK", { reason: wsResult.ack?.status || wsResult.timedOut || "unknown" });
      }
      const res = await api.pause(workflowId);
      log("PAUSE_RESPONSE", res);
      // Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1:
      // PAUSED workflows do not retain active execution context.
      // Stream polling must stop to prevent 404 orphan invalidation.
      if (res?.success && onPause) {
        onPause("pause");
      }
      if (res?.success && onForceProjectionRefresh) {
        onForceProjectionRefresh();
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setPausing(false);
    }
  }

  async function handleResume() {
    setError(null);
    // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
    // workflowId is derived from backend projection, not synthesized locally
    console.log("[GUI:RESUME_CLICK]", {
      workflowId,
      timestamp: Date.now()
    });
    log("RESUME_CLICK", { workflowId });
    const RESUMABLE_STATUSES = new Set(["PAUSED", "PENDING_RECOVERY", "BLOCKED"]);
    if (!RESUMABLE_STATUSES.has(status)) {
      setError(`Resume not available when workflow is ${status ? status.toLowerCase() : "unknown"}.`);
      return;
    }
    setResuming(true);
    try {
      // Sprint 9C-4B: Try WebSocket first, fall back to HTTP
      const wsResult = await api.wsCommand.send(workflowId, "resume", {});
      if (wsResult.usedWebSocket && wsResult.ack?.status === "accepted") {
        log("RESUME_WS_ACK", wsResult.ack);
        // Ack is NOT lifecycle truth. Wait for projection/events to update UI.
        // WebSocket resume ack may include bg_id for stream continuity.
        if (wsResult.ack?.payload?.bg_id && onResumeStreamStart) {
          onResumeStreamStart(wsResult.ack.payload.bg_id);
        }
        if (onForceProjectionRefresh) onForceProjectionRefresh();
        return;
      }
      if (wsResult.usedWebSocket) {
        log("RESUME_WS_FALLBACK", { reason: wsResult.ack?.status || wsResult.timedOut || "unknown" });
      }
      const res = await api.resume(workflowId);
      log("RESUME_RESPONSE", res);
      // Start streaming for the new bg_id returned by resume
      if (res.bg_id && onResumeStreamStart) {
        onResumeStreamStart(res.bg_id);
      }
      if (res?.success && onForceProjectionRefresh) {
        onForceProjectionRefresh();
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setResuming(false);
    }
  }

  async function handleRetry() {
    // Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1:
    // Retry creates a NEW execution instance with fresh isolation boundaries.
    // Frontend sends mutation intent only — backend validates and orchestrates.
    // Per ISSUE-057 CONTRACT AUDIT:
    // Frontend MUST NOT synthesize retry legality or infer retry target from visible step statuses.
    // Frontend MUST consume authoritative retry_target_step_id from backend projection.
    console.log("[GUI:RETRY_CLICK]", {
      workflowId,
      status,
      timestamp: Date.now()
    });
    log("RETRY_CLICK", { workflowId });
    setRetrying(true);
    try {
      // Fetch authoritative projection to identify retry target.
      // Per CANONICAL_PROJECTION_MODEL_V1: projection is authoritative, not synthesized.
      const proj = await api.getProjection(workflowId);

      // === ISSUE-057 FIX E: Consume authoritative retry_target_step_id ===
      // Backend decides retry target. Frontend must NOT guess.
      let targetStepId = proj?.retry_target_step_id || null;

      // Fallback: if no retry_target_step_id, search for FAILED step only (backward compatibility)
      // Per CONTRACT AUDIT: do NOT broaden search to BLOCKED steps.
      if (!targetStepId) {
        const steps = proj?.steps || [];
        const failedStep = steps.find((s) => s.status === "FAILED");
        if (failedStep) {
          targetStepId = failedStep.step_id;
        }
      }

      if (!targetStepId) {
        setError("No authoritative retry target available.");
        return;
      }

      log("RETRY_STEP_IDENTIFIED", { workflowId, stepId: targetStepId });
      const res = await api.requestMutation(
        workflowId,
        "retry_step",
        { step_id: targetStepId },
        "user"
      );
      log("RETRY_RESPONSE", res);
      // Defensive: surface embedded failure status even if HTTP 200
      if (res?.status === "failure") {
        setError(res.reason || "Mutation rejected by orchestrator");
        return;
      }
      // === ISSUE-074C-FIX: Restart stream polling after retry so lastResult updates ===
      // Backend mutation endpoint returns bg_id when execution is resurrected.
      // Without this, the stream stays stopped (terminal workflow shut it down)
      // and lastResult never refreshes — ExecutionPanel remains stale FAILED.
      if (res?.bg_id && onResumeStreamStart) {
        onResumeStreamStart(res.bg_id);
      }
      if (onForceProjectionRefresh) {
        onForceProjectionRefresh();
      }
      return res;
    } catch (e) {
      setError(e.message);
    } finally {
      setRetrying(false);
    }
  }

  async function handleForceRetry() {
    // Per USER_CONTROL_CONTRACT_V2 §23:
    // Force retry is a bounded, operator-initiated action with explicit confirmation.
    // Frontend sends intent only; backend validates candidate conditions and budget.
    console.log("[GUI:FORCE_RETRY_CLICK]", {
      workflowId,
      status,
      timestamp: Date.now()
    });
    log("FORCE_RETRY_CLICK", { workflowId });
    setForceRetrying(true);
    try {
      const targetStepId = retryTargetStepId;
      if (!targetStepId) {
        setError("No authoritative retry target available for force retry.");
        return;
      }
      const res = await api.forceStepRetry(workflowId, targetStepId);
      log("FORCE_RETRY_RESPONSE", res);
      if (res?.status !== "ok") {
        setError(res?.detail || "Force retry rejected by backend");
        return;
      }
      // === ISSUE-098A: Start stream polling for resurrected execution ===
      // Backend returns dispatch.bg_id when execution is resurrected.
      // Without this, the stream remains stopped (terminal workflow shut it down)
      // and the GUI never receives live execution updates.
      if (res?.dispatch?.bg_id && onResumeStreamStart) {
        onResumeStreamStart(res.dispatch.bg_id);
      }
      if (onForceProjectionRefresh) {
        onForceProjectionRefresh();
      }
      return res;
    } catch (e) {
      setError(e.message);
    } finally {
      setForceRetrying(false);
    }
  }

  function handleCancelClick() {
    setCancelModalOpen(true);
  }

  async function executeCancellation() {
    // Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
    // Frontend requests cancellation — backend owns lifecycle authority.
    // No optimistic lifecycle mutation. Wait for projection convergence.
    setCancelModalOpen(false);
    console.log("[GUI:CANCEL_CLICK]", {
      workflowId,
      status,
      timestamp: Date.now()
    });
    log("CANCEL_CLICK", { workflowId });
    const TERMINAL_STATUSES = new Set(["COMPLETED", "CANCELLED", "FAILED"]);
    if (TERMINAL_STATUSES.has(status)) {
      setError(`Workflow is already ${status.toLowerCase()}.`);
      return;
    }
    setCancelling(true);
    setError(null);
    try {
      // Sprint 9C-4B: Try WebSocket first, fall back to HTTP
      const wsResult = await api.wsCommand.send(workflowId, "cancel", {});
      if (wsResult.usedWebSocket && wsResult.ack?.status === "accepted") {
        log("CANCEL_WS_ACK", wsResult.ack);
        // Ack is NOT lifecycle truth. Wait for projection/events to update UI.
        // Do not optimistically mark cancelled.
        if (onWorkflowCancelled) onWorkflowCancelled({ workflow_id: workflowId, status: "success", new_state: "CANCELLED" });
        return;
      }
      if (wsResult.usedWebSocket) {
        log("CANCEL_WS_FALLBACK", { reason: wsResult.ack?.status || wsResult.timedOut || "unknown" });
      }
      const res = await api.cancel(workflowId);
      log("CANCEL_RESPONSE", res);

      // Consume successful cancel response and report upward for display convergence
      if (res?.status === "success" &&
        res?.new_state === "CANCELLED" &&
        res?.workflow_id === workflowId &&
        onWorkflowCancelled) {
        console.log("[GUI:CANCEL_RESPONSE_CONSUMED]", {
          workflowId,
          new_state: res.new_state,
          previous_state: res.previous_state,
          timestamp: Date.now()
        });
        onWorkflowCancelled(res);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setCancelling(false);
    }
  }

  async function handleBgStart() {
    if (!bgInput.trim()) return;
    try {
      const res = await api.backgroundStart(bgInput.trim());
      setBgInput("");
      if (onBackgroundStart) onBackgroundStart(res.workflow_id);
    } catch (e) {
      setError(e.message);
    }
  }

  // === ISSUE-062 + ISSUE-092B: Retry visibility uses backend-authored metadata ===
  // If backend provides retryEligible, use it. Otherwise fall back to status-based
  // recoverable terminal check for backward compatibility with old workflows.
  // ISSUE-092B: Also require valid retry_target_step_id and failed_step_id —
  // pre-step planner failures have no steps, so retry must be hidden.
  let showRetry = false;
  if (status === WORKFLOW_LIFECYCLE.FAILED) {
    const hasRetryTarget = !!retryTargetStepId;
    const hasFailedStep = !!failedStepId;
    if (typeof retryEligible === "boolean") {
      // Backend provided explicit eligibility — trust it but also require valid targets
      showRetry = retryEligible && hasRetryTarget && hasFailedStep;
    } else {
      // Fallback: status-based check with target validation
      showRetry = isRecoverableTerminal(status) && hasRetryTarget && hasFailedStep;
    }
  }

  // === ISSUE-098A: Force retry visibility ===
  // Show force retry only when backend explicitly marks candidate.
  // Do NOT synthesize from raw retries/max_retries.
  let showForceRetry = false;
  if (status === WORKFLOW_LIFECYCLE.FAILED) {
    if (typeof forceRetryCandidate === "boolean") {
      showForceRetry = forceRetryCandidate && !!retryTargetStepId && !!failedStepId;
    }
  }
  // Per LIFECYCLE_AUTHORITY_CONTRACT_V1: operator MUST retain Cancel authority for all
  // non-terminal operational states, including bootstrap (ACTIVATING) and recovery
  // (PENDING_RECOVERY) states that are observable via canonical projection.
  const showCancel = status === WORKFLOW_LIFECYCLE.ACTIVE
    || status === WORKFLOW_LIFECYCLE.ACTIVATING
    || status === WORKFLOW_LIFECYCLE.PENDING_RECOVERY
    || status === WORKFLOW_LIFECYCLE.PAUSED
    || status === WORKFLOW_LIFECYCLE.BLOCKED;

  const canPause = workflowId && status === WORKFLOW_LIFECYCLE.ACTIVE && !pausing;
  const canResume = workflowId && (status === WORKFLOW_LIFECYCLE.PAUSED || status === WORKFLOW_LIFECYCLE.PENDING_RECOVERY) && !resuming;

  // === [AUTH:CONTROL_LEGALITY] Control legality from component perspective ===
  if (status === WORKFLOW_LIFECYCLE.ACTIVE || status === WORKFLOW_LIFECYCLE.PENDING_RECOVERY) {
    console.log("[AUTH:CONTROL_LEGALITY]", {
      workflowId,
      status,
      canPause,
      canResume,
      legality_source: "projection_status",
      lifecycle_source: "status_prop",
      has_runtimeActivity_context: false,
      timestamp: Date.now(),
    });
  }

  console.log("[CONTROL_RUNTIME_AUDIT]", {
    workflowId,
    status,
    canPause,
    canResume,
    showCancel,
    showRetry,
    pausing,
    resuming,
    disabledPause: !canPause,
    disabledResume: !canResume,
    statusType: typeof status,
    statusIsNull: status === null,
    statusIsUndefined: status === undefined,
    statusValue: JSON.stringify(status),
    // === ISSUE-062 RETRY DIAGNOSTIC ===
    retryEligible,
    retryEligibleType: typeof retryEligible,
    failedRecoverable,
    retryDisabledReason,
    showRetryCondition: status === WORKFLOW_LIFECYCLE.FAILED
      ? (typeof retryEligible === "boolean" ? `retryEligible=${retryEligible}` : `fallback_isRecoverableTerminal=${isRecoverableTerminal(status)}`)
      : `status_not_FAILED(${JSON.stringify(status)})`,
    timestamp: Date.now(),
  });

  const cancelModalConfig = cancelModalOpen ? {
    title: "Cancel Workflow",
    confirmLabel: "Cancel Workflow",
    rows: [
      { label: "Action", value: "Cancel Workflow" },
      { label: "Workflow ID", value: workflowId || "—" },
      { label: "Effect", value: "This will intentionally terminate the workflow." },
    ],
    warning:
      "Cancelled workflows are immutable and cannot be retried. " +
      "Execution will stop and the workflow will become observability-only. " +
      "This action cannot be undone.",
  } : null;

  const forceRetryModalConfig = forceRetryModalOpen ? {
    title: "Force Retry Failed Step",
    confirmLabel: "Force Retry",
    rows: [
      { label: "Action", value: "Force Retry Failed Step" },
      { label: "Workflow ID", value: workflowId || "—" },
      { label: "Step ID", value: retryTargetStepId || "—" },
      { label: "Remaining force retries", value: String(forceRetryRemaining ?? 0) },
    ],
    warning:
      "Normal retries are exhausted. Force retry creates a new execution attempt " +
      "outside normal retry bounds. This action is bounded and cannot be repeated indefinitely. " +
      "This action cannot be undone.",
  } : null;

  return (
    <>
      <DangerConfirmModal
        config={cancelModalConfig}
        onConfirm={executeCancellation}
        onCancel={() => setCancelModalOpen(false)}
      />
      <DangerConfirmModal
        config={forceRetryModalConfig}
        onConfirm={() => { setForceRetryModalOpen(false); act(handleForceRetry); }}
        onCancel={() => setForceRetryModalOpen(false)}
      />
      <section className="panel control-panel">
        <h2>Controls</h2>

        <div className="control-row">
          <div className="btn-group">
            <button
              className="btn-control"
              onClick={() => act(handlePause)}
              disabled={!canPause}
              title={
                pausing
                  ? "Pause requested — awaiting orchestrator convergence…"
                  : canPause
                    ? "Request cooperative pause"
                    : status === WORKFLOW_LIFECYCLE.PAUSED
                      ? "Workflow is already paused"
                      : status === WORKFLOW_LIFECYCLE.ACTIVATING
                        ? "Workflow is starting up — pause available once fully active"
                        : status === WORKFLOW_LIFECYCLE.PENDING_RECOVERY
                          ? "Workflow is recovering from restart — pause available once active"
                          : "Pause available when workflow is ACTIVE"
              }
            >
              {pausing ? "⏸ Pausing…" : "Pause"}
            </button>
            <button
              className="btn-control"
              onClick={() => act(handleResume)}
              disabled={!canResume}
              title={
                resuming
                  ? "Resume requested — awaiting orchestrator convergence…"
                  : canResume
                    ? "Resume paused workflow"
                    : status === WORKFLOW_LIFECYCLE.ACTIVE
                      ? "Workflow is already active"
                      : status === WORKFLOW_LIFECYCLE.ACTIVATING
                        ? "Workflow is starting up — will be active automatically"
                        : status === WORKFLOW_LIFECYCLE.PENDING_RECOVERY
                          ? "Workflow is recovering from restart — click Resume to continue"
                          : "Resume available when workflow is PAUSED"
              }
            >
              {resuming ? "▶ Resuming…" : "Resume"}
            </button>
          </div>
        </div>

        {/* Cancel control for active/paused/blocked workflows */}
        {showCancel && (
          <div className="control-row">
            <button
              className="btn-control btn-control--cancel"
              onClick={handleCancelClick}
              disabled={!workflowId || cancelling}
              title="Cancel workflow — intentional immutable termination"
            >
              ⏹ Cancel Workflow
            </button>
          </div>
        )}

        {/* Retry control for recoverable terminal workflows (FAILED) */}
        {showRetry && (
          <div className="control-row">
            <button
              className="btn-control btn-control--retry"
              onClick={() => act(handleRetry)}
              disabled={!workflowId || retrying}
              title="Retry failed step — creates a new execution attempt with fresh isolation boundaries"
            >
              ⟳ Retry Failed Step
            </button>
          </div>
        )}

        {/* Force retry control for when normal retries are exhausted */}
        {showForceRetry && (
          <div className="control-row">
            <button
              className="btn-control btn-control--retry"
              style={{ borderColor: "#c0392b" }}
              onClick={() => setForceRetryModalOpen(true)}
              disabled={!workflowId || forceRetrying}
              title="Force retry failed step — bounded retry beyond normal limits"
            >
              ⟳ Force Retry Failed Step
            </button>
          </div>
        )}

        {pausing && (
          <div className="control-row">
            <span className="pause-pending-badge muted">
              ⏸ Pause requested — awaiting orchestrator convergence…
            </span>
          </div>
        )}

        {resuming && (
          <div className="control-row">
            <span className="resume-pending-badge muted">
              ▶ Resume requested — awaiting orchestrator convergence…
            </span>
          </div>
        )}

        {retrying && (
          <div className="control-row">
            <span className="retry-pending-badge muted">
              ◌ Retrying step — awaiting projection refresh…
            </span>
          </div>
        )}

        {forceRetrying && (
          <div className="control-row">
            <span className="retry-pending-badge muted">
              ◌ Force retrying step — awaiting projection refresh…
            </span>
          </div>
        )}

        {cancelling && (
          <div className="control-row">
            <span className="cancel-pending-badge muted">
              ◌ Cancelling workflow — awaiting projection update…
            </span>
          </div>
        )}

        <div className="bg-start-row">
          <input
            className="bg-input"
            placeholder="Background task input…"
            value={bgInput}
            onChange={(e) => setBgInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !pendingReattach && handleBgStart()}
          />
          <button
            className="btn-secondary"
            onClick={handleBgStart}
            disabled={!bgInput.trim() || pendingReattach}
            title={pendingReattach ? "Reattaching workflow — please wait" : "Start background task"}
          >
            {pendingReattach ? "Reattaching…" : "Start Background"}
          </button>
        </div>

        {error && <div className="error-badge">⚠ {error}</div>}
      </section>
    </>
  );
}
