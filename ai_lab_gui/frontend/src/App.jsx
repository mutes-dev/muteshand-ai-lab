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
import BudgetStatus from "./components/BudgetStatus.jsx";
import ExecutionPanel from "./components/ExecutionPanel.jsx";
import ControlPanel from "./components/ControlPanel.jsx";
import BackgroundPanel from "./components/BackgroundPanel.jsx";
import ApprovalPanel from "./components/ApprovalPanel.jsx";
import UserControlPanel from "./components/UserControlPanel.jsx";
import NotificationBanner from "./components/NotificationBanner.jsx";
import UnreadIndicator from "./components/UnreadIndicator.jsx";
import WorkflowManagementShell from "./components/WorkflowManagementShell.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import HistoryInspector from "./components/HistoryInspector.jsx";
import MemoryPanel from "./components/MemoryPanel.jsx";
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
// Per ISSUE-055: execution-context bridge for pre-workflow_id planning window.
// Preserved before workflow_id is known; cleared once workflow_id is locked on stream.
const SESSION_BG_ID_KEY = "wf_session_pending_bg_id";
// Per ISSUE-061 Phase 4C: preserve selected historical workflow across refresh
const HISTORY_SELECTED_KEY = "history_selected_workflow_id";

// Foreground refresh restore eligibility: all inspectable workflow statuses.
// Must be inspectability-based, NOT recoverability-based.
// BLOCKED is included because user-control workflows must remain
// attachable/controllable after refresh (ISSUE-098KX).
const FOREGROUND_RESTORE_STATUSES = new Set([
  "ACTIVE",
  "ACTIVATING",
  "PAUSED",
  "QUEUED",
  "BLOCKED",
  "FAILED",
  "CANCELLED",
  "COMPLETED",
]);

// Terminal statuses that preserve the foreground marker after terminalization
// so refresh can reattach them for inspection-only viewing.
const INSPECTABLE_TERMINAL_STATUSES = new Set([
  "FAILED",
  "CANCELLED",
  "COMPLETED",
]);

// Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
// - Frontend is projection-only
// - All lifecycle state derives from backend projection
// - Frontend does NOT synthesize lifecycle state locally
// - Frontend does NOT infer workflow ownership

export default function App() {

  const [debugMode, setDebugMode] = useState(false);
  const [memoryPanelOpen, setMemoryPanelOpen] = useState(() => {
    try { return localStorage.getItem("memory_panel_open") === "true"; } catch { return false; }
  });
  const [bgRefresh, setBgRefresh] = useState(0);
  const [runtimeInspectData, setRuntimeInspectData] = useState(null);
  // === FOCUSED WORKFLOW LIFECYCLE SOURCE UNIFICATION (PHASE 4A) ===
  // Per LIFECYCLE_AUTHORITY_CONTRACT_V1: All focused-workflow surfaces MUST
  // consume the same authoritative lifecycle source. Projection is the
  // canonical source; lastResult is stream-derived and may lag.
  const [focusedProjection, setFocusedProjection] = useState(null);
  const [projectionRefreshTrigger, setProjectionRefreshTrigger] = useState(0);

  // Cancel response buffer for authoritative backend terminal states
  // Ensures CANCELLED convergence during projection fetch errors
  const [cancelResponseBuffer, setCancelResponseBuffer] = useState(null);

  // ISSUE-055B Phase 2 Correction: preserve selected workflow metadata from Task Hub
  // so downstream components (WorkflowProjectionView, WorkflowPanel) can see
  // actionability fields like projection_expected_missing without re-fetching.
  const [selectedWorkflowMetadata, setSelectedWorkflowMetadata] = useState(null);

  // ISSUE-061 Phase 4C: History Inspector state (separate from runtime foreground)
  const [selectedHistoricalWorkflowId, setSelectedHistoricalWorkflowId] = useState(null);
  const [selectedHistoricalWorkflow, setSelectedHistoricalWorkflow] = useState(null);



  // === REFS (MUST BE DEFINED BEFORE HOOKS THAT USE THEM) ===
  const streamPollRef = useRef(null);
  const activeBgIdRef = useRef(null);
  const consecutive404Ref = useRef(0);

  // === PHASE 1: Backend Readiness Extraction ===
  // Per APP_JSX_DECOUPLING_ARCHITECTURE_AUDIT.md:
  // Backend readiness is isolated, non-authoritative, safe to extract.
  const { isReady: backendReady, isLoading: backendLoading, isUnavailable: backendUnavailable, isIdentityMismatch: backendIdentityMismatch, error: backendError, retry } = useBackendReadiness();
  console.log(`[STARTUP_TRACE] useBackendReadiness: backendReady=${backendReady}, isLoading=${backendLoading}, isUnavailable=${backendUnavailable}`);

  // === PHASE 2: Runtime Activity Extraction ===
  // Per APP_JSX_DECOUPLING_ARCHITECTURE_AUDIT.md:
  // Runtime observability is backend-authoritative, safe to extract.
  const { runtimeActivity, updateRuntimeActivity, resetRuntimeActivity } = useRuntimeActivity();
  console.log(`[STARTUP_TRACE] useRuntimeActivity: runtimeActivity=${JSON.stringify(runtimeActivity)}`);

  // === STREAM LIFECYCLE CALLBACKS (must be before hooks that use them) ===
  const stopStreamPoll = useCallback((reason = "unknown", bgId = null) => {
    if (streamPollRef.current) {
      clearInterval(streamPollRef.current);
      streamPollRef.current = null;

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
    authoritativeProjectionStatus: focusedProjection?.lifecycle_status || null,
  });

  // === CENTRALIZED RESOLVED WORKFLOW STATUS ===
  // Compute one resolved status for all foreground display/session consumers
  // Ensures cancel response buffer precedence across all UI surfaces
  const resolvedWorkflowStatus = getResolvedStatus(activeWorkflowId);

  // Compute finalIsExecuting directly from resolvedWorkflowStatus
  // Ensures CANCELLED shows isExecuting=false while preserving genuine ACTIVE behavior
  const finalIsExecuting = resolvedWorkflowStatus === "ACTIVE" ||
    resolvedWorkflowStatus === "ACTIVATING" ||
    resolvedWorkflowStatus === "PENDING_RECOVERY";

  // === AUTHORITY-FIRST RESTORATION (PHASE XVI-A) ===
  // Triggered when backend becomes ready
  useEffect(() => {
    if (!backendReady) {

      return;
    }

    // Per SYSTEM_CONVERGENCE_AND_RECOVERY_CONTRACT_V1 §10:
    // Recovery MUST converge from authority downward.
    // Per LIFECYCLE_AUTHORITY_CONTRACT_V1 §WORKFLOW ENUMERATION RULES:
    // Frontend MUST NOT infer workflow existence heuristically.
    // Per GUI_ARCHITECTURE.txt §WORKFLOW SELECTION BOUNDARY:
    // Frontend MUST NOT assume singleton workflow recovery.

    api.getAuthoritativeWorkflows()
      .then(async (res) => {
        const workflows = res.workflows || [];
        const recoverable = workflows.filter((w) => w.recoverable === true);


        // === ATTACHMENT PRESERVATION GUARD ===
        // Per GUI_FUNCTIONALITY_CONTRACT_V1 §FOCUSED WORKFLOW PERSISTENCE:
        // Focused workflow attachment persists until explicitly detached or another
        // workflow explicitly attached. Reconnect hydration MUST NOT implicitly sever.
        const currentWorkflowId = lastResultRef.current?.workflow_id;
        if (currentWorkflowId) {
          const currentEntry = workflows.find((w) => w.workflow_id === currentWorkflowId);
          if (currentEntry) {

            return;
          }
          // Current workflow not in backend list — orphaned, proceed with recovery

        }

        // ISSUE-057: Read continuity marker early so FAILED (not backend-recoverable)
        // can bypass the no-recoverable early return.
        const continuityMarker = sessionStorage.getItem(SESSION_CONTINUITY_KEY);
        const markerWorkflow = continuityMarker
          ? workflows.find((w) => w.workflow_id === continuityMarker)
          : null;
        const hasContinuityRestoreCandidate =
          markerWorkflow &&
          FOREGROUND_RESTORE_STATUSES.has(markerWorkflow.status);

        if (recoverable.length === 0 && !hasContinuityRestoreCandidate) {
          // No recoverable workflows — clear any stale execution lock.
          if (lastResultRef.current !== null) {

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
        const matchingWorkflow = markerWorkflow;
        if (continuityMarker && matchingWorkflow) {
          // Per GUI_FUNCTIONALITY_CONTRACT_V1: PAUSED workflows are operational and
          // must preserve continuity equivalently to ACTIVE workflows.
          const isEligibleForAutoRestore =
            FOREGROUND_RESTORE_STATUSES.has(matchingWorkflow.status) &&
            !isQueuedReplanRequired(matchingWorkflow);
          if (isEligibleForAutoRestore) {
            const bgId = matchingWorkflow.bg_ids?.[0] || null;

            // ISSUE-062 FIX: Propagate backend-authored actionability metadata (retry_eligible,
            // failed_recoverable, etc.) so ControlPanel receives retryEligible after refresh/reopen.
            // Mirrors handleWorkflowSelect line — setSelectedWorkflowMetadata must be called
            // in every path that calls loadProjectionOnlyWorkflow with an authoritative workflow entry.
            setSelectedWorkflowMetadata(matchingWorkflow);
            loadProjectionOnlyWorkflow(matchingWorkflow.workflow_id, bgId, matchingWorkflow.status);
            // [AUTH:SESSION_RESTORE] Auto-restore path

            return;
          }
        }

        // === ISSUE-098KY: HISTORICAL RESTORE FOR TERMINAL WORKFLOWS ===
        // If continuity marker exists but workflow is not in authoritative list,
        // it may be a terminal workflow (COMPLETED/CANCELLED) in workflows.json.
        // Attempt restore from historical endpoint before falling through to detach.
        if (continuityMarker && !matchingWorkflow) {
          try {
            const histRes = await api.getHistoricalWorkflows();
            const histList = histRes.workflows || [];
            const histWf = histList.find((w) => w.workflow_id === continuityMarker);
            const terminalStatuses = new Set(["COMPLETED", "CANCELLED", "FAILED"]);
            if (histWf && terminalStatuses.has(histWf.status)) {

              setSelectedWorkflowMetadata(histWf);
              loadProjectionOnlyWorkflow(histWf.workflow_id, null, histWf.status);

              return;
            }
          } catch (_histErr) {
            // Historical restore failure is non-fatal — fall through to explicit selection
          }
        }

        // === ISSUE-055: BG_ID DISCOVERY BRIDGE ===
        // If no continuity marker but a pending bg_id exists, attempt ONE-TIME
        // stream discovery to recover workflow_id from the execution context.
        // This bridges the planning-phase gap where workflow_id is not yet on stream.
        const pendingBgId = sessionStorage.getItem(SESSION_BG_ID_KEY);
        if (pendingBgId && !continuityMarker) {

          try {
            const streamData = await api.streamWorkflowId(pendingBgId);



            // CASE 1: Planning still in progress — start stream polling, preserve bridge
            if (!streamData?.workflow_id && streamData?.status === "PENDING") {

              handleStreamStart(pendingBgId);
              return;
            }

            // CASE 2: Stream returned workflow_id — attempt authoritative match
            if (streamData?.workflow_id) {
              const discoveredWf = recoverable.find(
                (w) => w.workflow_id === streamData.workflow_id
              );



              if (discoveredWf) {
                const isEligible =
                  discoveredWf.status === "ACTIVE" ||
                  discoveredWf.status === "ACTIVATING" ||
                  discoveredWf.status === "PAUSED" ||
                  discoveredWf.status === "BLOCKED" ||
                  (discoveredWf.status === "QUEUED" && !isQueuedReplanRequired(discoveredWf)) ||
                  discoveredWf.status === "FAILED";
                if (isEligible) {
                  // Write canonical marker and proceed with existing auto-restore path
                  sessionStorage.setItem(SESSION_CONTINUITY_KEY, streamData.workflow_id);
                  sessionStorage.removeItem(SESSION_BG_ID_KEY);

                  // ISSUE-062 FIX: Same propagation as auto-restore path above —
                  // bg_id_discovery_bridge also has authoritative workflow entry (discoveredWf)
                  // and must populate selectedWorkflowMetadata for ControlPanel retry metadata.
                  setSelectedWorkflowMetadata(discoveredWf);
                  loadProjectionOnlyWorkflow(discoveredWf.workflow_id, pendingBgId, discoveredWf.status);

                  return;
                }
              }

              // workflow_id present but not in recoverable or not eligible — clear bridge
              sessionStorage.removeItem(SESSION_BG_ID_KEY);

              return;
            }
          } catch (err) {
            const is404 = err?.message && (
              err.message.includes("404") ||
              err.message.includes("Not Found") ||
              err.message.includes("bg_id not found")
            );

            if (is404) {
              sessionStorage.removeItem(SESSION_BG_ID_KEY);

            }
          }
        }
        // No continuity marker (cold boot), marker mismatch,
        // or matching workflow non-eligible (BLOCKED/PENDING_RECOVERY):
        // require explicit Task Hub selection.

        // Clear any stale attachment — Task Hub will display recoverable workflows
        lastResultRef.current = null;
        setLastResult(null);
      })
      .catch(() => {
        // Recovery fetch failure is non-fatal — frontend continues in idle state.
      });
  }, [backendReady]);

  // === DEBUG OBSERVABILITY — RUNTIME INSPECT SURFACING ===
  // Per OBSERVABILITY_AND_DASHBOARD_ARCHITECTURE_CONTRACT_V1:
  // Debug-only visibility of execution_generation and retry_lineage.
  // Non-authoritative rendering only — MUST NOT drive control logic.
  useEffect(() => {
    if (!debugMode || !activeWorkflowId) {
      setRuntimeInspectData(null);
      return;
    }
    let cancelled = false;
    api.runtimeInspect(activeWorkflowId)
      .then((data) => {
        if (!cancelled) {
          setRuntimeInspectData(data);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRuntimeInspectData(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [debugMode, activeWorkflowId]);

  // === ISSUE-061 Phase 4C: History inspection restore across refresh ===
  useEffect(() => {
    if (!backendReady) return;
    const storedId = sessionStorage.getItem(HISTORY_SELECTED_KEY);
    if (!storedId) return;
    api.getHistoricalWorkflows()
      .then((res) => {
        const list = res.workflows || [];
        const found = list.find((w) => w.workflow_id === storedId);
        if (found) {
          setSelectedHistoricalWorkflowId(storedId);
          setSelectedHistoricalWorkflow(found);

        } else {
          sessionStorage.removeItem(HISTORY_SELECTED_KEY);

        }
      })
      .catch(() => {
        // Non-fatal: history restore failure should not block app startup
      });
  }, [backendReady]);

  // === [AUTH:RUNTIME_SNAPSHOT] Consolidated authority visibility ===
  useEffect(() => {

  }, [activeWorkflowId, lastResult, runtimeActivity, focusedProjection, finalIsExecuting]);

  // === FIX 1: PROJECTION-DERIVED RUNTIME ACTIVITY FALLBACK (ISSUE-056) ===
  // Per PROJECTION_CONTINUITY_CONTRACT_V1 + OBSERVABILITY_AND_DASHBOARD_ARCHITECTURE_CONTRACT_V1:
  // When stream polling stops (e.g., on pause), runtimeActivity freezes at pre-pause value.
  // Projection poll continues and includes runtime_activity read from authoritative runtime registry.
  // This effect passively consumes projection runtime_activity as downstream observability only.
  // NO lifecycle synthesis. NO authority escalation. NO backend mutation.
  useEffect(() => {
    if (focusedProjection?.runtime_activity) {
      updateRuntimeActivity(focusedProjection.runtime_activity);
    }
  }, [focusedProjection?.runtime_activity, updateRuntimeActivity]);

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

      // Hit-test the Pause button
      const btns = Array.from(document.querySelectorAll('button'));
      const pauseBtn = btns.find(b => b.textContent?.trim().includes('Pause'));
      if (pauseBtn) {
        const rect = pauseBtn.getBoundingClientRect();
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const top = document.elementFromPoint(cx, cy);

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

  // === ISSUE-055B Phase 2: Safe actionability helpers ===
  // All helpers tolerate missing backend fields (backward compat with old workflows)
  function getActionability(workflow) {
    if (workflow && typeof workflow.actionability === "string") {
      return workflow.actionability;
    }
    if (workflow?.inspection_only === true) return "INSPECTION_ONLY";
    if (workflow?.recoverable === true) return "RUNTIME_RECOVERABLE";
    return "INSPECTION_ONLY";
  }

  function isQueuedReplanRequired(workflow) {
    if (!workflow) return false;
    if (workflow.status !== "QUEUED") return false;
    if (workflow.actionability === "PLANNING_REPLAN") return true;
    if (workflow.planning_actionability === "REPLAN_REQUIRED") return true;
    return false;
  }

  function isQueuedLivePlanning(workflow) {
    if (!workflow) return false;
    if (workflow.status !== "QUEUED") return false;
    if (workflow.live_planning === true) return true;
    if (workflow.actionability === "LIVE_PLANNING") return true;
    return false;
  }

  function shouldStartStreamPolling(workflow, bgId) {
    if (!bgId) return false;
    if (workflow?.stale_bg_id === true) return false;
    if (isQueuedReplanRequired(workflow)) return false;
    return true;
  }

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
    lastResultRef.current = null;
    setLastResult(null);
    setSelectedWorkflowMetadata(null);
    // NOTE: Do NOT resetRuntimeActivity here — indicator must remain visible
    // during startup. Backend will update with new data via stream polling.
    log("EXECUTION_START", { lastResult: null });
  }

  async function handleWorkflowSelect(workflow) {
    // Per WORKFLOW MANAGER UI: Explicit workflow selection by operator
    // ISSUE-055B Phase 2 Correction: preserve full metadata for downstream projection/event polling guards
    // ISSUE-061 Phase 4C: Selecting a runtime workflow clears historical inspection
    handleClearHistoricalInspection();
    setSelectedWorkflowMetadata(workflow);
    const bgId = workflow.bg_ids?.[0];
    const hasBgId = shouldStartStreamPolling(workflow, bgId);
    const isPendingRecovery = workflow.status === "PENDING_RECOVERY";



    // === TASK HUB AUTHORITY PRESERVATION ===
    // Extract authoritative status from Task Hub workflow object
    const knownStatus = workflow?.status || null;


    // === AUTHORITY-FIRST RECOVERY ACTIVATION ===
    // Per RECOVERY ACTIVATION CORRECTION: PENDING_RECOVERY workflows MUST be
    // authoritatively resumed BEFORE projection hydration. Projection must NEVER
    // imply execution or derive control legality without runtime confirmation.
    if (isPendingRecovery) {

      try {
        const res = await api.resume(workflow.workflow_id);

        // Hydrate projection ONLY after authoritative resume confirms ACTIVE.
        // Use bg_id from resume response to attach stream polling.
        loadProjectionOnlyWorkflow(workflow.workflow_id, res.bg_id || null);
      } catch (err) {

        // Fallback: hydrate without stream so user can inspect workflow state
        loadProjectionOnlyWorkflow(workflow.workflow_id, null, knownStatus);
      }
      return;
    }

    // === OPERATIONAL ATTACHMENT WITH STREAM CONTINUITY ===
    // If workflow has a bg_id (ACTIVE/running), restore stream polling for
    // live convergence. Otherwise use projection-only hydration (PAUSED, etc.)
    if (hasBgId) {

      loadProjectionOnlyWorkflow(workflow.workflow_id, bgId, knownStatus);
    } else {

      loadProjectionOnlyWorkflow(workflow.workflow_id, null, knownStatus);
    }
  }

  // === ISSUE-055B Phase 3: OPERATOR-INITIATED REPLAN ===
  async function handleReplan(workflowId) {

    try {
      const res = await api.replanWorkflow(workflowId);

      // Immediately update selected metadata to live planning so UI
      // transitions from "Planning Interrupted" to "Planning..." state.
      setSelectedWorkflowMetadata((prev) => {
        if (!prev || prev.workflow_id !== workflowId) return prev;
        return {
          ...prev,
          actionability: "LIVE_PLANNING",
          planning_actionability: "LIVE_PLANNING",
          live_planning: true,
          replan_eligible: false,
          stale_bg_id: false,
          projection_expected_missing: true,
          taskhub_action: null,
          action_label: null,
        };
      });

      // Attach stream polling for the new bg_id.
      if (res.bg_id) {
        handleStreamStart(res.bg_id);
      }

      // Trigger a refresh of the workflow list so Task Hub updates.
      // We rely on the existing TaskHubTab polling for this, but
      // we can also force a re-check of the list if needed.
    } catch (err) {
      // Re-throw so TaskHubTab can clear its local replanning state
      throw err;
    }
  }

  // === PROJECTION-ONLY WORKFLOW HYDRATION ===
  // Per PROJECTION-FIRST HYDRATION ALIGNMENT:
  // Load workflow view from canonical projection without runtime attachment.
  // If bgId provided (running workflow), stream polling is restored for live convergence.
  // If no bgId (PAUSED/etc), this is view-only hydration with projection polling only.
  /**
   * @param {string|null} knownStatus — authoritative status from
   *        /workflows/authoritative; enables planning-phase tolerance.
   */
  async function loadProjectionOnlyWorkflow(workflowId, bgId = null, knownStatus = null) {

    // Per LIFECYCLE_AUTHORITY_CONTRACT_V1 + PROJECTION_CONTINUITY_CONTRACT_V1:
    // Clear stale focusedProjection immediately before async fetch begins.
    // Without this, focusedProjection retains the PREVIOUS workflow's lifecycle_status
    // during the async fetch window, causing ControlPanel to derive legality from a
    // stale authority source (e.g. COMPLETED status from old workflow → Cancel hidden).
    // lastResult?.status serves as the correct fallback until focusedProjection updates.
    setFocusedProjection(null);

    try {
      // Stop any existing stream poll — will restart if bgId provided
      stopStreamPoll(bgId ? "stream_continuity_switch" : "projection_only_hydration");

      // Fetch authoritative canonical projection
      const projection = await api.getProjection(workflowId);


      if (!projection) {
        if (knownStatus) {
          // Planning-phase tolerance: projection not yet emitted but backend
          // confirms workflow exists (knownStatus from authoritative list).
          // Seed minimal identity so stream convergence can proceed.
          const minimalResult = {
            workflow_id: workflowId,
            status: knownStatus,
            _hydrationSource: "projection_minimal_seed",
            _runtimeContext: bgId ? "stream_active" : "none",
            _restoredBgId: bgId || null,
          };
          lastResultRef.current = minimalResult;
          setLastResult(minimalResult);
          sessionStorage.setItem(SESSION_CONTINUITY_KEY, workflowId);
          if (bgId) { handleStreamStart(bgId); }
          return;
        }
        // Existing detach for paths without knownStatus
        lastResultRef.current = null;
        setLastResult(null);
        return;
      }

      // === PROJECTION-ONLY STATE CONSTRUCTION ===
      // Construct result state from projection WITHOUT fabricating runtime ownership
      // Per PROJECTION_NON_AUTHORITY: projection is view-only, not runtime authority
      // Preserve authoritative terminal status - projection must not override terminal lifecycle state
      const TERMINAL_STATUSES = new Set(["CANCELLED", "COMPLETED", "FAILED"]);
      const resolvedHydrationStatus = TERMINAL_STATUSES.has(knownStatus)
        ? knownStatus
        : projection.lifecycle_status;

      // Log status resolution for debugging
      if (knownStatus && knownStatus !== resolvedHydrationStatus) {
      }

      const projectionResult = {
        ...projection,
        workflow_id: workflowId,
        // Use preserved terminal status or projection lifecycle_status for non-terminal
        status: resolvedHydrationStatus,
        // Explicit marker: hydration source and runtime context
        _hydrationSource: "projection_only",
        _runtimeContext: bgId ? "stream_active" : "none",
        _restoredBgId: bgId || null,
      };

      // === [AUTH:HYDRATION] Authority trace before commit ===



      lastResultRef.current = projectionResult;
      setLastResult(projectionResult);

      // Per OPERATOR_SESSION_CONTRACT_V1: stamp renderer-session continuity for this workflow.
      // Written on every successful projection hydration (Task Hub attach, operator selection,
      // and auto-restore) so refresh will rediscover the marker on next backendReady.
      sessionStorage.setItem(SESSION_CONTINUITY_KEY, workflowId);

      // === STREAM CONTINUITY RESTORATION ===
      // If bgId provided, restart stream polling for live convergence
      if (bgId) {
        handleStreamStart(bgId);
      } else {
      }

    } catch (err) {
      const is404 = err?.message && (
        err.message.includes("404") ||
        err.message.includes("Not Found") ||
        err.message.includes("workflow not found") ||
        err.message.includes("projection_not_found")
      );
      if (is404 && knownStatus) {
        // Transient projection absence during planning window.
        // Seed minimal identity; projection polling continues independently.
        const minimalResult = {
          workflow_id: workflowId,
          status: knownStatus,
          _hydrationSource: "projection_minimal_seed",
          _runtimeContext: bgId ? "stream_active" : "none",
          _restoredBgId: bgId || null,
        };
        lastResultRef.current = minimalResult;
        setLastResult(minimalResult);
        sessionStorage.setItem(SESSION_CONTINUITY_KEY, workflowId);
        if (bgId) { handleStreamStart(bgId); }
        return;
      }
      // Non-404 errors or paths without knownStatus: existing detach
      console.log("[GUI:PROJECTION_HYDRATION_ERROR]", {
        workflowId,
        error: err.message,
        timestamp: Date.now()
      });
      lastResultRef.current = null;
      setLastResult(null);
    }
  }

  function handleNewWorkflowRequest() {
    // Per WORKFLOW MANAGER UI: New workflow creation requested

    // Reset state to allow fresh workflow creation
    stopStreamPoll("new_workflow_request");
    sessionStorage.removeItem(SESSION_CONTINUITY_KEY);
    lastResultRef.current = null;
    setLastResult(null);
    setSelectedWorkflowMetadata(null);
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
    sessionStorage.removeItem(SESSION_BG_ID_KEY);
    lastResultRef.current = null;
    setLastResult(null);
    setFocusedProjection(null); // Clear unified lifecycle source
    setSelectedWorkflowMetadata(null);
    resetRuntimeActivity();
  }

  // === ISSUE-061 Phase 4C: HISTORY INSPECTION (NOT foreground attachment) ===
  function handleInspectHistoricalWorkflow(workflow) {
    // Historical inspection is read-only. Does NOT attach as foreground.
    // Does NOT call /execute/stream, /resume, /replan, retry, archive, or dismiss.
    setSelectedHistoricalWorkflowId(workflow.workflow_id);
    setSelectedHistoricalWorkflow(workflow);
    sessionStorage.setItem(HISTORY_SELECTED_KEY, workflow.workflow_id);
    console.log("[GUI:HISTORY_INSPECT]", {
      workflowId: workflow.workflow_id,
      timestamp: Date.now(),
    });
  }

  function handleClearHistoricalInspection() {
    setSelectedHistoricalWorkflowId(null);
    setSelectedHistoricalWorkflow(null);
    sessionStorage.removeItem(HISTORY_SELECTED_KEY);
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
    // Per ISSUE-055: Persist bg_id before workflow_id exists to bridge planning window.
    // Cleared when workflow_id is locked on stream; never used for arbitrary attachment.
    sessionStorage.setItem(SESSION_BG_ID_KEY, bgId);
    activeBgIdRef.current = bgId;
    expectedWorkflowIdRef.current = null; // reset rebinding guard on new stream attach
    console.log("[GUI:STREAM_ATTACH]", {
      bgId,
      streamOwner: "handleStreamStart",
      timestamp: Date.now()
    });
    // === PERF036: stream poll attach ===
    const _p036_stream_attach_ts = Date.now();
    let _p036_poll_count = 0;
    let _p036_first_result_logged = false;
    try {
      console.log("PERF036_FRONTEND " + JSON.stringify({
        label: "stream_poll_attach",
        source_layer: "App_handleStreamStart",
        timestamp_iso: new Date().toISOString(),
        timestamp_ms: _p036_stream_attach_ts,
        bg_id: bgId,
      }));
    } catch (e) { }
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
        // === PERF036: poll count ===
        _p036_poll_count += 1;
        const wfData = await api.streamWorkflowId(bgId);
        // Successful fetch — reset orphan counter.
        consecutive404Ref.current = 0;
        // === PERF036: first non-PENDING result received ===
        try {
          if (!_p036_first_result_logged && wfData && wfData.status !== "PENDING") {
            _p036_first_result_logged = true;
            console.log("PERF036_FRONTEND " + JSON.stringify({
              label: "stream_first_result_received",
              source_layer: "App_streamPoll",
              timestamp_iso: new Date().toISOString(),
              timestamp_ms: Date.now(),
              elapsed_since_attach_ms: Date.now() - _p036_stream_attach_ts,
              poll_count: _p036_poll_count,
              bg_id: bgId,
              workflow_id: wfData.workflow_id || null,
              status: wfData.status,
            }));
          }
        } catch (e) { }

        // === PHASE 2: Runtime Activity Update ===
        // Per PHASE 4G-A.6: Extract backend-authoritative runtime_activity for global surface.
        if (wfData.runtime_activity) {
          updateRuntimeActivity(wfData.runtime_activity);
        }

        // [AUTH:STREAM_RECONCILE] Detect stream dormant vs UI ACTIVE mismatch
        if (wfData.status === "PENDING" && lastResultRef.current?.status && lastResultRef.current.status !== "PENDING") {
          console.log("[AUTH:STREAM_RECONCILE]", {
            workflowId: lastResultRef.current?.workflow_id,
            stream_status: wfData.status,
            lastResult_status: lastResultRef.current?.status,
            runtimeActivity: wfData.runtime_activity || null,
            poll_action_taken: "early_return_no_state_update",
            mismatch: "stream_dormant_ui_active",
            timestamp: Date.now(),
          });
        }

        // === WORKFLOW_ID REBINDING GUARD (PHASE XVI-A) ===
        // Per ISSUE-055: Acknowledge workflow_id and stamp continuity marker
        // BEFORE the PENDING early-return. Marker must survive refresh window.
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
            // Per ISSUE-055: bg_id bridge is no longer needed; canonical continuity takes over.
            sessionStorage.removeItem(SESSION_BG_ID_KEY);

            // === MINIMAL SEED: Close gap window for planning-phase refresh ===
            // When workflow_id first appears on stream but result is not yet available,
            // lastResultRef remains null → activeWorkflowId stays null → live propagation
            // bridge blocks. Seed minimal identity so foreground attaches immediately.
            if (
              !lastResultRef.current &&
              !wfData.result &&
              (wfData.status === "ACTIVE" ||
                wfData.status === "ACTIVATING" ||
                wfData.status === "PENDING_RECOVERY")
            ) {
              const minimalSeed = {
                workflow_id: wfData.workflow_id,
                status: wfData.status,
                _hydrationSource: "stream_identity_minimal_seed",
                _runtimeContext: "stream_active",
                _restoredBgId: bgId || null,
              };
              lastResultRef.current = minimalSeed;
              setLastResult(minimalSeed);
              console.log("[GUI:MINIMAL_SEED]", {
                workflowId: wfData.workflow_id,
                status: wfData.status,
                bgId,
                reason: "identity_lock_first_workflow_id_null_lastResult",
                timestamp: Date.now(),
              });
            }

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

        // PENDING means planning is still in progress or bootstrap states active.
        // State updates below remain suppressed during PENDING; only identity
        // lock above executes.
        if (!wfData.workflow_id || wfData.status === "PENDING") {
          return;
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
            status: wfData.status || wfData.result?.status,
            // ISSUE-057 FIX E+F: Propagate projection enrichment fields from stream/poll data
            retry_target_step_id: wfData.retry_target_step_id || wfData.result?.retry_target_step_id || null,
            failure_reason: wfData.failure_reason || wfData.result?.failure_reason || null,
            failed_step_id: wfData.failed_step_id || wfData.result?.failed_step_id || null,
            failed_step_label: wfData.failed_step_label || wfData.result?.failed_step_label || null,
            last_successful_output: wfData.last_successful_output || wfData.result?.last_successful_output || null,
            last_successful_step_id: wfData.last_successful_step_id || wfData.result?.last_successful_step_id || null,
          };

          // === HYDRATION TRACE: Result Commit ===
          console.log("[GUI:HYDRATION_TRACE_COMMIT]", {
            phase: "setLastResult",
            workflowId: terminalResult.workflow_id,
            status: terminalResult.status,
            hasResult: !!terminalResult,
            timestamp: Date.now()
          });

          // === GUI_SYNC_FIX: Trigger projection refresh on meaningful stream update ===
          // Per GUI_SYNCHRONIZATION_AUDIT_REPORT.md: stream poll updates lastResult but
          // did not inform the projection pipeline, causing Workflow rows to lag.
          const prevResult = lastResultRef.current;
          const meaningfulChange =
            !prevResult ||
            prevResult.status !== terminalResult.status ||
            (prevResult.steps?.length || 0) !== (terminalResult.steps?.length || 0) ||
            (prevResult.outputs?.length || 0) !== (terminalResult.outputs?.length || 0);

          lastResultRef.current = terminalResult;
          setLastResult(terminalResult);
          // === PERF036: final result rendered ===
          try {
            console.log("PERF036_FRONTEND " + JSON.stringify({
              label: "final_result_rendered",
              source_layer: "App_streamPoll",
              timestamp_iso: new Date().toISOString(),
              timestamp_ms: Date.now(),
              elapsed_since_attach_ms: Date.now() - _p036_stream_attach_ts,
              poll_count: _p036_poll_count,
              bg_id: bgId,
              workflow_id: terminalResult.workflow_id || null,
              status: terminalResult.status,
            }));
          } catch (e) { }

          if (meaningfulChange && activeWorkflowId === terminalResult.workflow_id) {
            handleForceProjectionRefresh();
          }
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
            // ISSUE-057 FIX E+F: Propagate projection enrichment fields from stream data
            retry_target_step_id: wfData.retry_target_step_id || wfData.result?.retry_target_step_id || lastResultRef.current?.retry_target_step_id || null,
            failure_display_message: wfData.failure_display_message || wfData.result?.failure_display_message || lastResultRef.current?.failure_display_message || null,
            failure_reason: wfData.failure_reason || wfData.result?.failure_reason || lastResultRef.current?.failure_reason || null,
            failed_step_id: wfData.failed_step_id || wfData.result?.failed_step_id || lastResultRef.current?.failed_step_id || null,
            failed_step_label: wfData.failed_step_label || wfData.result?.failed_step_label || lastResultRef.current?.failed_step_label || null,
            last_successful_output: wfData.last_successful_output || wfData.result?.last_successful_output || lastResultRef.current?.last_successful_output || null,
            last_successful_step_id: wfData.last_successful_step_id || wfData.result?.last_successful_step_id || lastResultRef.current?.last_successful_step_id || null,
          };

          // Only update if state actually changed (avoid infinite re-render loops)
          const changed =
            JSON.stringify(streamResult) !==
            JSON.stringify(lastResultRef.current);

          if (changed && activeWorkflowId === wfData.workflow_id) {
            console.log("[GUI:WORKFLOW_STATE_UPDATE]", {
              workflowId: wfData.workflow_id,
              previousState: lastResultRef.current?.status,
              nextState: wfData.status,
              source: "event_stream_live_propagation",
              timestamp: Date.now(),
            });

            lastResultRef.current = streamResult;
            setLastResult(streamResult);
            // === GUI_SYNC_FIX: Inform projection pipeline on status-only stream update ===
            handleForceProjectionRefresh();
          } else if (changed) {
            logFgAuth("stale_stream_result_suppressed", {
              polledWorkflowId: wfData.workflow_id,
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
          || wfData.result?.status === "COMPLETED" || wfData.result?.status === "FAILED"
          || wfData.result?.status === "CANCELLED";
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
          // === PERF036: terminal stream stop ===
          try {
            console.log("PERF036_FRONTEND " + JSON.stringify({
              label: "stream_terminal_stop",
              source_layer: "App_streamPoll",
              timestamp_iso: new Date().toISOString(),
              timestamp_ms: Date.now(),
              elapsed_since_attach_ms: Date.now() - _p036_stream_attach_ts,
              total_poll_count: _p036_poll_count,
              bg_id: bgId,
              workflow_id: wfData.workflow_id || null,
              terminal_status: _resolvedStatus,
            }));
          } catch (e) { }
          stopStreamPoll("terminal_state", bgId);
          // Per LIFECYCLE_AUTHORITY_CONTRACT_V1 + CANCELLATION_CONTRACT:
          // Clear stale focusedProjection immediately on terminal detection.
          // Prevents pre-terminal ACTIVE projection from keeping controls in wrong state
          // during the projection convergence window (0-1000ms after stream termination).
          // lastResult?.status (set by live propagation above) serves as correct fallback.
          setFocusedProjection(null);
          if (_resolvedStatus === "FAILED") {
            // ISSUE-057 FIX 3b: Fetch projection to enrich terminal failure display.
            // Stream payload lacks projection-computed metadata; projection has it.
            // ISSUE-092B: Preserve enriched failure reason from lastResult — do not degrade to generic.
            let _enriched = null;
            try {
              _enriched = await api.getProjection(wfData.workflow_id);
            } catch (_projErr) {
              console.log("[GUI:TERMINAL_PROJECTION_FETCH_FAIL]", {
                workflowId: wfData.workflow_id,
                error: _projErr.message,
                timestamp: Date.now(),
              });
            }

            // Preserve authoritative "FAILED" (uppercase) — WorkflowPanel isTerminal checks "FAILED".
            // Do NOT downcase to "failure": that broke WorkflowPanel poll-shutdown (RR-2).
            // FIX D (Phase 1B): canonical reason derivation hierarchy — "Unknown error" MUST NOT
            // appear when a canonical reason exists anywhere in the workflow payload.
            // ISSUE-092B: Use existing lastResult reason first (from enriched stream result),
            // then projection, then wfData, then fallback.
            const _failedStep = (wfData.steps || []).find(
              s => s.status === "FAILED" || s.status === "BLOCKED"
            );
            const _existingReason = lastResultRef.current?.failure_reason || lastResultRef.current?.reason;
            const _wfDataReason = wfData.error || wfData.result?.reason || wfData.reason;
            // ISSUE-098N: Frontend does NOT inspect blocked_reason directly.
            // Use execution_result.reason or backend-provided error metadata only.
            const _stepReason = _failedStep?.execution_result?.reason || _failedStep?.error;
            const _canonicalReason = _existingReason || _wfDataReason || _stepReason || "workflow_failed";

            setLastResult(prev => ({
              ...prev,
              status: "FAILED",
              // ISSUE-092B: Preserve specific planner failure reason if already enriched
              reason: _enriched?.failure_reason || _canonicalReason,
              // ISSUE-057 FIX E+F: Propagate projection enrichment fields if available
              // ISSUE-092B: Preserve pre-step failure metadata from existing lastResult
              retry_target_step_id: _enriched?.retry_target_step_id || prev?.retry_target_step_id || wfData.retry_target_step_id || null,
              failure_display_message: _enriched?.failure_display_message || prev?.failure_display_message || wfData.failure_display_message || null,
              failure_reason: _enriched?.failure_reason || prev?.failure_reason || wfData.failure_reason || _canonicalReason,
              failed_step_id: _enriched?.failed_step_id || prev?.failed_step_id || wfData.failed_step_id || null,
              failed_step_label: _enriched?.failed_step_label || prev?.failed_step_label || wfData.failed_step_label || null,
              last_successful_output: _enriched?.last_successful_output || prev?.last_successful_output || wfData.last_successful_output || null,
              last_successful_step_id: _enriched?.last_successful_step_id || prev?.last_successful_step_id || wfData.last_successful_step_id || null,
              // ISSUE-092B: Preserve retry eligibility from enriched result
              retry_eligible: _enriched?.retry_eligible ?? prev?.retry_eligible ?? wfData.retry_eligible ?? null,
              failed_recoverable: _enriched?.failed_recoverable ?? prev?.failed_recoverable ?? wfData.failed_recoverable ?? null,
              retry_disabled_reason: _enriched?.retry_disabled_reason || prev?.retry_disabled_reason || wfData.retry_disabled_reason || null,
            }));
          }
          // Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1:
          // Terminal states MUST release foreground ownership deterministically.
          // This prevents stale reattach attempts and foreground deadlock.
          // CRITICAL: Only clear ownership if this workflow still owns foreground.
          // Prevents stale async callbacks from clearing newer workflow ownership.
          if (activeWorkflowId === wfData.workflow_id) {
            logFgAuth("terminal_ownership_release", {
              status: _resolvedStatus,
              workflowId: wfData.workflow_id,
              priorBgId: activeBgIdRef.current,
              ...captureFgAuthState()
            });
            // Preserve foreground marker for all inspectable terminal workflows
            // (FAILED, CANCELLED, COMPLETED) so refresh can reattach for inspection.
            if (!INSPECTABLE_TERMINAL_STATUSES.has(_resolvedStatus)) {
              sessionStorage.removeItem(SESSION_CONTINUITY_KEY);
            }
            selectWorkflow(null); // Clears activeWorkflowId
            activeBgIdRef.current = null;
            expectedWorkflowIdRef.current = null;
          } else {
            logFgAuth("terminal_cleanup_suppressed", {
              status: _resolvedStatus,
              terminalWorkflowId: wfData.workflow_id,
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
            // === ISSUE-098KY: Terminal workflows preserve lastResult on bg_id deregistration ===
            const currentStatus = lastResultRef.current?.status;
            const isTerminal = currentStatus === "COMPLETED" || currentStatus === "CANCELLED" || currentStatus === "FAILED";
            if (isTerminal) {
              // Terminal workflow: bg_id was deregistered after completion.
              // Stop polling but preserve lastResult so ExecutionPanel remains visible.
              stopStreamPoll("terminal_bg_id_deregistered", bgId);
              activeBgIdRef.current = null;
              console.log("[GUI:TERMINAL_STREAM_END]", {
                workflowId: lastResultRef.current?.workflow_id,
                status: currentStatus,
                reason: "bg_id_deregistered_after_terminal",
                timestamp: Date.now(),
              });
            } else {
              // Per LIFECYCLE_AUTHORITY_CONTRACT_V1:
              // Clear focusedProjection BEFORE invalidation — invalidateOrphanedWorkflow
              // clears lastResult (workflowId→null) but does not clear focusedProjection.
              // Without this, status derives from stale focusedProjection while workflowId
              // is null, producing split legality: controls show wrong disabled/visible state.
              setFocusedProjection(null);
              invalidateOrphanedWorkflow(
                `stream_poll_consecutive_404:${consecutive404Ref.current}`,
                lastResultRef.current?.workflow_id
              );
            }
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

  function handleForceProjectionRefresh() {
    setProjectionRefreshTrigger((n) => n + 1);
  }

  function handleWorkflowCancelled(response) {
    // Handle authoritative backend cancel response for display convergence
    if (response?.status === "success" &&
      response?.new_state === "CANCELLED" &&
      response?.workflow_id) {

      console.log("[GUI:WORKFLOW_CANCELLED_HANDLED]", {
        workflowId: response.workflow_id,
        new_state: response.new_state,
        previous_state: response.previous_state,
        timestamp: Date.now()
      });

      // Buffer the authoritative CANCELLED state to ensure convergence during projection fetch errors
      setCancelResponseBuffer({
        workflow_id: response.workflow_id,
        new_state: response.new_state,
        previous_state: response.previous_state,
        timestamp: Date.now()
      });
    }
  }

  function getResolvedStatus(workflowId) {
    // Status precedence for display/session convergence
    // 1. Backend-confirmed terminal state from cancel response (highest precedence)
    // 2. Terminal lastResult.status for same workflow (selected Task Hub authority)
    // 3. Focused projection lifecycle status (canonical source for non-terminal)
    // 4. Non-terminal last result status (fallback)
    // 5. Runtime activity status (fallback)

    const cancelBuffer = cancelResponseBuffer?.workflow_id === workflowId ? cancelResponseBuffer : null;
    const projectionStatus = focusedProjection?.lifecycle_status;
    const lastResultStatus = lastResult?.status;
    const lastResultWorkflowId = lastResult?.workflow_id;
    const runtimeStatus = runtimeActivity ? "ACTIVE" : null;

    const TERMINAL_STATUSES = new Set(["CANCELLED", "COMPLETED", "FAILED"]);

    // If we have a backend-confirmed CANCELLED state, it takes precedence
    if (cancelBuffer?.new_state === "CANCELLED") {
      console.log("[GUI:RESOLVED_STATUS]", {
        workflowId,
        resolvedStatus: "CANCELLED",
        source: "cancel_response_buffer",
        precedence: 1,
        timestamp: Date.now()
      });
      return "CANCELLED";
    }

    // Terminal lastResult.status beats focusedProjection for same workflow
    if (lastResultStatus && lastResultWorkflowId === workflowId && TERMINAL_STATUSES.has(lastResultStatus)) {
      console.log("[GUI:RESOLVED_STATUS]", {
        workflowId,
        resolvedStatus: lastResultStatus,
        source: "terminal_last_result",
        precedence: 2,
        timestamp: Date.now()
      });
      return lastResultStatus;
    }

    // Use projection status if available (canonical source for non-terminal)
    if (projectionStatus) {
      console.log("[GUI:RESOLVED_STATUS]", {
        workflowId,
        resolvedStatus: projectionStatus,
        source: "focused_projection",
        precedence: 3,
        timestamp: Date.now()
      });
      return projectionStatus;
    }

    // Use non-terminal last result status as fallback
    if (lastResultStatus && lastResultWorkflowId === workflowId && !TERMINAL_STATUSES.has(lastResultStatus)) {
      console.log("[GUI:RESOLVED_STATUS]", {
        workflowId,
        resolvedStatus: lastResultStatus,
        source: "non_terminal_last_result",
        precedence: 4,
        timestamp: Date.now()
      });
      return lastResultStatus;
    }

    // Use runtime status as final fallback
    if (runtimeStatus) {
      console.log("[GUI:RESOLVED_STATUS]", {
        workflowId,
        resolvedStatus: runtimeStatus,
        source: "runtime_activity",
        precedence: 5,
        timestamp: Date.now()
      });
      return runtimeStatus;
    }

    // No status available
    console.log("[GUI:RESOLVED_STATUS]", {
      workflowId,
      resolvedStatus: null,
      source: "none",
      precedence: 5,
      timestamp: Date.now()
    });
    return null;
  }

  function handleProjectionUpdate(projection) {
    // Update projection and clear cancel response buffer when projection catches up
    setFocusedProjection(projection);

    // If projection shows CANCELLED and matches our buffered response, clear the buffer
    if (projection?.lifecycle_status === "CANCELLED" &&
      cancelResponseBuffer?.workflow_id === projection.workflow_id &&
      cancelResponseBuffer?.new_state === "CANCELLED") {
      console.log("[GUI:CANCEL_BUFFER_CLEARED]", {
        workflowId: projection.workflow_id,
        reason: "projection_caught_up_with_cancelled",
        projectionStatus: projection.lifecycle_status,
        timestamp: Date.now()
      });
      setCancelResponseBuffer(null);
    }
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

  console.log(`[STARTUP_TRACE] Render gate check: backendIdentityMismatch=${backendIdentityMismatch}, backendError=${backendError}`);
  if (backendIdentityMismatch) {

    return (
      <div className="app">
        <header className="app-header">
          <span className="logo">⬡ AI Lab</span>
        </header>
        <main className="layout">
          <div className="startup-error">
            <h2>⚠ Backend Already Running on Port 8000</h2>
            <p>{backendError}</p>
            <p className="muted">
              Possible causes:
              <br />• Another AI Lab backend is running from Windsurf or a terminal
              <br />• A stale backend from a previous dev session is still alive
              <br />• Another process is using port 8000
            </p>
            <p className="muted">
              Close the external backend or restart cleanly, then try again.
            </p>
            <button className="btn-primary" onClick={retry}>
              Retry
            </button>
          </div>
        </main>
      </div>
    );
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
      <NotificationBanner focusedWorkflowId={activeWorkflowId} />

      <header className="app-header">
        <span className="logo">⬡ AI Lab</span>
        <UnreadIndicator />
        <button
          className="memory-toggle-btn"
          onClick={() => setMemoryPanelOpen((prev) => {
            const next = !prev;
            try { localStorage.setItem("memory_panel_open", String(next)); } catch { /* non-fatal */ }
            return next;
          })}
          style={{
            marginLeft: "auto",
            marginRight: "12px",
            padding: "6px 12px",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            background: memoryPanelOpen ? "var(--accent)" : "var(--surface-2)",
            color: memoryPanelOpen ? "#fff" : "var(--text)",
            fontSize: "13px",
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          {memoryPanelOpen ? "Hide Memory" : "Memory"}
        </button>
        <label className="debug-toggle">
          <input
            type="checkbox"
            checked={debugMode}
            onChange={(e) => setDebugMode(e.target.checked)}
          />
          Debug Mode
        </label>
      </header>

      <main className="layout with-workflow-shell">
        {/* === WORKFLOW MANAGEMENT SHELL (PHASE 1) === */}
        <WorkflowManagementShell
          currentWorkflowId={activeWorkflowId}
          currentStatus={resolvedWorkflowStatus}
          onWorkflowSelect={handleWorkflowSelect}
          onNewWorkflow={handleNewWorkflowRequest}
          onDetachWorkflow={handleDetachWorkflow}
          isExecuting={finalIsExecuting}
          onReplan={handleReplan}
          onInspectWorkflow={handleInspectHistoricalWorkflow}
          selectedHistoricalWorkflowId={selectedHistoricalWorkflowId}
        />

        {/* === MAIN CONTENT AREA === */}
        <div className="main-content-area">
          {/* === GLOBAL TRANSIENT OPERATOR STATUS (PHASE 4G-A.6) === */}
          {/* Backend-authoritative runtime_activity — NOT projection metadata */}
          <div className="global-runtime-bar" style={{ padding: "0 16px", marginBottom: "4px" }}>
            <GlobalRuntimeStatus runtimeActivity={runtimeActivity} />
            <BudgetStatus />
          </div>

          {/* === PENDING REATTACHMENT UX INDICATOR (ISSUE-055) === */}
          {/* UX-only: informs operator during the narrow refresh reattachment window.
              Does NOT affect restore logic. Auto-clears when lastResult arrives,
              activeWorkflowId resolves, or SESSION_BG_ID_KEY is removed. */}
          {(() => {
            const hasPendingBgId = !!sessionStorage.getItem(SESSION_BG_ID_KEY);
            const pendingReattach = hasPendingBgId && !lastResult && !activeWorkflowId;
            return pendingReattach ? (
              <div className="planning-notice reattach-notice" role="status" aria-live="polite">
                <span className="spinner-inline" aria-hidden="true" />
                <span>
                  <strong>Reattaching workflow…</strong>
                  <span className="notice-sub" style={{ marginLeft: 8 }}>
                    Restoring your running workflow. This usually takes a few seconds.
                  </span>
                </span>
              </div>
            ) : null;
          })()}

          {/* === QUEUED/PLANNING STATUS BANNER (ISSUE-061 + ISSUE-092B FIX) === */}
          {/* Restores Sprint 2 visibility for QUEUED/planning workflows in main workspace */}
          {/* ISSUE-092B: Also clear when terminal FAILED/COMPLETED/CANCELLED result received */}
          {(() => {
            // Show planning banner when we have an active workflow but no projection/result yet
            // and the workflow status is QUEUED (planning/awaiting projection)
            // ISSUE-055B Phase 2: suppress false live spinner for dead QUEUED shells.
            const hasActiveWorkflow = !!activeWorkflowId;
            const hasNoProjection = !focusedProjection && !lastResult;
            const isActivating = resolvedWorkflowStatus === "ACTIVATING";
            const isQueued = resolvedWorkflowStatus === "QUEUED";
            // For QUEUED: only show spinner when live stream evidence exists
            // (activeBgIdRef means stream polling is active or about to start).
            // Dead QUEUED_REPLAN_REQUIRED has no bg_id and no stream polling.
            const isLiveQueued = isQueued && !!activeBgIdRef.current;
            const isQueuedOrPlanning = isLiveQueued || isActivating;
            // ISSUE-092B: Do NOT show Planning if terminal result already received
            // (pre-step planner failure arrives as FAILED without projection)
            // Check both lastResult and resolvedWorkflowStatus for terminal states.
            const isTerminalLastResult = lastResult?.status === "FAILED" ||
              lastResult?.status === "COMPLETED" ||
              lastResult?.status === "CANCELLED";
            const isTerminalResolvedStatus = resolvedWorkflowStatus === "FAILED" ||
              resolvedWorkflowStatus === "COMPLETED" ||
              resolvedWorkflowStatus === "CANCELLED";
            const isTerminal = isTerminalLastResult || isTerminalResolvedStatus;

            return hasActiveWorkflow && hasNoProjection && isQueuedOrPlanning && !isTerminal ? (
              <div className="planning-notice queued-notice" role="status" aria-live="polite">
                <span className="spinner-inline" aria-hidden="true" />
                <span>
                  <strong>Preparing workflow steps…</strong>
                  <span className="notice-sub" style={{ marginLeft: 8 }}>
                    Your workflow is queued and being prepared for execution.
                  </span>
                </span>
              </div>
            ) : null;
          })()}

          {/* === HISTORY INSPECTOR (ISSUE-061 Phase 4C) === */}
          {/* Replaces main workspace with read-only historical inspection. */}
          {/* Does NOT attach as foreground. Does NOT call /execute/stream, /resume, /replan. */}
          {selectedHistoricalWorkflowId ? (
            <HistoryInspector
              workflow={selectedHistoricalWorkflow}
              onClose={handleClearHistoricalInspection}
            />
          ) : (
            <>
              <ChatPanel
                onResult={handleResult}
                onExecutionStart={handleExecutionStart}
                onStreamStart={handleStreamStart}
                isExecuting={finalIsExecuting}
                pendingReattach={!!sessionStorage.getItem(SESSION_BG_ID_KEY) && !lastResult && !activeWorkflowId}
              />

              <div className="mid-row">
                <WorkflowPanel
                  result={lastResult}
                  isExecuting={finalIsExecuting}
                  projection={focusedProjection}
                  resolvedWorkflowStatus={resolvedWorkflowStatus}
                  selectedWorkflowMetadata={selectedWorkflowMetadata}
                  onRequestProjectionRefresh={() => {
                    setProjectionRefreshTrigger((prev) => prev + 1);
                  }}
                />
                <ExecutionPanel result={lastResult} status={resolvedWorkflowStatus} debugMode={debugMode} />
              </div>

              {console.log("[CONTROL_SOURCE_AUDIT]", {
                activeWorkflowId,
                focusedProjectionLifecycle: focusedProjection?.lifecycle_status,
                focusedProjectionWorkflowId: focusedProjection?.workflow_id,
                focusedProjectionState: focusedProjection?.projection_state,
                lastResultStatus: lastResult?.status,
                lastResultWorkflowId: lastResult?.workflow_id,
                resolvedStatus: focusedProjection?.lifecycle_status || lastResult?.status,
                isExecuting: finalIsExecuting,
                timestamp: Date.now(),
              })}
              {/* [AUTH:CONTROL_LEGALITY] Control legality with runtimeActivity context */}
              {(() => {
                const _cpStatus = focusedProjection?.lifecycle_status || lastResult?.status;
                const _cpCanPause = activeWorkflowId && _cpStatus === "ACTIVE";
                const _cpCanResume = activeWorkflowId && (_cpStatus === "PAUSED" || _cpStatus === "PENDING_RECOVERY");
                if (_cpStatus === "ACTIVE" || _cpStatus === "PENDING_RECOVERY") {
                  console.log("[AUTH:CONTROL_LEGALITY]", {
                    workflow_id: activeWorkflowId,
                    status: _cpStatus,
                    runtimeActivity: runtimeActivity || null,
                    canPause: _cpCanPause,
                    canResume: _cpCanResume,
                    legality_source: "projection_status",
                    lifecycle_source: focusedProjection ? "focusedProjection" : "lastResult",
                    mismatch: _cpStatus === "ACTIVE" && !runtimeActivity,
                    timestamp: Date.now(),
                  });
                }
                return null;
              })()}
              <ControlPanel
                onBackgroundStart={handleBackgroundStart}
                onResumeStreamStart={handleResumeStreamStart}
                onPause={stopStreamPoll}
                onForceProjectionRefresh={handleForceProjectionRefresh}
                onWorkflowCancelled={handleWorkflowCancelled}
                workflowId={activeWorkflowId}
                status={resolvedWorkflowStatus}
                pendingReattach={!!sessionStorage.getItem(SESSION_BG_ID_KEY) && !lastResult && !activeWorkflowId}
                // === ISSUE-062: Backend-authored FAILED actionability metadata ===
                // Precedence: focusedProjection (currently hydrated projection — most current)
                //           → lastResult (projection spread by loadProjectionOnlyWorkflow)
                //           → selectedWorkflowMetadata (authoritative list entry — can be stale)
                // All three sources are backend/projection-authored. No local synthesis.
                // selectedWorkflowMetadata is last because /workflows/authoritative can return
                // retry_eligible=false (e.g. stale entry) while the projection correctly has
                // retry_eligible=true. The currently loaded projection is the authoritative view.
                retryEligible={
                  focusedProjection?.retry_eligible ??
                  lastResult?.retry_eligible ??
                  selectedWorkflowMetadata?.retry_eligible
                }
                failedRecoverable={
                  focusedProjection?.failed_recoverable ??
                  lastResult?.failed_recoverable ??
                  selectedWorkflowMetadata?.failed_recoverable
                }
                retryDisabledReason={
                  focusedProjection?.retry_disabled_reason ??
                  lastResult?.retry_disabled_reason ??
                  selectedWorkflowMetadata?.retry_disabled_reason
                }
                // === ISSUE-092B: Pass retry/failed step IDs for retry button visibility ===
                retryTargetStepId={
                  focusedProjection?.retry_target_step_id ??
                  lastResult?.retry_target_step_id ??
                  selectedWorkflowMetadata?.retry_target_step_id
                }
                failedStepId={
                  focusedProjection?.failed_step_id ??
                  lastResult?.failed_step_id ??
                  selectedWorkflowMetadata?.failed_step_id
                }
                // === ISSUE-098A: Force retry candidate metadata ===
                forceRetryCandidate={
                  focusedProjection?.force_retry_candidate ??
                  lastResult?.force_retry_candidate ??
                  selectedWorkflowMetadata?.force_retry_candidate
                }
                forceRetryRemaining={
                  focusedProjection?.force_retry_remaining ??
                  lastResult?.force_retry_remaining ??
                  selectedWorkflowMetadata?.force_retry_remaining
                }
                forceRetryDisabledReason={
                  focusedProjection?.force_retry_disabled_reason ??
                  lastResult?.force_retry_disabled_reason ??
                  selectedWorkflowMetadata?.force_retry_disabled_reason
                }
              />

              {/* Per CANONICAL_PROJECTION_MODEL_V1: Canonical Projection Rendering Pipeline (SUB-PHASE 3A) */}
              {/* Renders ONLY from orchestrator-owned canonical WorkflowProjection via GET /projection/{workflowId} */}
              {/* workflowId derived from backend projection — no local synthesis */}
              {activeWorkflowId && (
                <WorkflowProjectionView
                  workflowId={activeWorkflowId}
                  isExecuting={finalIsExecuting}
                  showPlanView={true}
                  triggerRefresh={projectionRefreshTrigger}
                  resolvedWorkflowStatus={resolvedWorkflowStatus}
                  selectedWorkflowMetadata={selectedWorkflowMetadata}
                  onOrphan={(reason) => {
                    setFocusedProjection(null); // Clear unified lifecycle source
                    invalidateOrphanedWorkflow(reason, activeWorkflowId);
                  }}
                  onProjectionUpdate={handleProjectionUpdate}
                />
              )}

              <BackgroundPanel
                triggerRefresh={bgRefresh}
              />

              <ApprovalPanel workflowId={activeWorkflowId} />

              <UserControlPanel
                workflowId={activeWorkflowId}
                workflowMetadata={selectedWorkflowMetadata}
              />

              {memoryPanelOpen && (
                <MemoryPanel />
              )}

              {debugMode && lastResult && (
                <section className="panel debug-panel">
                  <h2>Raw Workflow JSON</h2>
                  <pre className="json-dump">{JSON.stringify(lastResult, null, 2)}</pre>
                  {runtimeInspectData && (
                    <>
                      <h2>Runtime Inspect (Observability Only)</h2>
                      <pre className="json-dump">{JSON.stringify(runtimeInspectData, null, 2)}</pre>
                    </>
                  )}
                </section>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
