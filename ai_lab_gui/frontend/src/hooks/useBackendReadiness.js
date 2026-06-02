/**
 * USE BACKEND READINESS — PHASE 1 SAFE EXTRACTION
 *
 * Per APP_JSX_DECOUPLING_ARCHITECTURE_AUDIT.md:
 * Low-risk extraction of backend health monitoring.
 *
 * Authority: GUI_ARCHITECTURE.txt
 *
 * RESPONSIBILITIES:
 * - Backend health polling
 * - Backend ready state
 * - Backend unavailable detection
 * - Retry logic with backoff
 * - Timer/effect lifecycle
 *
 * NOT RESPONSIBLE FOR:
 * - Workflow session (higher risk)
 * - Projection polling (prohibited)
 * - Runtime attachment (separate domain)
 *
 * This hook is SAFE to extract because:
 * - No workflow coupling
 * - No session coupling
 * - No projection coupling
 * - No runtime coupling
 * - Self-contained and isolated
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { waitForBackend } from "../api.js";

/**
 * ISSUE-063: Retrieve the expected app instance ID from Tauri.
 * Returns null if Tauri is not available (e.g., browser dev mode).
 */
async function getExpectedAppInstanceId() {
  try {
    // ISSUE-063: Tauri v2 global API uses window.__TAURI__.core.invoke
    if (window.__TAURI__?.core?.invoke) {
      const id = await window.__TAURI__.core.invoke("get_app_instance_id");
      console.log("[ISSUE-063] Expected app_instance_id from Tauri:", id);
      return id;
    }
  } catch (e) {
    console.log("[ISSUE-063] Tauri not available, skipping identity validation:", e);
  }
  return null;
}

/**
 * useBackendReadiness — backend health monitoring hook
 *
 * Polls backend health endpoint until backend is ready.
 * Provides ready/unavailable states for UI orchestration.
 *
 * @returns {Object} Backend readiness state
 * @returns {boolean} isReady — backend is ready
 * @returns {boolean} isLoading — checking backend status
 * @returns {boolean} isUnavailable — backend unavailable after retries
 * @returns {string|null} error — error message if unavailable
 * @returns {Function} retry — manual retry function
 */
export function useBackendReadiness() {
  // State
  const [isReady, setIsReady] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isUnavailable, setIsUnavailable] = useState(false);
  const [isIdentityMismatch, setIsIdentityMismatch] = useState(false);
  const [error, setError] = useState(null);

  // Refs for effect control
  const isMountedRef = useRef(true);
  const retryCountRef = useRef(0);
  const timeoutRef = useRef(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isMountedRef.current = false;
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  // Backend check function
  const checkBackend = useCallback(async () => {
    console.log("[STARTUP_TRACE] checkBackend start");
    if (!isMountedRef.current) {
      console.log("[STARTUP_TRACE] checkBackend abort: unmounted");
      return;
    }

    let expectedId = null;
    try {
      expectedId = await getExpectedAppInstanceId();
    } catch (e) {
      console.log("[STARTUP_TRACE] Failed to get expected app_instance_id:", e);
    }

    try {
      console.log("[STARTUP_TRACE] waitForBackend calling...");
      const ready = await waitForBackend(expectedId, 5000, 500);
      console.log(`[STARTUP_TRACE] waitForBackend resolved: ready=${ready}`);

      if (ready) {
        console.log("[STARTUP_TRACE] Setting backendReady=true, isLoading=false");
        setIsReady(true);
        setIsLoading(false);
        setIsUnavailable(false);
        setIsIdentityMismatch(false);
        setError(null);
        retryCountRef.current = 0;
        console.log("[STARTUP_TRACE] Backend readiness state SET");
      } else {
        console.log("[STARTUP_TRACE] waitForBackend returned false");
        retryCountRef.current += 1;

        if (retryCountRef.current > 20) {
          console.log("[STARTUP_TRACE] Max retries reached, marking unavailable");
          setIsUnavailable(true);
          setError("Backend unavailable after multiple retries");
          setIsLoading(false);
        } else {
          console.log(`[STARTUP_TRACE] Scheduling retry ${retryCountRef.current}`);
          timeoutRef.current = setTimeout(() => {
            checkBackend();
          }, 500);
        }
      }
    } catch (err) {
      if (!isMountedRef.current) {
        console.log("[STARTUP_TRACE] checkBackend abort: unmounted after error");
        return;
      }
      const msg = err?.message || "";
      console.log(`[STARTUP_TRACE] Backend check ERROR: ${msg}`);
      if (msg.includes("identity mismatch") || msg.includes("Port 8000 occupied")) {
        setIsIdentityMismatch(true);
        setIsUnavailable(true);
        setError(msg);
        setIsLoading(false);
      } else {
        setIsUnavailable(true);
        setError(msg || "Backend connection failed");
        setIsLoading(false);
      }
    }
  }, []);

  // Manual retry function
  const retry = useCallback(() => {
    if (!isMountedRef.current) return;

    setIsLoading(true);
    setIsUnavailable(false);
    setIsIdentityMismatch(false);
    setError(null);
    retryCountRef.current = 0;

    checkBackend();
  }, [checkBackend]);

  // Initial backend check
  useEffect(() => {
    checkBackend();
  }, [checkBackend]);

  return {
    isReady,
    isLoading,
    isUnavailable,
    isIdentityMismatch,
    error,
    retry,
  };
}

export default useBackendReadiness;
