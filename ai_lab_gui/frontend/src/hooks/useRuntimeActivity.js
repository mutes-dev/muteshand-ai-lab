/**
 * USE RUNTIME ACTIVITY — PHASE 2 SAFE EXTRACTION
 *
 * Per APP_JSX_DECOUPLING_ARCHITECTURE_AUDIT.md:
 * Low-risk extraction of runtime observability coordination.
 *
 * Authority: OBSERVABILITY_AND_DASHBOARD_ARCHITECTURE_CONTRACT_V1
 *
 * RESPONSIBILITIES:
 * - Runtime activity state management (observability only)
 * - Runtime activity updates from backend data
 * - Runtime activity reset/cleanup
 * - GlobalRuntimeStatus coordination
 *
 * NOT RESPONSIBLE FOR:
 * - Runtime execution authority (WorkflowPanel owns this)
 * - Event stream ownership (WorkflowPanel owns this)
 * - Stream polling (remains in App.jsx for now)
 * - Projection polling (prohibited)
 *
 * This hook is SAFE to extract because:
 * - Observability-only (no authority)
 * - Backend provides authoritative runtime_activity
 * - No stream ownership moved
 * - No projection coupling
 * - Self-contained state management
 *
 * Per PHASE 4G-A.6: runtime_activity is backend-authoritative,
 * extracted for global surface display ONLY.
 */

import { useState, useCallback, useRef, useEffect } from "react";

/**
 * useRuntimeActivity — runtime observability coordination hook
 *
 * Manages runtime_activity state for GlobalRuntimeStatus display.
 * Provides update/reset functions for coordination with stream polling.
 *
 * @returns {Object} Runtime activity state and controls
 * @returns {Object|null} runtimeActivity — current runtime activity data
 * @returns {Function} updateRuntimeActivity — update from backend data
 * @returns {Function} resetRuntimeActivity — clear/reset activity
 * @returns {boolean} hasActivity — whether activity is present
 */
export function useRuntimeActivity() {
  // State: backend-authoritative runtime_activity for observability
  const [runtimeActivity, setRuntimeActivity] = useState(null);

  // Ref for mount safety
  const isMountedRef = useRef(true);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  /**
   * Update runtime activity from backend data
   *
   * Called from stream poll when new runtime_activity data arrives.
   * Only updates if data has actually changed (prevents unnecessary renders).
   *
   * @param {Object} newActivity — runtime_activity from backend
   */
  const updateRuntimeActivity = useCallback((newActivity) => {
    if (!isMountedRef.current) return;

    // Per PHASE 4G-A.6: Only update if activity exists and is different
    // Prevents unnecessary re-renders from identical data
    setRuntimeActivity((current) => {
      if (newActivity && newActivity !== current) {
        return newActivity;
      }
      return current;
    });
  }, []);

  /**
   * Reset/clear runtime activity
   *
   * Called on:
   * - Orphan invalidation (workflow no longer exists)
   * - New execution start (clear previous activity)
   * - Workflow switch (clear old workflow's activity)
   */
  const resetRuntimeActivity = useCallback(() => {
    if (!isMountedRef.current) return;
    setRuntimeActivity(null);
  }, []);

  // Derived state for convenience
  const hasActivity = runtimeActivity !== null;

  return {
    runtimeActivity,
    updateRuntimeActivity,
    resetRuntimeActivity,
    hasActivity,
  };
}

export default useRuntimeActivity;
