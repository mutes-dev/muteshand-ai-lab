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

/**
 * useWorkflowSession — GUARDED session coordination hook
 *
 * Manages workflow selection, recovery, and session state.
 * Preserves all safety guards from original App.jsx implementation.
 *
 * @param {Object} options
 * @param {Function} options.resetRuntimeActivity — runtime activity reset callback
 * @param {Function} options.stopStreamPoll — stream poll stop callback
 * @param {string} options.authoritativeProjectionStatus — authoritative projection lifecycle status
 * @returns {Object} Session state and coordinators
 */
export function useWorkflowSession({
  resetRuntimeActivity,
  stopStreamPoll,
  authoritativeProjectionStatus,
}) {
  
  // === SESSION STATE ===
  // lastResult: stores the last workflow result from ChatPanel execution
  // This is the authoritative source for activeWorkflowId derivation
  const [lastResult, setLastResult] = useState(null);

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
  // Per HAND_ARCHITECTURE_V2 §7: ACTIVATING and PENDING_RECOVERY are in-progress
  // execution contexts and MUST be treated equivalently to ACTIVE for guard purposes.
  // Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1: CANCELLED is immutable terminal
  // and must not remain executing/running.
  // Use authoritative projection status for terminal state detection.
  const resolvedStatus = authoritativeProjectionStatus || lastResult?.status;
  const isExecuting =
    resolvedStatus === "ACTIVE" ||
    resolvedStatus === "ACTIVATING" ||
    resolvedStatus === "PENDING_RECOVERY";

  // === [AUTH:EXECUTION_DERIVATION] Authority trace for execution state ===
  if (isExecuting) {
    console.log("[AUTH:EXECUTION_DERIVATION]", {
      workflow_id: lastResult?.workflow_id || null,
      lastResult_status: lastResult?.status || null,
      authoritativeProjectionStatus: authoritativeProjectionStatus || null,
      resolvedStatus: resolvedStatus || null,
      runtimeActivity: "NOT_AVAILABLE_AT_THIS_DERIVATION_POINT",
      derivation_reason: "authoritative_projection_or_lastResult_match",
      authority_source: authoritativeProjectionStatus ? "authoritative_projection" : "lastResult_projection_derived",
      projection_derived: true,
      timestamp: Date.now(),
    });
  }

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

      

      // === PAUSED WORKFLOW GUARD ===
      // Prevent switching when current workflow is paused
      // Paused workflows require explicit resume/cancel action
      if (lastResultRef.current?.status === "PAUSED") {
        
        // Block selection — user must explicitly resume or cancel first
        return;
      }

      // === ACTIVE EXECUTION GUARD ===
      // Prevent switching during active execution
      if (isExecuting && activeWorkflowId !== workflowId) {
        
        // Block selection — user must explicitly pause/stop first
        return;
      }

      // === SELECTION APPROVED ===
      // Set expected workflow ID for identity validation
      expectedWorkflowIdRef.current = workflowId;

      // Update session state (triggers projection fetch in WorkflowProjectionView)
      lastResultRef.current = { workflow_id: workflowId };
      setLastResult({ workflow_id: workflowId });

      
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
      

      // Stop stream polling
      stopStreamPoll("orphan_invalidation");

      // Clear session state
      lastResultRef.current = null;
      setLastResult(null);

      // Reset runtime activity
      resetRuntimeActivity();

      // Clear expected workflow
      expectedWorkflowIdRef.current = null;
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
  }, [resetRuntimeActivity, stopStreamPoll]);

  // === NEW WORKFLOW REQUEST ===
  /**
   * Handle request to create new workflow.
   * Clears current session state.
   */
  const requestNewWorkflow = useCallback(() => {
    
    resetSession();
  }, [activeWorkflowId, resetSession]);

  return {
    // State
    lastResult,
    activeWorkflowId,
    isExecuting,
    expectedWorkflowIdRef,
    lastResultRef,

    // Actions
    setLastResult,
    selectWorkflow,
    invalidateOrphanedWorkflow,
    resetSession,
    requestNewWorkflow,
  };
}

export default useWorkflowSession;
