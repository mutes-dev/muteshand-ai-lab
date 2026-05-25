import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "./api.js";
import { log } from "./utils/log.js";
import { logFgAuth, captureFgAuthState } from "./utils/fgAuthLog.js";
import { useBackendReadiness } from "./hooks/useBackendReadiness.js";
import { useRuntimeActivity } from "./hooks/useRuntimeActivity.js";
import { useWorkflowSession } from "./hooks/useWorkflowSession.js";
import WorkflowPanel from "./components/WorkflowPanel.jsx";
import WorkflowProjectionView from "./components/WorkflowProjectionView.jsx";
import GlobalRuntimeStatus from "./components/GlobalRuntimeStatus.jsx";
import ExecutionPanel from "./components/ExecutionPanel.jsx";
import ControlPanel from "./components/ControlPanel.jsx";
import BackgroundPanel from "./components/BackgroundPanel.jsx";
import ApprovalPanel from "./components/ApprovalPanel.jsx";
import WorkflowManager from "./components/WorkflowManager.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import "./styles.css";

const STREAM_POLL_MS = 500;
// Consecutive 404 responses before declaring a workflow orphaned and self-healing.
// At STREAM_POLL_MS=500ms this means ~1.5 seconds of sustained absence before invalidation.
const MAX_ORPHAN_POLLS = 3;
// Per OPERATOR_SESSION_CONTRACT_V1: renderer-session continuity discriminator key.
// sessionStorage persists through browser refresh/renderer reload but is absent
// on cold app open (new WebView instance). Used to distinguish same-session reload
// from cold boot without relying on backend lifecycle status heuristics.
const SESSION_CONTINUITY_KEY = "wf_session_foreground";

// Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
// - Frontend is projection-only
// - All lifecycle state derives from backend projection
// - Frontend does NOT synthesize lifecycle state locally
// - Frontend does NOT infer workflow ownership

export default function App() {
  console.log("[STARTUP_TRACE] App render start");
  const [debugMode, setDebugMode] = useState(false);
  const [bgRefresh, setBgRefresh] = useState(0);
  // === FOCUSED WORKFLOW LIFECYCLE SOURCE UNIFICATION (PHASE 4A) ===
  // Per LIFECYCLE_AUTHORITY_CONTRACT_V1: All focused-workflow surfaces MUST
  // consume the same authoritative lifecycle source. Projection is the
  // canonical source; lastResult is stream-derived and may lag.
  const [focusedProjection, setFocusedProjection] = useState(null);
  console.log("[STARTUP_TRACE] useState initialized");

  // === REFS (MUST BE DEFINED BEFORE HOOKS THAT USE THEM) ===
  const streamPollRef = useRef(null);
  const activeBgIdRef = useRef(null);
  const consecutive404Ref = useRef(0);

  // === PHASE 1: Backend Readiness Extraction ===
  // Per APP_JSX_DECOUPLING_ARCHITECTURE_AUDIT.md:
  // Backend readiness is isolated, non-authoritative, safe to extract.
  const { isReady: backendReady, isLoading: backendLoading, isUnavailable: backendUnavailable, error: backendError, retry } = useBackendReadiness();
  console.log(`[STARTUP_TRACE] useBackendReadiness: backendReady=${backendReady}, isLoading=${backendLoading}, isUnavailable=${backendUnavailable}`);

  // === PHASE 2: Runtime Activity Extraction ===
  // Per APP_JSX_DECOUPLING_ARCHITECTURE_AUDIT.md:
  // Runtime observability is backend-authoritative, safe to extract.
  const { runtimeActivity, updateRuntimeActivity, resetRuntimeActivity } = useRuntimeActivity();
  console.log(`[STARTUP_TRACE] useRuntimeActivity: runtimeActivity=${JSON.stringify(runtimeActivity)}`);

  // === STREAM LIFECYCLE CALLBACKS (must be before hooks that use them) ===
  const stopStreamPoll = useCallback((reason = "unknown", bgId = null) => {
    console.log(`[STARTUP_TRACE] stopStreamPoll called, reason=${reason}`);
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
  }, []);

  // === PHASE 3: Workflow Session Extraction ===
  // Per APP_JSX_DECOUPLING_ARCHITECTURE_AUDIT.md:
  // MEDIUM-RISK extraction with ALL SAFETY GUARDS PRESERVED.
  // NOTE: Must be defined AFTER backendReady and resetRuntimeActivity
  const {
    lastResult,
    activeWorkflowId,
    isExecuting,
    expectedWorkflowIdRef,
    lastResultRef,
    setLastResult,
    selectWorkflow,
    invalidateOrphanedWorkflow,
    resetSession,
    requestNewWorkflow,
  } = useWorkflowSession({
    resetRuntimeActivity,
    stopStreamPoll,
  });

  // === AUTHORITY-FIRST RESTORATION (PHASE XVI-A) ===
  // Triggered when backend becomes ready
  useEffect(() => {
    console.log(`[STARTUP_TRACE] useEffect[backendReady] start, backendReady=${backendReady}`);
    if (!backendReady) {
      console.log("[STARTUP_TRACE] Early return: backendReady=false");
      return;
    }
    console.log("[STARTUP_TRACE] Beginning session recovery...");
    // Per SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1 §10:
    // Recovery MUST converge from authority downward.
    // Per LIFECYCLE_AUTHORITY_CONTRACT_V1 §WORKFLOW ENUMERATION RULES:
    // Frontend MUST NOT infer workflow existence heuristically.
    // Per GUI_ARCHITECTURE.txt §WORKFLOW SELECTION BOUNDARY:
    // Frontend MUST NOT assume singleton workflow recovery.
    console.log("[STARTUP_TRACE] Fetching authoritative workflows...");
    api.getAuthoritativeWorkflows()
      .then((res) => {
        console.log(`[STARTUP_TRACE] Authoritative workflows fetched: ${JSON.stringify(res)}`);
        const workflows = res.workflows || [];
        const recoverable = workflows.filter((w) => w.recoverable === true);
        console.log("[GUI:AUTHORITY_RESTORE_PAYLOAD]", {
          total: workflows.length,
          recoverableCount: recoverable.length,
          recoverableIds: recoverable.map(w => w.workflow_id),
          timestamp: Date.now(),
        });

        // === ATTACHMENT PRESERVATION GUARD ===
        // Per GUI_FUNCTIONALITY_CONTRACT_V1 §FOCUSED WORKFLOW PERSISTENCE:
        // Focused workflow attachment persists until explicitly detached or another
        // workflow explicitly attached. Reconnect hydration MUST NOT implicitly sever.
        const currentWorkflowId = lastResultRef.current?.workflow_id;
        if (currentWorkflowId) {
          const currentEntry = workflows.find((w) => w.workflow_id === currentWorkflowId);
          if (currentEntry) {
            console.log("[GUI:RECONNECT_RECOVERY]", {
              action: "preserve_existing_attachment",
              workflowId: currentWorkflowId,
              status: currentEntry.status,
              recoverable: currentEntry.recoverable,
              reason: "workflow_still_known_to_backend",
              timestamp: Date.now(),
            });
            return;
          }
          // Current workflow not in backend list — orphaned, proceed with recovery
          console.log("[GUI:RECONNECT_RECOVERY]", {
            action: "attachment_orphaned",
            workflowId: currentWorkflowId,
            reason: "workflow_not_in_authoritative_list",
            timestamp: Date.now(),
          });
        }

        if (recoverable.length === 0) {
          // No recoverable workflows — clear any stale execution lock.
          if (lastResultRef.current !== null) {
            console.log("[GUI:RECONNECT_RECOVERY]", {
              action: "clear_stale_result",
              staleStatus: lastResultRef.current?.status,
              reason: "no_recoverable_workflows",
              timestamp: Date.now(),
            });
            console.trace("[FG_DETACH]", {
              reason: "no_recoverable_workflows",
              activeWorkflowId,
              bgId: activeBgIdRef.current,
              timestamp: Date.now(),
            });
            lastResultRef.current = null;
            setLastResult(null);
          }
          return;
        }
        // === REFRESH CONTINUITY REPAIR — PHASE XVI-B ===
        // Per OPERATOR_SESSION_CONTRACT_V1:
        // Renderer-session continuity is signalled by SESSION_CONTINUITY_KEY in sessionStorage.
        // sessionStorage survives browser refresh/renderer reload but is ABSENT on cold app open
        // (Tauri creates a new WebView instance → storage cleared). This is the correct
        // discriminator — NOT backend lifecycle status, which is ACTIVE on both refresh AND
        // cold open (when backend stays alive), making status-inference ambiguous.
        const continuityMarker = sessionStorage.getItem(SESSION_CONTINUITY_KEY);
        if (
          continuityMarker &&
          recoverable.length === 1 &&
          recoverable[0].workflow_id === continuityMarker
        ) {
          const single = recoverable[0];
          // Per GUI_FUNCTIONALITY_CONTRACT_V1: PAUSED workflows are operational and
          // must preserve continuity equivalently to ACTIVE workflows.
          const isEligibleForAutoRestore =
            single.status === "ACTIVE" ||
            single.status === "ACTIVATING" ||
            single.status === "PAUSED";
          if (isEligibleForAutoRestore) {
            const bgId = single.bg_ids?.[0] || null;
            console.log("[GUI:RECONNECT_RECOVERY]", {
              action: "auto_restore_eligible_session",
              workflowId: single.workflow_id,
              status: single.status,
              bgId,
              reason: "renderer_session_continuity_marker",
              timestamp: Date.now(),
            });
            loadProjectionOnlyWorkflow(single.workflow_id, bgId);
            return;
          }
        }
        // No continuity marker (cold boot), multiple workflows, marker mismatch,
        // or single non-eligible workflow (BLOCKED/PENDING_RECOVERY):
        // require explicit Task Hub selection.
        console.log("[GUI:RECONNECT_RECOVERY]", {
          action: "explicit_selection_required",
          reason: recoverable.length > 1 ? "multiple_recoverable_workflows"
            : !continuityMarker ? "no_session_continuity_marker"
              : "non_active_single_workflow",
          count: recoverable.length,
          hasContinuityMarker: !!continuityMarker,
          markedWorkflowId: continuityMarker,
          workflowIds: recoverable.map(w => w.workflow_id),
          timestamp: Date.now(),
        });
        // Clear any stale attachment — Task Hub will display recoverable workflows
        console.trace("[FG_DETACH]", {
          reason: "explicit_selection_required_multiple_or_non_eligible",
          activeWorkflowId,
          bgId: activeBgIdRef.current,
          timestamp: Date.now(),
        });
        lastResultRef.current = null;
        setLastResult(null);
      })
      .catch(() => {
        // Recovery fetch failure is non-fatal — frontend continues in idle state.
      });
  }, [backendReady]);

  // === TEMPORARY FORENSIC INSTRUMENTATION — CATEGORY E AUDIT ===
  // Scans all overlay/fixed elements after workflow attach to detect pointer-event interception.
  // Remove after root cause is identified.
  useEffect(() => {
    if (!activeWorkflowId) return;
    const scan = () => {
      const fixed = Array.from(document.querySelectorAll('*')).filter(el => {
        const s = window.getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden') return false;
        if (parseFloat(s.opacity) <= 0) return false;
        return s.position === 'fixed' || s.position === 'absolute';
      }).map(el => {
        const s = window.getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return {
          tag: el.tagName,
          cls: el.className?.toString?.().slice(0, 80),
          pos: s.position,
          z: s.zIndex,
          pe: s.pointerEvents,
          fullscreen: r.left <= 2 && r.top <= 2 && r.right >= window.innerWidth - 2 && r.bottom >= window.innerHeight - 2,
          rect: { l: Math.round(r.left), t: Math.round(r.top), r: Math.round(r.right), b: Math.round(r.bottom) },
        };
      });
      const fullscreenBlockers = fixed.filter(el => el.fullscreen && el.pe !== 'none');
      console.log("[GUI:OVERLAY_SCAN]", {
        activeWorkflowId,
        totalFixed: fixed.length,
        fullscreenBlockers: fullscreenBlockers.length,
        blockers: fullscreenBlockers,
        allFixed: fixed,
        timestamp: Date.now(),
      });
      // Hit-test the Pause button
      const btns = Array.from(document.querySelectorAll('button'));
      const pauseBtn = btns.find(b => b.textContent?.trim().includes('Pause'));
      if (pauseBtn) {
        const rect = pauseBtn.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const top = document.elementFromPoint(cx, cy);
        console.log("[GUI:PAUSE_HITBOX]", {
          pauseExists: true,
          hitIsButton: top === pauseBtn,
          topTag: top?.tagName,
          topClass: top?.className?.toString?.().slice(0, 100),
          topZ: top ? window.getComputedStyle(top).zIndex : null,
          topPE: top ? window.getComputedStyle(top).pointerEvents : null,
          pauseRect: { l: Math.round(rect.left), t: Math.round(rect.top), w: Math.round(rect.width), h: Math.round(rect.height) },
          timestamp: Date.now(),
        });
      }
    };
    // Scan immediately and again after 1.5s (covers delayed React renders)
    scan();
    const t = setTimeout(scan, 1500);
    return () => clearTimeout(t);
  }, [activeWorkflowId]);

  // Global mousedown capture — logs what element receives every click in the real app.
  // Persists until component unmounts.
  useEffect(() => {
    const handler = (e) => {
      const el = document.elementFromPoint(e.clientX, e.clientY);
      const s = el ? window.getComputedStyle(el) : null;
      console.log("[GUI:CLICK_INTERCEPT]", {
        x: e.clientX,
        y: e.clientY,
        targetTag: e.target?.tagName,
        targetClass: e.target?.className?.toString?.().slice(0, 100),
        hitTag: el?.tagName,
        hitClass: el?.className?.toString?.().slice(0, 100),
        hitText: el?.textContent?.trim().slice(0, 50),
        hitPos: s?.position,
        hitZ: s?.zIndex,
        hitPE: s?.pointerEvents,
        timestamp: Date.now(),
      });
    };
    document.addEventListener('mousedown', handler, { capture: true });
    return () => document.removeEventListener('mousedown', handler, { capture: true });
  }, []);
  // === END TEMPORARY FORENSIC INSTRUMENTATION ===

  // === WORKFLOW CONTEXT HANDLING ===
  // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
  // Frontend derives workflow context from backend projection (lastResult)
  // No local workflow ownership synthesis or fallback logic
  // Backend provides authoritative workflow identity via projection

  // === ORPHAN INVALIDATION ===
  // Note: stopStreamPoll is now defined as useCallback above
  // Note: invalidateOrphanedWorkflow is now provided by useWorkflowSession hook
  // This reference is kept for stream poll callback compatibility

  function handleExecutionStart() {
    // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
    // Clear lastResult to indicate new execution starting
    // Backend will provide authoritative workflow identity in projection
    logFgAuth("execution_start", {
      priorWorkflowId: activeWorkflowId,
      priorBgId: activeBgIdRef.current,
      ...captureFgAuthState()
    });
    stopStreamPoll("new_execution_start");
    // Per OPERATOR_SESSION_CONTRACT_V1: clear session continuity marker — new execution
    // invalidates the previous workflow identity. New marker written by stream poll
    // once the new workflow ID first resolves.
    sessionStorage.removeItem(SESSION_CONTINUITY_KEY);
    console.trace("[FG_DETACH]", {
      reason: "new_execution_start",
      activeWorkflowId,
      bgId: activeBgIdRef.current,
      timestamp: Date.now(),
    });
    lastResultRef.current = null;
    setLastResult(null);
    // NOTE: Do NOT resetRuntimeActivity here — indicator must remain visible
    // during startup. Backend will update with new data via stream polling.
    log("EXECUTION_START", { lastResult: null });
  }

  function handleWorkflowSelect(workflow) {
    // Per WORKFLOW MANAGER UI: Explicit workflow selection by operator
    const bgId = workflow.bg_ids?.[0];
    const hasBgId = !!(workflow.recoverable && bgId);

    console.log("[GUI:HYDRATION_TRACE_SELECTION]", {
      phase: "selection_start",
      workflowId: workflow.workflow_id,
      status: workflow.status,
      recoverable: workflow.recoverable,
      bgId,
      hasBgId,
      action: "operator_explicit_selection",
      timestamp: Date.now(),
    });

    // === OPERATIONAL ATTACHMENT WITH STREAM CONTINUITY ===
    // If workflow has a bg_id (ACTIVE/running), restore stream polling for
    // live convergence. Otherwise use projection-only hydration (PAUSED, etc.)
    if (hasBgId) {
      console.log("[GUI:HYDRATION_TRACE_SELECTION]", {
        phase: "operational_attach_with_stream",
        workflowId: workflow.workflow_id,
        bgId,
        status: workflow.status,
        action: "stream_continuity_restore",
        timestamp: Date.now()
      });
      loadProjectionOnlyWorkflow(workflow.workflow_id, bgId);
    } else {
      console.log("[GUI:HYDRATION_TRACE_SELECTION]", {
        phase: "projection_only_workflow",
        workflowId: workflow.workflow_id,
        status: workflow.status,
        action: "projection_hydration_no_stream",
        timestamp: Date.now()
      });
      loadProjectionOnlyWorkflow(workflow.workflow_id, null);
    }
  }

  // === PROJECTION-ONLY WORKFLOW HYDRATION ===
  // Per PROJECTION-FIRST HYDRATION ALIGNMENT:
  // Load workflow view from canonical projection without runtime attachment.
  // If bgId provided (running workflow), stream polling is restored for live convergence.
  // If no bgId (PAUSED/etc), this is view-only hydration with projection polling only.
  async function loadProjectionOnlyWorkflow(workflowId, bgId = null) {
    // === FORENSIC LOG: ENTRY ===
    console.log("[FG_ATTACH:ENTRY]", {
      workflowId,
      bgId,
      continuityMarker: sessionStorage.getItem(SESSION_CONTINUITY_KEY),
      activeWorkflowId,
      currentBgId: activeBgIdRef.current,
      timestamp: Date.now(),
    });

    // Per LIFECYCLE_AUTHORITY_CONTRACT_V1 + PROJECTION_CONTINUITY_CONTRACT_V1:
    // Clear stale focusedProjection immediately before async fetch begins.
    // Without this, focusedProjection retains the PREVIOUS workflow's lifecycle_status
    // during the async fetch window, causing ControlPanel to derive legality from a
    // stale authority source (e.g. COMPLETED status from old workflow → Cancel hidden).
    // lastResult?.status serves as the correct fallback until focusedProjection updates.
    setFocusedProjection(null);
    console.log("[GUI:PROJECTION_HYDRATION_START]", {
      workflowId,
      bgId,
      hasStreamContext: !!bgId,
      phase: "fetching_projection",
      timestamp: Date.now()
    });

    try {
      // Stop any existing stream poll — will restart if bgId provided
      stopStreamPoll(bgId ? "stream_continuity_switch" : "projection_only_hydration");

      // Fetch authoritative canonical projection
      const projection = await api.getProjection(workflowId);

      // === FORENSIC LOG: PROJECTION FETCHED ===
      console.log("[FG_ATTACH:PROJECTION_FETCHED]", {
        workflowId,
        projectionWorkflowId: projection?.workflow_id,
        projectionLifecycle: projection?.lifecycle_status,
        timestamp: Date.now(),
      });

      if (!projection) {
        console.log("[GUI:PROJECTION_HYDRATION_FAIL]", {
          workflowId,
          reason: "projection_not_found",
          timestamp: Date.now()
        });
        console.trace("[FG_DETACH]", {
          reason: "projection_not_found",
          activeWorkflowId,
          bgId: activeBgIdRef.current,
          timestamp: Date.now(),
        });
        lastResultRef.current = null;
        setLastResult(null);
        return;
      }

      // === PROJECTION-ONLY STATE CONSTRUCTION ===
      // Construct result state from projection WITHOUT fabricating runtime ownership
      // Per PROJECTION_NON_AUTHORITY: projection is view-only, not runtime authority
      const projectionResult = {
        ...projection,
        workflow_id: workflowId,
        // Normalize canonical projection lifecycle_status to legacy status field
        // for backward compatibility with all downstream consumers.
        status: projection.lifecycle_status,
        // Explicit marker: hydration source and runtime context
        _hydrationSource: "projection_only",
        _runtimeContext: bgId ? "stream_active" : "none",
        _restoredBgId: bgId || null,
      };

      console.log("[GUI:PROJECTION_HYDRATION_COMMIT]", {
        workflowId,
        bgId,
        hasStreamContext: !!bgId,
        projectionVersion: projection.projection_version,
        projectionState: projection.projection_state,
        lifecycleStatus: projection.lifecycle_status,
        projectedStatus: projectionResult.status,
        hasSteps: !!(projection.steps && projection.steps.length > 0),
        timestamp: Date.now()
      });

      // === FORENSIC LOG: BEFORE OWNERSHIP COMMIT ===
      console.log("[FG_ATTACH:COMMITTING_OWNERSHIP]", {
        workflowId,
        bgId,
        timestamp: Date.now(),
      });

      lastResultRef.current = projectionResult;
      setLastResult(projectionResult);

      // === FORENSIC LOG: AFTER OWNERSHIP COMMIT ===
      console.log("[FG_ATTACH:OWNERSHIP_COMMITTED]", {
        workflowId,
        activeWorkflowIdAfter: workflowId,
        bgIdAfter: activeBgIdRef.current,
        continuityMarker: sessionStorage.getItem(SESSION_CONTINUITY_KEY),
        timestamp: Date.now(),
      });
      // Per OPERATOR_SESSION_CONTRACT_V1: stamp renderer-session continuity for this workflow.
      // Written on every successful projection hydration (Task Hub attach, operator selection,
      // and auto-restore) so refresh will rediscover the marker on next backendReady.
      sessionStorage.setItem(SESSION_CONTINUITY_KEY, workflowId);

      // === STREAM CONTINUITY RESTORATION ===
      // If bgId provided, restart stream polling for live convergence
      if (bgId) {
        // === FORENSIC LOG: STREAM RESTART ===
        console.log("[FG_ATTACH:STREAM_RESTART]", {
          workflowId,
          bgId,
          timestamp: Date.now(),
        });
        console.log("[GUI:STREAM_CONTINUITY_RESTORE]", {
          workflowId,
          bgId,
          action: "starting_stream_poll",
          timestamp: Date.now()
        });
        handleStreamStart(bgId);
      } else {
        // === FORENSIC LOG: STREAM SKIPPED ===
        console.log("[FG_ATTACH:STREAM_SKIPPED]", {
          workflowId,
          bgId,
          reason: "missing_bg_id",
          timestamp: Date.now(),
        });
      }

    } catch (err) {
      console.log("[GUI:PROJECTION_HYDRATION_ERROR]", {
        workflowId,
        error: err.message,
        timestamp: Date.now()
      });
      console.trace("[FG_DETACH]", {
        reason: "projection_hydration_error",
        activeWorkflowId,
        bgId: activeBgIdRef.current,
        timestamp: Date.now(),
      });
      lastResultRef.current = null;
      setLastResult(null);
    }
  }

  function handleNewWorkflowRequest() {
    // Per WORKFLOW MANAGER UI: New workflow creation requested
    console.log("[GUI:NEW_WORKFLOW_REQUEST]", {
      action: "new_workflow_from_manager",
      timestamp: Date.now(),
    });
    // Reset state to allow fresh workflow creation
    stopStreamPoll("new_workflow_request");
    sessionStorage.removeItem(SESSION_CONTINUITY_KEY);
    console.trace("[FG_DETACH]", {
      reason: "new_workflow_request",
      activeWorkflowId,
      bgId: activeBgIdRef.current,
      timestamp: Date.now(),
    });
    lastResultRef.current = null;
    setLastResult(null);
    // ChatPanel will handle the actual creation flow
  }

  function handleDetachWorkflow() {
    // Per GUI_FUNCTIONALITY_CONTRACT_V1 §FOCUSED WORKFLOW PERSISTENCE:
    // Explicit operator-controlled detachment.
    console.log("[GUI:DETACH_WORKFLOW]", {
      workflowId: activeWorkflowId,
      previousStatus: lastResultRef.current?.status,
      action: "explicit_detach",
      timestamp: Date.now(),
    });
    stopStreamPoll("explicit_detach");
    sessionStorage.removeItem(SESSION_CONTINUITY_KEY);
    console.trace("[FG_DETACH]", {
      reason: "explicit_detach_workflow",
      activeWorkflowId,
      bgId: activeBgIdRef.current,
      timestamp: Date.now(),
    });
    lastResultRef.current = null;
    setLastResult(null);
    setFocusedProjection(null); // Clear unified lifecycle source
    resetRuntimeActivity();
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
    expectedWorkflowIdRef.current = null; // reset rebinding guard on new stream attach
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

        // === PHASE 2: Runtime Activity Update ===
        // Per PHASE 4G-A.6: Extract backend-authoritative runtime_activity for global surface.
        if (wfData.runtime_activity) {
          updateRuntimeActivity(wfData.runtime_activity);
        }

        // PENDING means planning is still in progress (null workflow_id).
        // Per fixed stream schema: only PENDING, ACTIVE, COMPLETED, FAILED reach frontend.
        if (!wfData.workflow_id || wfData.status === "PENDING") {
          return;
        }

        // === WORKFLOW_ID REBINDING GUARD (PHASE XVI-A) ===
        // Per GUI_ARCHITECTURE.txt §STREAMING MODEL:
        // GUI MUST bind all updates to workflow_id without inferring authority.
        // Reject stream events that mutate workflow identity mid-stream.
        if (wfData.workflow_id) {
          if (!expectedWorkflowIdRef.current) {
            expectedWorkflowIdRef.current = wfData.workflow_id;
            // Per OPERATOR_SESSION_CONTRACT_V1: stamp renderer-session continuity when
            // workflow ID first resolves on stream (covers new workflow start path where
            // loadProjectionOnlyWorkflow has not yet been called).
            sessionStorage.setItem(SESSION_CONTINUITY_KEY, wfData.workflow_id);
            console.log("[GUI:WORKFLOW_ID_LOCK]", {
              workflowId: wfData.workflow_id,
              bgId,
              reason: "first_seen_on_stream",
              timestamp: Date.now(),
            });
          } else if (expectedWorkflowIdRef.current !== wfData.workflow_id) {
            console.log("[GUI:WORKFLOW_REBIND_REJECTED]", {
              expectedWorkflowId: expectedWorkflowIdRef.current,
              receivedWorkflowId: wfData.workflow_id,
              bgId,
              action: "rejected_stream_update",
              timestamp: Date.now(),
            });
            return;
          }
        }

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
          // Per RECOVERABLE TERMINAL SEMANTICS: FAILED is recoverable and MAY transition
          // to non-terminal via retry. Only immutable terminals (COMPLETED, CANCELLED)
          // are protected from reverting to non-terminal.
          const isImmutableTerminal = (status) => status === "COMPLETED" || status === "CANCELLED";
          const isAnyTerminal = (status) => isImmutableTerminal(status) || status === "FAILED";
          // Read current result from ref (not stale closure) to avoid false rejections
          const currentResult = lastResultRef.current;

          // Stale terminal overwrite prevention — uses ref not stale closure
          // Only immutable terminals are protected; FAILED may transition to ACTIVE on retry
          if (currentResult && isImmutableTerminal(currentResult.status) && !isAnyTerminal(wfData.status)) {
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

          // === HYDRATION TRACE: Result Commit ===
          console.log("[GUI:HYDRATION_TRACE_COMMIT]", {
            phase: "setLastResult",
            workflowId: terminalResult.workflow_id,
            status: terminalResult.status,
            hasResult: !!terminalResult,
            timestamp: Date.now()
          });

          lastResultRef.current = terminalResult;
          setLastResult(terminalResult);
        }

        // === LIVE PROPAGATION BRIDGE (RECONNECT FIX) ===
        // Per PROJECTION_CONTINUITY_CONTRACT_V1 §14: Stream carries authoritative lifecycle.
        // When wfData.result is absent but workflow_id exists, propagate stream status
        // to lastResult so legacy surfaces (WorkflowPanel, ExecutionPanel, Controls)
        // remain synchronized with live execution state.
        if (wfData.workflow_id && wfData.status) {
          const streamResult = {
            ...lastResultRef.current,
            workflow_id: wfData.workflow_id,
            status: wfData.status,
            ...(wfData.result || {}),
          };

          // Only update if state actually changed (avoid infinite re-render loops)
          const changed =
            JSON.stringify(streamResult) !==
            JSON.stringify(lastResultRef.current);

          if (changed && activeWorkflowId === workflowId) {
            console.log("[GUI:WORKFLOW_STATE_UPDATE]", {
              workflowId: wfData.workflow_id,
              previousState: lastResultRef.current?.status,
              nextState: wfData.status,
              source: "event_stream_live_propagation",
              timestamp: Date.now(),
            });

            lastResultRef.current = streamResult;
            setLastResult(streamResult);
          } else if (changed) {
            logFgAuth("stale_stream_result_suppressed", {
              polledWorkflowId: workflowId,
              activeWorkflowId,
              reason: "workflow_identity_mismatch",
              ...captureFgAuthState()
            });
          }
        }

        // REMOVED: stream-derived projection synthesis (minimalResult).
        // Per PROJECTION_CONTINUITY_CONTRACT_V1 §4: Hydration MUST NOT invent missing lifecycle state.
        // Frontend now waits for canonical projection from /projection/{workflow_id} only.
        // === TERMINAL STREAM SHUTDOWN ===
        // Per PROJECTION_CONTINUITY_CONTRACT_V1 §9: terminal states are continuity anchors.
        // Once terminal, stop the stream poll immediately — no further events expected.
        // PAUSED is NOT terminal (per STATE_TRANSITIONS_CONTRACT_V1: PAUSED → ACTIVE is valid).
        // Defense-in-depth: also check wfData.result?.status — covers race where wfData.status
        // lags behind the result payload (e.g. FIX-3 failure result with status:"FAILED").
        // Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1: CANCELLED is also terminal.
        const _terminalStatus = wfData.status === "COMPLETED" || wfData.status === "FAILED"
          || wfData.status === "CANCELLED"
          || wfData.result?.status === "COMPLETED" || wfData.result?.status === "FAILED";
        if (_terminalStatus) {
          const _resolvedStatus = wfData.status === "COMPLETED" || wfData.result?.status === "COMPLETED"
            ? "COMPLETED" : wfData.status === "CANCELLED" ? "CANCELLED" : "FAILED";
          logFgAuth("terminal_state_detected", {
            status: _resolvedStatus,
            workflowId: activeWorkflowId,
            bgId,
            activeBgIdRef: activeBgIdRef.current,
            ...captureFgAuthState()
          });
          console.log("[GUI:TERMINAL_STREAM_SHUTDOWN]", {
            bgId,
            workflowId: wfData.workflow_id,
            terminalStatus: _resolvedStatus,
            reason: "workflow_terminal",
            timestamp: Date.now()
          });
          stopStreamPoll("terminal_state", bgId);
          // Per LIFECYCLE_AUTHORITY_CONTRACT_V1 + CANCELLATION_CONTRACT:
          // Clear stale focusedProjection immediately on terminal detection.
          // Prevents pre-terminal ACTIVE projection from keeping controls in wrong state
          // during the projection convergence window (0-1000ms after stream termination).
          // lastResult?.status (set by live propagation above) serves as correct fallback.
          console.trace("[FG_DETACH]", {
            reason: "terminal_stream_shutdown_clear_projection",
            activeWorkflowId,
            bgId: activeBgIdRef.current,
            timestamp: Date.now(),
          });
          setFocusedProjection(null);
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
          // Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1:
          // Terminal states MUST release foreground ownership deterministically.
          // This prevents stale reattach attempts and foreground deadlock.
          // CRITICAL: Only clear ownership if this workflow still owns foreground.
          // Prevents stale async callbacks from clearing newer workflow ownership.
          if (activeWorkflowId === workflowId) {
            logFgAuth("terminal_ownership_release", {
              status: _resolvedStatus,
              workflowId,
              priorBgId: activeBgIdRef.current,
              ...captureFgAuthState()
            });
            sessionStorage.removeItem(SESSION_CONTINUITY_KEY);
            console.trace("[FG_DETACH]", {
              reason: "terminal_state_detected",
              activeWorkflowId,
              bgId: activeBgIdRef.current,
              timestamp: Date.now(),
            });
            selectWorkflow(null); // Clears activeWorkflowId
            activeBgIdRef.current = null;
            expectedWorkflowIdRef.current = null;
          } else {
            logFgAuth("terminal_cleanup_suppressed", {
              status: _resolvedStatus,
              terminalWorkflowId: workflowId,
              currentWorkflowId: activeWorkflowId,
              reason: "ownership_mismatch",
              ...captureFgAuthState()
            });
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
            // Per LIFECYCLE_AUTHORITY_CONTRACT_V1:
            // Clear focusedProjection BEFORE invalidation — invalidateOrphanedWorkflow
            // clears lastResult (workflowId→null) but does not clear focusedProjection.
            // Without this, status derives from stale focusedProjection while workflowId
            // is null, producing split legality: controls show wrong disabled/visible state.
            console.trace("[FG_DETACH]", {
              reason: "orphan_invalidation_clear_projection",
              activeWorkflowId,
              bgId: activeBgIdRef.current,
              timestamp: Date.now(),
            });
            setFocusedProjection(null);
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

  console.log(`[STARTUP_TRACE] Render gate check: backendError=${backendError}`);
  if (backendError) {
    console.log("[STARTUP_TRACE] RENDERING: Backend error screen");
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
            <button className="btn-primary" onClick={retry}>
              Retry
            </button>
          </div>
        </main>
      </div>
    );
  }

  console.log(`[STARTUP_TRACE] Render gate check: backendReady=${backendReady}`);
  if (!backendReady) {
    console.log("[STARTUP_TRACE] RENDERING: Loading spinner (backend not ready)");
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
  console.log("[STARTUP_TRACE] RENDERING: Main app content");

  console.log("[STARTUP_TRACE] RENDERING: Full app layout");
  return (
    <div className="app">
      <header className="app-header">
        <span className="logo">⬡ AI Lab</span>
        <WorkflowManager
          currentWorkflowId={activeWorkflowId}
          currentStatus={focusedProjection?.lifecycle_status || lastResult?.status}
          onWorkflowSelect={handleWorkflowSelect}
          onNewWorkflow={handleNewWorkflowRequest}
          onDetachWorkflow={handleDetachWorkflow}
          isExecuting={isExecuting}
        />
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
        {/* === GLOBAL TRANSIENT OPERATOR STATUS (PHASE 4G-A.6) === */}
        {/* Backend-authoritative runtime_activity — NOT projection metadata */}
        <div className="global-runtime-bar" style={{ padding: "0 16px", marginBottom: "4px" }}>
          <GlobalRuntimeStatus runtimeActivity={runtimeActivity} />
        </div>

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
            projection={focusedProjection}
          />
          <ExecutionPanel result={lastResult} debugMode={debugMode} />
        </div>

        {console.log("[CONTROL_SOURCE_AUDIT]", {
          activeWorkflowId,
          focusedProjectionLifecycle: focusedProjection?.lifecycle_status,
          focusedProjectionWorkflowId: focusedProjection?.workflow_id,
          focusedProjectionState: focusedProjection?.projection_state,
          lastResultStatus: lastResult?.status,
          lastResultWorkflowId: lastResult?.workflow_id,
          resolvedStatus: focusedProjection?.lifecycle_status || lastResult?.status,
          isExecuting,
          timestamp: Date.now(),
        })}
        <ControlPanel
          onBackgroundStart={handleBackgroundStart}
          onResumeStreamStart={handleResumeStreamStart}
          onPause={stopStreamPoll}
          workflowId={activeWorkflowId}
          status={focusedProjection?.lifecycle_status || lastResult?.status}
        />

        {/* Per CANONICAL_PROJECTION_MODEL_V1: Canonical Projection Rendering Pipeline (SUB-PHASE 3A) */}
        {/* Renders ONLY from orchestrator-owned canonical WorkflowProjection via GET /projection/{workflowId} */}
        {/* workflowId derived from backend projection — no local synthesis */}
        {activeWorkflowId && (
          <WorkflowProjectionView
            workflowId={activeWorkflowId}
            isExecuting={isExecuting}
            showPlanView={true}
            onOrphan={(reason) => {
              console.trace("[FG_DETACH]", {
                reason: `workflow_projection_view_orphan:${reason}`,
                activeWorkflowId,
                bgId: activeBgIdRef.current,
                timestamp: Date.now(),
              });
              setFocusedProjection(null); // Clear unified lifecycle source
              invalidateOrphanedWorkflow(reason, activeWorkflowId);
            }}
            onProjectionUpdate={setFocusedProjection}
          />
        )}

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
