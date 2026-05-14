import { useState, useEffect, useRef } from "react";
import ChatPanel from "./components/ChatPanel.jsx";
import WorkflowPanel from "./components/WorkflowPanel.jsx";
import WorkflowProjectionView from "./components/WorkflowProjectionView.jsx";
import ExecutionPanel from "./components/ExecutionPanel.jsx";
import ControlPanel from "./components/ControlPanel.jsx";
import BackgroundPanel from "./components/BackgroundPanel.jsx";
import ApprovalPanel from "./components/ApprovalPanel.jsx";
import { waitForBackend, api } from "./api.js";
import { log } from "./utils/log.js";
import "./styles.css";

const STREAM_POLL_MS = 500;
// Consecutive 404 responses before declaring a workflow orphaned and self-healing.
// At STREAM_POLL_MS=500ms this means ~1.5 seconds of sustained absence before invalidation.
const MAX_ORPHAN_POLLS = 3;

// Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
// - Frontend is projection-only
// - All lifecycle state derives from backend projection
// - Frontend does NOT synthesize lifecycle state locally
// - Frontend does NOT infer workflow ownership

export default function App() {
  const [lastResult, setLastResult] = useState(null);
  const [debugMode, setDebugMode] = useState(false);
  const [bgRefresh, setBgRefresh] = useState(0);
  const [backendReady, setBackendReady] = useState(false);
  const [backendError, setBackendError] = useState(null);
  const streamPollRef = useRef(null);
  const activeBgIdRef = useRef(null);       // tracks which bgId the current poll owns
  const lastResultRef = useRef(null);       // authoritative ref — avoids stale closure in setInterval
  const consecutive404Ref = useRef(0); // consecutive 404/orphan responses from stream poll

  // Derive isExecuting from backend projection (workflow status)
  // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
  const isExecuting = lastResult?.status === "ACTIVE";

  // Derive activeWorkflowId from backend projection
  // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
  const activeWorkflowId = lastResult?.workflow_id || null;

  useEffect(() => {
    waitForBackend(20, 500)
      .then(() => {
        setBackendReady(true);
        // Reconnect recovery: if frontend holds stale execution state (isExecuting still
        // true from before restart, or lastResult is null), query backend for any active
        // non-terminal streams and reattach if found.
        // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: frontend is projection-only;
        // backend is the sole source of recovery truth.
        api.getActiveStreams()
          .then((res) => {
            const active = res.active || [];
            if (active.length === 0) {
              // No recoverable streams on backend — clear any stale execution lock.
              if (lastResultRef.current !== null) {
                console.log("[GUI:RECONNECT_RECOVERY]", {
                  action: "clear_stale_result",
                  staleStatus: lastResultRef.current?.status,
                  reason: "no_streams_on_backend",
                  timestamp: Date.now(),
                });
                lastResultRef.current = null;
                setLastResult(null);
              }
              return;
            }
            // Recovery reattach: filter out QUARANTINED entries (backend excludes them
            // already, but guard here for defence-in-depth).
            // Prefer newest non-terminal (ACTIVE/PENDING_RECOVERY) entry — execution
            // in-progress takes priority over terminal rehydration.
            // Fall back to the last terminal entry so already-completed workflows
            // still hydrate the UI with their final result.
            const recoverable = active.filter(
              (e) => e.status !== "QUARANTINED"
            );
            if (recoverable.length === 0) {
              // All entries were quarantined — treat as empty
              if (lastResultRef.current !== null) {
                lastResultRef.current = null;
                setLastResult(null);
              }
              return;
            }
            const nonTerminal = recoverable.find(
              (e) => e.status !== "COMPLETED" && e.status !== "FAILED"
            );
            const entry = nonTerminal || recoverable[recoverable.length - 1];
            console.log("[GUI:RECONNECT_RECOVERY]", {
              action: "reattach_stream",
              bgId: entry.bg_id,
              workflowId: entry.workflow_id,
              status: entry.status,
              isTerminalRehydration: !nonTerminal,
              timestamp: Date.now(),
            });
            handleStreamStart(entry.bg_id);
          })
          .catch(() => {
            // Recovery fetch failure is non-fatal — frontend continues in idle state.
          });
      })
      .catch((e) => setBackendError(e.message));
  }, []);

  // === WORKFLOW CONTEXT HANDLING ===
  // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
  // Frontend derives workflow context from backend projection (lastResult)
  // No local workflow ownership synthesis or fallback logic
  // Backend provides authoritative workflow identity via projection

  function stopStreamPoll(reason = "unknown", bgId = null) {
    if (streamPollRef.current) {
      clearInterval(streamPollRef.current);
      streamPollRef.current = null;
      console.log("[GUI:STREAM_CLEANUP]", {
        bgId: bgId ?? activeBgIdRef.current,
        reason,
        timestamp: Date.now()
      });
    }
    activeBgIdRef.current = null;
    consecutive404Ref.current = 0;
  }

  // Unconditional full reset when backend confirms a workflow no longer exists.
  // Called from the stream poll (consecutive 404s on /execute/stream/workflow_id)
  // and from WorkflowProjectionView (consecutive 404s on /projection/{id}).
  // Both paths arrive at the same invariant: backend has no record of this workflow
  // → frontend must relinquish all ownership and return to clean idle.
  function invalidateOrphanedWorkflow(reason, workflowId) {
    console.log("[GUI:ORPHAN_INVALIDATION]", {
      workflowId,
      reason,
      previousStatus: lastResultRef.current?.status,
      timestamp: Date.now(),
    });
    stopStreamPoll("orphan_invalidation");
    lastResultRef.current = null;
    setLastResult(null);
  }

  function handleExecutionStart() {
    // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
    // Clear lastResult to indicate new execution starting
    // Backend will provide authoritative workflow identity in projection
    stopStreamPoll("new_execution_start");
    lastResultRef.current = null;
    setLastResult(null);
    log("EXECUTION_START", { lastResult: null });
  }

  function handleStreamStart(bgId) {
    // === SINGLE ACTIVE STREAM CONTRACT ===
    // Per PROJECTION_CONTINUITY_CONTRACT_V1 §14: uncontrolled projection replacement prohibited.
    // Guard: refuse to start a poll for an undefined/null bgId (e.g. resume with no bg_id in response).
    if (!bgId) {
      console.log("[GUI:STREAM_ATTACH]", {
        bgId: null,
        reason: "rejected_undefined_bgId",
        timestamp: Date.now()
      });
      return;
    }
    stopStreamPoll("new_stream_attach", bgId);
    activeBgIdRef.current = bgId;
    console.log("[GUI:STREAM_ATTACH]", {
      bgId,
      streamOwner: "handleStreamStart",
      timestamp: Date.now()
    });
    streamPollRef.current = setInterval(async () => {
      // === SINGLE ACTIVE STREAM: ignore if this interval is no longer the active owner ===
      if (activeBgIdRef.current !== bgId) {
        console.log("[GUI:WORKFLOW_ISOLATION_REJECT]", {
          staleBgId: bgId,
          activeBgId: activeBgIdRef.current,
          reason: "stale_interval_owner",
          timestamp: Date.now()
        });
        return;
      }
      try {
        const wfData = await api.streamWorkflowId(bgId);
        // Successful fetch — reset orphan counter.
        consecutive404Ref.current = 0;

        // PENDING means planning is still in progress (null workflow_id).
        // Per fixed stream schema: only PENDING, ACTIVE, COMPLETED, FAILED reach frontend.
        if (!wfData.workflow_id || wfData.status === "PENDING") {
          return;
        }

        // === WORKFLOW_STATE_UPDATE log ===
        if (wfData.workflow_id && wfData.workflow_id !== activeWorkflowId) {
          console.log("[GUI:WORKFLOW_STATE_UPDATE]", {
            workflowId: wfData.workflow_id,
            previousState: activeWorkflowId,
            nextState: wfData.workflow_id,
            source: "event_stream",
            timestamp: Date.now()
          });
        }
        if (wfData.result && (!lastResultRef.current || wfData.result !== lastResultRef.current)) {
          console.log("[GUI:WORKFLOW_STATE_UPDATE]", {
            workflowId: wfData.workflow_id,
            previousState: lastResultRef.current?.status,
            nextState: wfData.result?.status,
            source: "event_stream",
            timestamp: Date.now()
          });
        }
        // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
        // Per PROJECTION_CONTINUITY_CONTRACT_V1 §9: Terminal projections MUST NOT revert
        // Per PROJECTION_CONTINUITY_CONTRACT_V1 §13: No invalid ACTIVE/COMPLETED coexistence
        if (wfData.result) {
          const isTerminal = (status) => status === "COMPLETED" || status === "FAILED";
          // Read current result from ref (not stale closure) to avoid false rejections
          const currentResult = lastResultRef.current;

          // Stale terminal overwrite prevention — uses ref not stale closure
          if (currentResult && isTerminal(currentResult.status) && !isTerminal(wfData.status)) {
            console.log("[GUI:TERMINAL_PROTECTION]", {
              workflowId: wfData.workflow_id,
              existingTerminalState: currentResult.status,
              incomingNonTerminalState: wfData.status,
              action: "rejected"
            });
            return;
          }

          const terminalResult = {
            ...wfData.result,
            workflow_id: wfData.workflow_id || wfData.result?.workflow_id,
            status: wfData.status || wfData.result?.status
          };
          lastResultRef.current = terminalResult;
          setLastResult(terminalResult);
        } else if (wfData.workflow_id && wfData.status && wfData.status !== "COMPLETED" && wfData.status !== "FAILED") {
          // result is null but we have workflow_id + non-terminal status (e.g. execution is
          // mid-resurrection and run_workflow hasn't written workflow to registry yet).
          // Hydrate a minimal lastResult so isExecuting becomes true and WorkflowProjectionView
          // mounts. This covers the recovery window where backend knows workflow is ACTIVE but
          // has no projected steps yet. Will be overwritten when full result arrives.
          const currentResult = lastResultRef.current;
          if (!currentResult || currentResult.workflow_id !== wfData.workflow_id) {
            const minimalResult = {
              workflow_id: wfData.workflow_id,
              status: wfData.status,
              steps: [],
            };
            lastResultRef.current = minimalResult;
            setLastResult(minimalResult);
            console.log("[GUI:RECOVERY_MINIMAL_HYDRATION]", {
              workflowId: wfData.workflow_id,
              status: wfData.status,
              reason: "result_null_mid_execution",
              timestamp: Date.now(),
            });
          }
        }
        // === TERMINAL STREAM SHUTDOWN ===
        // Per PROJECTION_CONTINUITY_CONTRACT_V1 §9: terminal states are continuity anchors.
        // Once terminal, stop the stream poll immediately — no further events expected.
        // PAUSED is NOT terminal (per STATE_TRANSITIONS_CONTRACT_V1: PAUSED → ACTIVE is valid).
        // Defense-in-depth: also check wfData.result?.status — covers race where wfData.status
        // lags behind the result payload (e.g. FIX-3 failure result with status:"FAILED").
        const _terminalStatus = wfData.status === "COMPLETED" || wfData.status === "FAILED"
          || wfData.result?.status === "COMPLETED" || wfData.result?.status === "FAILED";
        if (_terminalStatus) {
          const _resolvedStatus = wfData.status === "COMPLETED" || wfData.result?.status === "COMPLETED"
            ? "COMPLETED" : "FAILED";
          console.log("[GUI:TERMINAL_STREAM_SHUTDOWN]", {
            bgId,
            workflowId: wfData.workflow_id,
            terminalStatus: _resolvedStatus,
            reason: "workflow_terminal",
            timestamp: Date.now()
          });
          stopStreamPoll("terminal_state", bgId);
          if (_resolvedStatus === "FAILED") {
            // Preserve authoritative "FAILED" (uppercase) — WorkflowPanel isTerminal checks "FAILED".
            // Do NOT downcase to "failure": that broke WorkflowPanel poll-shutdown (RR-2).
            // FIX D (Phase 1B): canonical reason derivation hierarchy — "Unknown error" MUST NOT
            // appear when a canonical reason exists anywhere in the workflow payload.
            const _failedStep = (wfData.steps || []).find(
              s => s.status === "FAILED" || s.status === "BLOCKED"
            );
            const _canonicalReason =
              wfData.error ||
              wfData.result?.reason ||
              wfData.reason ||
              _failedStep?.blocked_reason ||
              _failedStep?.execution_result?.reason ||
              "workflow_failed";
            setLastResult(prev => ({
              ...prev,
              status: "FAILED",
              reason: _canonicalReason
            }));
          }
        }
      } catch (err) {
        const is404 = err?.message && (
          err.message.includes("404") ||
          err.message.includes("Not Found") ||
          err.message.includes("workflow not found")
        );
        if (is404) {
          consecutive404Ref.current += 1;
          console.log("[GUI:STREAM_POLL_404]", {
            bgId,
            workflowId: lastResultRef.current?.workflow_id,
            consecutiveCount: consecutive404Ref.current,
            threshold: MAX_ORPHAN_POLLS,
            timestamp: Date.now(),
          });
          if (consecutive404Ref.current >= MAX_ORPHAN_POLLS) {
            invalidateOrphanedWorkflow(
              `stream_poll_consecutive_404:${consecutive404Ref.current}`,
              lastResultRef.current?.workflow_id
            );
          }
        } else {
          consecutive404Ref.current = 0;
        }
      }
    }, STREAM_POLL_MS);
  }

  function handleResult(result) {
    console.log("[GUI:WORKFLOW_STATE_UPDATE]", {
      workflowId: result?.workflow_id,
      previousState: lastResultRef.current?.status,
      nextState: result?.status,
      source: "api_response",
      timestamp: Date.now()
    });
    // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
    // Backend provides authoritative workflow identity and status via projection
    log("RESULT_UPDATE", { result_status: result?.status, result_payload: result, result_workflow_id: result?.workflow_id });
    lastResultRef.current = result;
    setLastResult(result);
    log("SET_LAST_RESULT", { status: result?.status, source: "handle_result" });
  }

  function handleBackgroundStart() {
    setBgRefresh((n) => n + 1);
  }

  function handleResumeStreamStart(bgId) {
    log("RESUME_STREAM_START", { bgId });
    // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
    // Backend provides authoritative workflow status via projection
    // Resume continuity: preserve existing workflow context, let stream update with resumed state.
    // handleStreamStart guards against undefined bgId (resume endpoint may omit bg_id).
    if (!bgId) {
      log("RESUME_STREAM_NO_BG_ID", { reason: "resume_response_missing_bg_id" });
      console.log("[GUI:STREAM_ATTACH]", {
        bgId: null,
        streamOwner: "handleResumeStreamStart",
        reason: "resume_response_missing_bg_id — existing poll continues unchanged",
        timestamp: Date.now()
      });
      return;
    }
    handleStreamStart(bgId);
  }

  if (backendError) {
    return (
      <div className="app">
        <header className="app-header">
          <span className="logo">⬡ AI Lab</span>
        </header>
        <main className="layout">
          <div className="startup-error">
            <h2>⚠ Backend Unavailable</h2>
            <p>{backendError}</p>
            <p className="muted">
              Ensure Python and uvicorn are installed, then restart the application.
            </p>
            <button
              className="btn-primary"
              onClick={() => {
                setBackendError(null);
                setBackendReady(false);
                waitForBackend(20, 500)
                  .then(() => setBackendReady(true))
                  .catch((e) => setBackendError(e.message));
              }}
            >
              Retry
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (!backendReady) {
    return (
      <div className="app">
        <header className="app-header">
          <span className="logo">⬡ AI Lab</span>
        </header>
        <main className="layout">
          <div className="startup-loading">
            <div className="spinner" />
            <p>Starting backend…</p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <span className="logo">⬡ AI Lab</span>
        <label className="debug-toggle">
          <input
            type="checkbox"
            checked={debugMode}
            onChange={(e) => setDebugMode(e.target.checked)}
          />
          Debug Mode
        </label>
      </header>

      <main className="layout">
        <ChatPanel
          onResult={handleResult}
          onExecutionStart={handleExecutionStart}
          onStreamStart={handleStreamStart}
          isExecuting={isExecuting}
        />

        <div className="mid-row">
          <WorkflowPanel
            result={lastResult}
            isExecuting={isExecuting}
          />
          <ExecutionPanel result={lastResult} debugMode={debugMode} />
        </div>

        {/* Per CANONICAL_PROJECTION_MODEL_V1: Canonical Projection Rendering Pipeline (SUB-PHASE 3A) */}
        {/* Renders ONLY from orchestrator-owned canonical WorkflowProjection via GET /projection/{workflowId} */}
        {/* workflowId derived from backend projection — no local synthesis */}
        {activeWorkflowId && (
          <WorkflowProjectionView
            workflowId={activeWorkflowId}
            isExecuting={isExecuting}
            showPlanView={true}
            onOrphan={(reason) => invalidateOrphanedWorkflow(reason, activeWorkflowId)}
          />
        )}

        <ControlPanel
          onBackgroundStart={handleBackgroundStart}
          onResumeStreamStart={handleResumeStreamStart}
          workflowId={activeWorkflowId}
        />

        <BackgroundPanel
          triggerRefresh={bgRefresh}
        />

        <ApprovalPanel workflowId={activeWorkflowId} />

        {debugMode && lastResult && (
          <section className="panel debug-panel">
            <h2>Raw Workflow JSON</h2>
            <pre className="json-dump">{JSON.stringify(lastResult, null, 2)}</pre>
          </section>
        )}
      </main>
    </div>
  );
}
