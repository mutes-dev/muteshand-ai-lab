/**
 * USE WORKFLOW SESSION — PHASE 3 GUARDED EXTRACTION
 *
 * Per APP_JSX_DECOUPLING_ARCHITECTURE_AUDIT.md:
 * MEDIUM-RISK extraction of session coordination.
 *
 * Authority: LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1
 *
 * CRITICAL SAFETY NOTICE:
 * This hook extracts SESSION COORDINATION ONLY.
 * All safety guards are preserved EXACTLY as in original App.jsx.
 * ANY CHANGE TO GUARD LOGIC IS PROHIBITED.
 *
 * RESPONSIBILITIES:
 * - Workflow selection coordination
 * - Recoverable workflow loading
 * - Hydration/recovery logic (with guards)
 * - Orphan invalidation coordination
 * - Session cleanup/reset
 * - Workflow selector state
 *
 * NOT RESPONSIBLE FOR:
 * - Projection polling (WorkflowProjectionView owns this)
 * - Runtime/event-stream (WorkflowPanel owns this)
 * - Stream polling (App.jsx orchestrates this)
 * - Lifecycle authority (backend owns this)
 *
 * This extraction is MEDIUM-RISK because:
 * - Touches workflow identity
 * - Contains critical safety guards
 * - Involves hydration ordering
 * - Affects stale workflow prevention
 *
 * GUARDS THAT MUST BE PRESERVED:
 * 1. Paused workflow guard
 * 2. Active execution guard
 * 3. Stale resurrection prevention
 * 4. Orphan invalidation timing
 * 5. Recoverable workflow validation
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "../api.js";

/**
 * useWorkflowSession — GUARDED session coordination hook
 *
 * Manages workflow selection, recovery, and session state.
 * Preserves all safety guards from original App.jsx implementation.
 *
 * @param {Object} options
 * @param {boolean} options.backendReady — backend readiness state
 * @param {Function} options.resetRuntimeActivity — runtime activity reset callback
 * @param {Function} options.stopStreamPoll — stream poll stop callback
 * @returns {Object} Session state and coordinators
 */
export function useWorkflowSession({
  backendReady,
  resetRuntimeActivity,
  stopStreamPoll,
}) {
  console.log("[STARTUP_TRACE] useWorkflowSession hook initializing");
  // === SESSION STATE ===
  // lastResult: stores the last workflow result from ChatPanel execution
  // This is the authoritative source for activeWorkflowId derivation
  const [lastResult, setLastResult] = useState(null);

  // Recoverable workflows from backend (for startup restoration)
  const [recoverableWorkflows, setRecoverableWorkflows] = useState([]);

  // Workflow selector visibility state
  const [showWorkflowSelector, setShowWorkflowSelector] = useState(false);

  // Refs for stable identity and transition detection
  const expectedWorkflowIdRef = useRef(null);
  const lastResultRef = useRef(null);
  const isMountedRef = useRef(true);

  // Keep refs synchronized
  useEffect(() => {
    lastResultRef.current = lastResult;
  }, [lastResult]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // === DERIVED STATE ===
  // Derive activeWorkflowId from backend projection (projection-only)
  const activeWorkflowId = lastResult?.workflow_id || null;

  // Derive execution state
  const isExecuting = lastResult?.status === "ACTIVE";

  // === GUARDED SESSION RECOVERY (PHASE XVI-A) ===
  // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
  // Frontend derives workflow context from backend projection
  // NO local workflow ownership synthesis
  useEffect(() => {
    console.log(`[STARTUP_TRACE] useWorkflowSession hydration effect triggered, backendReady=${backendReady}`);
    if (!backendReady || !isMountedRef.current) {
      console.log(`[STARTUP_TRACE] Early return: backendReady=${backendReady}, isMounted=${isMountedRef.current}`);
      return;
    }
    console.log("[STARTUP_TRACE] Beginning workflow session recovery...");

    const storedWorkflowId = localStorage.getItem("activeWorkflowId");

    console.log("[STARTUP_TRACE] Fetching recoverable workflows...");
    api
      .getRecoverableWorkflows()
      .then((response) => {
        if (!isMountedRef.current) {
          console.log("[STARTUP_TRACE] Recoverable workflows: unmounted, aborting");
          return;
        }
        console.log(`[STARTUP_TRACE] Recoverable workflows fetched: count=${(response.workflows || []).length}`);

        const recoverable = response.workflows || [];
        setRecoverableWorkflows(recoverable);

        // === STALE WORKFLOW RESURRECTION PREVENTION ===
        // Validate stored workflow exists in recoverable list
        if (storedWorkflowId) {
          const storedWorkflow = recoverable.find(
            (w) => w.workflow_id === storedWorkflowId
          );

          if (storedWorkflow) {
            // === PAUSED WORKFLOW GUARD ===
            // Don't auto-restore paused workflows
            // Require explicit user action via WorkflowManager
            if (storedWorkflow.status === "PAUSED") {
              console.log("[GUI:HYDRATION_TRACE_PAUSED_WORKFLOW_SUPPRESSED]", {
                workflowId: storedWorkflowId,
                reason: "paused_workflow_requires_explicit_selection",
                storedStatus: storedWorkflow.status,
                timestamp: Date.now(),
              });
              // Clear stored workflow — don't auto-restore
              localStorage.removeItem("activeWorkflowId");
              lastResultRef.current = null;
              setLastResult(null);
              setShowWorkflowSelector(false);
              return;
            }

            // === ACTIVE WORKFLOW RESTORATION ===
            // Auto-restore active/completed workflows
            console.log("[GUI:HYDRATION_TRACE_RECOVERABLE_ACTIVE]", {
              workflowId: storedWorkflowId,
              status: storedWorkflow.status,
              action: "auto_restore_active_workflow",
              timestamp: Date.now(),
            });

            expectedWorkflowIdRef.current = storedWorkflowId;
            lastResultRef.current = { workflow_id: storedWorkflowId };
            setLastResult({ workflow_id: storedWorkflowId });
            setShowWorkflowSelector(false);
            return;
          } else {
            // Stored workflow not recoverable — clear it
            console.log("[GUI:HYDRATION_TRACE_STALE_WORKFLOW_CLEARED]", {
              workflowId: storedWorkflowId,
              reason: "not_in_recoverable_list",
              timestamp: Date.now(),
            });
            localStorage.removeItem("activeWorkflowId");
            lastResultRef.current = null;
            setLastResult(null);
          }
        }

        console.log("[STARTUP_TRACE] Hydration effect completed");
      })
      .catch((err) => {
        console.log(`[STARTUP_TRACE] Hydration effect FAILED: ${err.message}`);
        if (isMountedRef.current) {
          setShowWorkflowSelector(false);
        }
      });
  }, [backendReady]);

  // === GUARDED WORKFLOW SELECTION ===
  /**
   * Handle workflow selection with CRITICAL SAFETY GUARDS.
   *
   * PRESERVED GUARDS:
   * 1. Paused workflow guard — prevents invalid switching
   * 2. Active execution guard — prevents mid-execution switch
   * 3. Identity validation — sets expectedWorkflowIdRef
   *
   * @param {string} workflowId — workflow to select
   */
  const selectWorkflow = useCallback(
    async (workflowId) => {
      if (!workflowId) return;

      console.log("[GUI:HYDRATION_TRACE_SELECTION]", {
        phase: "selection_start",
        targetWorkflowId: workflowId,
        currentWorkflowId: activeWorkflowId,
        timestamp: Date.now(),
      });

      // === PAUSED WORKFLOW GUARD ===
      // Prevent switching when current workflow is paused
      // Paused workflows require explicit resume/cancel action
      if (lastResultRef.current?.status === "PAUSED") {
        console.log("[GUI:HYDRATION_TRACE_BLOCKED]", {
          phase: "paused_workflow_guard",
          reason: "current_workflow_is_paused",
          action: "selection_blocked",
          timestamp: Date.now(),
        });
        // Block selection — user must explicitly resume or cancel first
        return;
      }

      // === ACTIVE EXECUTION GUARD ===
      // Prevent switching during active execution
      if (isExecuting && activeWorkflowId !== workflowId) {
        console.log("[GUI:HYDRATION_TRACE_BLOCKED]", {
          phase: "active_execution_guard",
          reason: "execution_in_progress",
          action: "selection_blocked",
          timestamp: Date.now(),
        });
        // Block selection — user must explicitly pause/stop first
        return;
      }

      // === SELECTION APPROVED ===
      // Set expected workflow ID for identity validation
      expectedWorkflowIdRef.current = workflowId;

      // Update session state (triggers projection fetch in WorkflowProjectionView)
      lastResultRef.current = { workflow_id: workflowId };
      setLastResult({ workflow_id: workflowId });
      setShowWorkflowSelector(false);

      // Store for session restoration
      localStorage.setItem("activeWorkflowId", workflowId);

      console.log("[GUI:HYDRATION_TRACE_COMPLETE]", {
        phase: "selection_complete",
        workflowId: workflowId,
        expectedWorkflowId: expectedWorkflowIdRef.current,
        timestamp: Date.now(),
      });
    },
    [activeWorkflowId, isExecuting]
  );

  // === ORPHAN INVALIDATION ===
  /**
   * Handle orphaned workflow invalidation.
   * Called when backend confirms workflow no longer exists.
   *
   * @param {string} reason — invalidation reason
   * @param {string} workflowId — orphaned workflow ID
   */
  const invalidateOrphanedWorkflow = useCallback(
    (reason, workflowId) => {
      console.log("[GUI:ORPHAN_INVALIDATION]", {
        workflowId,
        reason,
        previousStatus: lastResultRef.current?.status,
        timestamp: Date.now(),
      });

      // Stop stream polling
      stopStreamPoll("orphan_invalidation");

      // Clear session state
      lastResultRef.current = null;
      setLastResult(null);

      // Reset runtime activity
      resetRuntimeActivity();

      // Clear expected workflow
      expectedWorkflowIdRef.current = null;

      // Clear stored workflow
      localStorage.removeItem("activeWorkflowId");
    },
    [resetRuntimeActivity, stopStreamPoll]
  );

  // === SESSION RESET ===
  /**
   * Reset/clear session state.
   * Used for new execution start or manual cleanup.
   */
  const resetSession = useCallback(() => {
    stopStreamPoll("session_reset");
    lastResultRef.current = null;
    setLastResult(null);
    resetRuntimeActivity();
    setShowWorkflowSelector(false);
    localStorage.removeItem("activeWorkflowId");
  }, [resetRuntimeActivity, stopStreamPoll]);

  // === NEW WORKFLOW REQUEST ===
  /**
   * Handle request to create new workflow.
   * Clears current session state.
   */
  const requestNewWorkflow = useCallback(() => {
    console.log("[GUI:NEW_WORKFLOW_REQUEST]", {
      previousWorkflowId: activeWorkflowId,
      timestamp: Date.now(),
    });
    resetSession();
  }, [activeWorkflowId, resetSession]);

  return {
    // State
    lastResult,
    activeWorkflowId,
    isExecuting,
    recoverableWorkflows,
    showWorkflowSelector,
    expectedWorkflowIdRef,
    lastResultRef,

    // Actions
    setLastResult,
    selectWorkflow,
    invalidateOrphanedWorkflow,
    resetSession,
    requestNewWorkflow,
    setShowWorkflowSelector,
  };
}

export default useWorkflowSession;
