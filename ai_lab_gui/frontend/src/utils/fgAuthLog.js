/**
 * Foreground Authority Lifecycle Logger
 * 
 * Per SA AUDIT — FOREGROUND OWNERSHIP DEADLOCK AFTER FAILURE
 * Add explicit logging for all foreground ownership transitions.
 */

export function logFgAuth(event, details = {}) {
  const timestamp = Date.now();
  const logEntry = {
    source: "FG_AUTH",
    event,
    timestamp,
    ...details
  };
  
  // Always log to console for audit visibility
  console.log("[FG_AUTH]", logEntry);
  
  return logEntry;
}

export function captureFgAuthState() {
  return {
    sessionKey: sessionStorage.getItem("wf_session_foreground"),
    timestamp: Date.now()
  };
}
