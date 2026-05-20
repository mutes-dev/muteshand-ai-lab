/**
 * CHAT PANEL — PHASE 4C.0
 *
 * SUB-PHASE 3A — Immediate Request Acknowledgement
 * SUB-PHASE 3B — Planning Visibility State
 * SUB-PHASE 3C — Duplicate Submission Protection
 * SUB-PHASE 3D — Failure Visibility
 *
 * Per GUI_ARCHITECTURE.txt + GUI_FUNCTIONALITY_CONTRACT_V1.txt:
 * - Frontend acknowledges request TRANSPORT only
 * - Frontend does NOT synthesize workflow truth
 * - Frontend does NOT create optimistic projections
 * - Frontend does NOT create fake workflow IDs
 *
 * Per CANONICAL_PROJECTION_MODEL_V1:
 * - Workflow rendering remains projection-driven
 * - Planning state is non-authoritative and carries zero workflow identity
 * - Planning state MUST disappear when canonical projection arrives OR request fails
 *
 * AUTHORITY BOUNDARY:
 * `submitting` = local transport state (covers send → bg_id received gap)
 * `isExecuting` = derived from backend canonical projection (status === "ACTIVE")
 * These are SEPARATE: `submitting` carries no workflow identity
 *
 * PROHIBITED:
 * - No fake workflow IDs
 * - No speculative projections
 * - No optimistic step rendering
 * - No local lifecycle synthesis
 */

import { useState, useRef, useEffect } from "react";
import { api, log } from "../api.js";

// Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
// Frontend does NOT synthesize workflow ownership
// Backend provides authoritative workflow identity via projection

export default function ChatPanel({ onResult, onExecutionStart, onStreamStart, isExecuting }) {
  const [input, setInput] = useState("");
  const [error, setError] = useState(null);

  // SUB-PHASE 3A+3C: Transport-only request state
  // `submitting` covers the gap between send and bg_id receipt.
  // This state carries ZERO workflow identity — it is a transport acknowledgement only.
  // It does NOT represent workflow existence or lifecycle truth.
  const [submitting, setSubmitting] = useState(false);

  // SUB-PHASE 3B: Planning visibility state label
  // Transitions: null → "submitting" → "planning" → null (on projection arrival or failure)
  const [planningLabel, setPlanningLabel] = useState(null);

  // SUB-PHASE 3C: In-flight guard ref — prevents duplicate submissions even under
  // rapid async state updates (ref is synchronous, state update may batch)
  const inFlightRef = useRef(false);

  // Combined lock: button/textarea disabled while transport pending OR execution active
  // Per GUI_FUNCTIONALITY_CONTRACT_V1: controls must be locked during pending states
  const locked = submitting || isExecuting;

  async function handleSend() {
    // SUB-PHASE 3C: Duplicate submission protection
    // Synchronous ref guard covers the gap before React state batch commits
    if (!input.trim() || inFlightRef.current || isExecuting) return;

    inFlightRef.current = true;
    setError(null);

    // SUB-PHASE 3A: Immediate request acknowledgement
    // Set submitting BEFORE any async call — user sees "Submitting…" instantly
    // This is transport acknowledgement only, not workflow creation
    setSubmitting(true);
    setPlanningLabel("submitting");

    console.log("[GUI:REQUEST_TRANSPORT_ACKNOWLEDGED]", {
      action: "chat_send",
      timestamp: Date.now(),
      note: "transport_only_no_workflow_identity",
    });

    // Per GUI_ARCHITECTURE.txt: clear previous execution context before new request
    if (onExecutionStart) onExecutionStart();

    try {
      // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
      // Backend creates workflow and returns authoritative workflow_id in projection
      log("CHAT_SEND", { input: input.trim() });
      const stream = await api.executeStream(input.trim());

      // SUB-PHASE 3B: Planning visibility state
      // bg_id received — backend has accepted the request, orchestrator is planning
      // Still transport-only: we have a bg_id but NO workflow projection yet
      // This label is non-authoritative and carries zero workflow identity
      setPlanningLabel("planning");

      console.log("[GUI:REQUEST_BACKEND_ACCEPTED]", {
        bg_id: stream.bg_id,
        timestamp: Date.now(),
        note: "planning_phase_no_projection_yet",
      });

      // Hand off stream to App — projection poll will replace planning state
      // when canonical WorkflowProjection arrives (isExecuting becomes true)
      if (onStreamStart) onStreamStart(stream.bg_id);

      // SUB-PHASE 3B: Planning state persists until isExecuting becomes true
      // (canonical projection received) — isExecuting useEffect below handles clear
      // DO NOT clear here — keep button locked until workflow is ACTIVE
      console.log("[EXEC_TRACE] Stream response received, keeping locked until isExecuting");
    } catch (e) {
      // SUB-PHASE 3D: Failure visibility — reset all transport state safely
      // No phantom workflows, no stale planning UI
      console.log("[GUI:REQUEST_TRANSPORT_FAILED]", {
        error: e.message,
        timestamp: Date.now(),
      });
      setError(e.message);
      setSubmitting(false);
      setPlanningLabel(null);
    } finally {
      inFlightRef.current = false;
    }
  }

  // SUB-PHASE 3D: Clear local submitting ONLY when workflow is ACTIVE
  // This prevents button from unlocking during long LLM startup delays
  useEffect(() => {
    if (isExecuting) {
      console.log("[EXEC_TRACE] isExecuting=true → clearing local submitting/planningLabel");
      setSubmitting(false);
      setPlanningLabel(null);
    }
  }, [isExecuting]);

  function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      // SUB-PHASE 3C: Enter-spam protection — same lock as button
      if (!locked) handleSend();
    }
  }

  // Derive button label per transport/lifecycle phase
  // Per PHASE 3A+3B: labels reflect transport state only — no workflow identity implied
  function getSendLabel() {
    if (planningLabel === "submitting") return "Submitting…";
    if (planningLabel === "planning") return "Planning…";
    if (isExecuting) return "Running…";
    return "Send →";
  }

  return (
    <section className="panel chat-panel">
      <h2>Chat</h2>
      <div className="chat-input-row">
        <textarea
          className="chat-input"
          rows={3}
          placeholder="Enter instruction…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKey}
          disabled={locked}
        />
        <button
          className="btn-primary"
          onClick={handleSend}
          disabled={locked || !input.trim()}
          aria-busy={locked}
          aria-label={getSendLabel()}
        >
          {getSendLabel()}
        </button>
      </div>

      {/* SUB-PHASE 3B: Non-authoritative planning visibility banner */}
      {/* Disappears when projection arrives (isExecuting) or on failure */}
      {planningLabel === "planning" && (
        <div className="planning-notice" role="status" aria-live="polite">
          <span className="spinner-inline" aria-hidden="true" />
          Planning workflow… awaiting orchestrator projection
        </div>
      )}

      {/* SUB-PHASE 3D: Error visibility */}
      {error && <div className="error-badge">⚠ {error}</div>}
    </section>
  );
}
