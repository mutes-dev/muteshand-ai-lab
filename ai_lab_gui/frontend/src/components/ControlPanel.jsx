import { useState, useEffect } from "react";
import { api } from "../api.js";
import { log } from "../utils/log.js";
import { isRecoverableTerminal, WORKFLOW_LIFECYCLE } from "../constants/workflow.js";

// Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
// Frontend does NOT synthesize workflow ownership
// Backend provides authoritative workflow identity via projection

export default function ControlPanel({
  onBackgroundStart,
  onResumeStreamStart,
  onPause,
  workflowId,
  status
}) {
  const [bgInput, setBgInput] = useState("");
  const [error, setError] = useState(null);
  const [cancelling, setCancelling] = useState(false);
  const [retrying, setRetrying] = useState(false);
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
    // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
    // workflowId is derived from backend projection, not synthesized locally
    console.log("[GUI:PAUSE_CLICK]", {
      workflowId,
      timestamp: Date.now()
    });
    log("PAUSE_CLICK", { workflowId });
    setPausing(true);
    try {
      const res = await api.pause(workflowId);
      log("PAUSE_RESPONSE", res);
      // Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1:
      // PAUSED workflows do not retain active execution context.
      // Stream polling must stop to prevent 404 orphan invalidation.
      if (res?.success && onPause) {
        onPause("pause");
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setPausing(false);
    }
  }

  async function handleResume() {
    // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
    // workflowId is derived from backend projection, not synthesized locally
    console.log("[GUI:RESUME_CLICK]", {
      workflowId,
      timestamp: Date.now()
    });
    log("RESUME_CLICK", { workflowId });
    setResuming(true);
    try {
      const res = await api.resume(workflowId);
      log("RESUME_RESPONSE", res);
      // Start streaming for the new bg_id returned by resume
      if (res.bg_id && onResumeStreamStart) {
        onResumeStreamStart(res.bg_id);
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
    // Per RETRY_SEMANTICS_AND_LINEAGE_RECONCILIATION_REPORT:
    // retry_step is the canonical retry mechanism. There is no workflow-level retry.
    console.log("[GUI:RETRY_CLICK]", {
      workflowId,
      status,
      timestamp: Date.now()
    });
    log("RETRY_CLICK", { workflowId });
    setRetrying(true);
    try {
      // Fetch authoritative projection to identify FAILED steps.
      // Per CANONICAL_PROJECTION_MODEL_V1: projection is authoritative, not synthesized.
      const proj = await api.getProjection(workflowId);
      const steps = proj?.steps || [];
      const failedStep = steps.find((s) => s.status === "FAILED");
      if (!failedStep) {
        setError("No failed step found — workflow may have recovered or has no failed steps.");
        return;
      }
      log("RETRY_STEP_IDENTIFIED", { workflowId, stepId: failedStep.step_id });
      const res = await api.requestMutation(
        workflowId,
        "retry_step",
        { step_id: failedStep.step_id },
        "user"
      );
      log("RETRY_RESPONSE", res);
      return res;
    } catch (e) {
      setError(e.message);
    } finally {
      setRetrying(false);
    }
  }

  async function handleCancel() {
    // Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
    // Frontend requests cancellation — backend owns lifecycle authority.
    // No optimistic lifecycle mutation. Wait for projection convergence.
    const confirmed = window.confirm(
      "This will intentionally terminate the workflow.\n\n" +
      "Cancelled workflows are immutable and cannot be retried.\n" +
      "Execution will stop and the workflow will become observability-only.\n\n" +
      "Confirm cancellation?"
    );
    if (!confirmed) return;

    console.log("[GUI:CANCEL_CLICK]", {
      workflowId,
      status,
      timestamp: Date.now()
    });
    log("CANCEL_CLICK", { workflowId });
    setCancelling(true);
    try {
      const res = await api.cancel(workflowId);
      log("CANCEL_RESPONSE", res);
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

  const showRetry = isRecoverableTerminal(status);
  // Per LIFECYCLE_AUTHORITY_CONTRACT_V1: operator MUST retain Cancel authority for all
  // non-terminal operational states, including bootstrap (ACTIVATING) and recovery
  // (PENDING_RECOVERY) states that are observable via canonical projection.
  const showCancel = status === WORKFLOW_LIFECYCLE.ACTIVE
    || status === WORKFLOW_LIFECYCLE.ACTIVATING
    || status === WORKFLOW_LIFECYCLE.PENDING_RECOVERY
    || status === WORKFLOW_LIFECYCLE.PAUSED
    || status === WORKFLOW_LIFECYCLE.BLOCKED;

  const canPause = workflowId && status === WORKFLOW_LIFECYCLE.ACTIVE && !pausing;
  const canResume = workflowId && status === WORKFLOW_LIFECYCLE.PAUSED && !resuming;

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
    timestamp: Date.now(),
  });

  return (
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
                        ? "Workflow is recovering from restart — will resume automatically"
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
            onClick={() => act(handleCancel)}
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
          onKeyDown={(e) => e.key === "Enter" && handleBgStart()}
        />
        <button className="btn-secondary" onClick={handleBgStart} disabled={!bgInput.trim()}>
          Start Background
        </button>
      </div>

      {error && <div className="error-badge">⚠ {error}</div>}
    </section>
  );
}
