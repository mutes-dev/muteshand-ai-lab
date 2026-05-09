import { useState, useEffect, useRef } from "react";
import { api } from "../api";
import { log } from "../utils/log.js";
import { normalizeResult } from "../utils/normalizeResult.js";

const STATUS_COLOR = {
  COMPLETED: "#22c55e",
  FAILED: "#ef4444",
  BLOCKED: "#f97316",
  ACTIVE: "#3b82f6",
  PENDING: "#94a3b8",
};

const POLL_INTERVAL_MS = 500;  // Faster polling for live updates (500ms)

// Build step state from events
// Per HAND_ARCHITECTURE_V2 Section 15: LIVE mode provides step-by-step visibility
// Per CONTROL_MODEL: Events are advisory, UI uses them for display only
function buildStepStateFromEvents(events) {
  const stepState = {};

  for (const event of events) {
    const { event_type, data } = event;
    const stepId = data?.step_id;

    if (!stepId) continue;

    if (!stepState[stepId]) {
      stepState[stepId] = {
        id: stepId,
        status: "PENDING",
        purpose: data?.purpose || "",
        retries: 0,
        execution_result: null
      };
    }

    switch (event_type) {
      case "step_started":
        stepState[stepId].status = "ACTIVE";
        stepState[stepId].purpose = data?.purpose || stepState[stepId].purpose;
        break;

      case "step_completed":
        stepState[stepId].status = data?.status || "COMPLETED";
        stepState[stepId].retries = data?.retries || 0;
        stepState[stepId].execution_result = data?.execution_status || data?.result_summary;
        break;

      case "step_failed":
        stepState[stepId].status = "FAILED";
        stepState[stepId].retries = data?.retries || 0;
        break;

      case "step_blocked":
        stepState[stepId].status = "BLOCKED";
        stepState[stepId].blocked_reason = data?.blocked_reason;
        break;

      case "state_transition":
        if (data?.new_state) {
          stepState[stepId].status = data.new_state;
        }
        break;

      case "governance_decision":
        // Governance decisions don't directly change UI state
        // They influence what happens next
        stepState[stepId].last_decision = data?.decision;
        break;

      case "MESSAGE":
        // MESSAGE events may or may not have step_id
        // Store message in step state if step_id present
        if (data?.message) {
          if (!stepState[stepId].messages) {
            stepState[stepId].messages = [];
          }
          stepState[stepId].messages.push({
            message: data.message,
            level: data.level || "INFO",
            timestamp: data.timestamp
          });
        }
        break;
    }
  }

  return Object.values(stepState);
}

export default function WorkflowPanel({ result, isExecuting, activeWorkflowId }) {
  const [events, setEvents] = useState([]);
  const [latestEventId, setLatestEventId] = useState(-1);
  const intervalRef = useRef(null);
  const latestEventIdRef = useRef(-1);

  // activeWorkflowId is set by App as soon as planning completes (during execution).
  // result?.workflow_id is the fallback once execution fully completes.
  const workflowId = activeWorkflowId || result?.workflow_id;

  // Extract outputs from contract-compliant structure
  const outputs = result?.outputs || [];

  console.log("AUDIT_WORKFLOW_PANEL_OUTPUTS:", result?.outputs);

  // Normalize result using shared normalizer
  const normalized = normalizeResult(result);

  log("WORKFLOW_PANEL_RENDER", { activeWorkflowId, resultWorkflowId: result?.workflow_id, finalWorkflowId: workflowId });
  log("NORMALIZED_RESULT", {
    type: normalized?.type,
    displayStatus: normalized?.displayStatus,
    displayReason: normalized?.displayReason,
    workflow_id: result?.workflow_id,
  });

  function stopPolling() {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }

  function fetchEvents(id) {
    // Always read from ref to avoid stale closure in setInterval
    const since = latestEventIdRef.current;
    api.getEvents(id, since, 100)
      .then((response) => {
        if (response.events && response.events.length > 0) {
          setEvents(prev => [...prev, ...response.events]);
          latestEventIdRef.current = response.latest_event_id;
          setLatestEventId(response.latest_event_id);
        }
      })
      .catch(() => {
        // 404 or network error — keep polling silently
      });
  }

  useEffect(() => {
    stopPolling();
    setEvents([]);
    setLatestEventId(-1);
    latestEventIdRef.current = -1;

    if (!workflowId) return;

    // Initial fetch
    fetchEvents(workflowId);

    // Start polling
    intervalRef.current = setInterval(() => fetchEvents(workflowId), POLL_INTERVAL_MS);

    return () => stopPolling();
  }, [workflowId]);

  // Do one final fetch after execution completes
  useEffect(() => {
    if (!isExecuting && workflowId) {
      fetchEvents(workflowId);
    }
  }, [isExecuting, workflowId]);

  // Build step state from accumulated events
  const steps = buildStepStateFromEvents(events);

  // Identify latest completed step for highlighting
  const completedSteps = steps.filter(s => s.status === "COMPLETED");
  const latestCompletedStepId = completedSteps.length
    ? completedSteps[completedSteps.length - 1].id
    : null;

  if (!result && !isExecuting) {
    return (
      <section className="panel workflow-panel">
        <h2>Workflow</h2>
        <p className="muted">No execution yet.</p>
      </section>
    );
  }

  return (
    <section className="panel workflow-panel">
      <h2>Workflow</h2>
      <div className="workflow-meta">
        {result && (
          <span className={`status-pill ${normalized?.displayStatus}`}>{normalized?.displayStatus?.toUpperCase()}</span>
        )}
        {isExecuting && <span className="running-indicator">⟳ Executing…</span>}
        {normalized?.displayReason && <span className="reason-badge">reason: {normalized?.displayReason}</span>}
      </div>

      {steps.length > 0 ? (
        <ol className="step-list">
          {steps.map((step, i) => {
            const status = step.status || "PENDING";
            const color = STATUS_COLOR[status] || "#94a3b8";

            // Match output to step by step_id
            const stepOutput = outputs.find(o => o.step_id === step.id);

            // Check if this is the latest completed step for highlighting
            const isLatestCompleted = step.id === latestCompletedStepId;

            return (
              <li key={step.id || i} className={`step-item${status === "ACTIVE" ? " step-item--active" : ""}${isLatestCompleted ? " latest-completed" : ""}`}>
                <span className={`step-dot${status === "ACTIVE" ? " step-dot--active" : ""}`} style={{ background: color }} />
                <span className="step-name">{step.purpose || step.id || `Step ${i + 1}`}</span>
                <span className="step-status" style={{ color }}>{status}</span>
                {step.retries > 0 && (
                  <span className="retry-count">(retry {step.retries})</span>
                )}
                {status === "ACTIVE" && (
                  <div className="step-processing">
                    … processing
                  </div>
                )}
                {status === "COMPLETED" && stepOutput && (
                  <div className="step-output fade-in">
                    → {stepOutput.execution_result?.result ?? "No result"}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="muted">{isExecuting ? "Waiting for events…" : "No step events available."}</p>
      )}

      {events.length > 0 && (
        <div className="event-count muted">
          {events.length} events received
        </div>
      )}
    </section>
  );
}
