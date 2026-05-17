import { useState, useEffect, useRef } from "react";
import { api } from "../api";
import { log } from "../utils/log.js";
import { normalizeResult } from "../utils/normalizeResult.js";

const STATUS_COLOR = {
  COMPLETED: "#22c55e",
  FAILED: "#ef4444",
  failure: "#ef4444",
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

// Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
// Frontend does NOT synthesize workflow ownership
// Backend provides authoritative workflow identity via projection

export default function WorkflowPanel({ result, isExecuting }) {
  const [events, setEvents] = useState([]);
  const [latestEventId, setLatestEventId] = useState(-1);
  const intervalRef = useRef(null);
  const latestEventIdRef = useRef(-1);
  const previousWorkflowIdRef = useRef(null);     // owned by render-state log effect only
  const activePollingWorkflowIdRef = useRef(null); // owned by polling effect + isolation guard
  const previousResultStatusRef = useRef(null);
  // Per PROJECTION_CONTINUITY_CONTRACT_V1 §11 (SUB-PHASE 3D+3E):
  // Track last known bus_sequence_id for reconnect continuity gap detection.
  // OBSERVATIONAL ONLY — does not influence execution or lifecycle authority.
  const knownBusSeqRef = useRef(0);

  // === S9F TRANSITION-AWARE IDENTITY GUARD STATE ===
  // Per TRANSITION-AWARE IDENTITY GUARD HARDENING:
  // Track explicit workflow transitions to distinguish valid switches from stale renders.
  // transitionTargetRef captures the intended workflow ID before polling ref synchronizes.
  const transitionTargetRef = useRef(null);
  const lastTransitionTimestampRef = useRef(0);
  const TRANSITION_WINDOW_MS = 500; // Window for transition recognition

  // === CONTINUITY GAP REPAIR STATE (PHASE S9B) ===
  // Per TARGETED HARDENING & ALIGNMENT PLANNING: automatic repair of continuity gaps.
  // Track last repair timestamp to implement debounce and prevent repair storms.
  const lastRepairTimestampRef = useRef(0);
  const repairInProgressRef = useRef(false);
  const REPAIR_DEBOUNCE_MS = 2000;  // Minimum time between repairs

  // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
  // Backend provides authoritative workflow identity via projection
  // No local ownership inference or fallback reconciliation logic
  // FIX 3: Result/workflow synchronization - derive workflowId from same projection as isExecuting
  const rawWorkflowId = result?.workflow_id || null;

  // === WORKFLOW IDENTITY VALIDATION GUARD (PHASE S9C + S9F) ===
  // Per TARGETED HARDENING & ALIGNMENT PLANNING: defensive validation of workflow identity.
  // Per S9F TRANSITION-AWARE HARDENING: distinguish valid transitions from stale renders.
  // Prevents stale workflow renders when result workflowId diverges from active polling context.
  // This is a render-time guard only — does NOT affect hydration sequencing or authority.
  let workflowId = rawWorkflowId;

  // === S9F: Detect Valid Workflow Transition ===
  // A valid transition occurs when:
  // 1. rawWorkflowId matches explicit transitionTargetRef (operator selected this workflow)
  // 2. rawWorkflowId differs from previousWorkflowIdRef (this is a new workflow, not stale)
  // 3. Within transition window of explicit workflow switch
  const isExplicitTransition = transitionTargetRef.current &&
    rawWorkflowId === transitionTargetRef.current;
  const isNewWorkflowTransition = rawWorkflowId &&
    rawWorkflowId !== previousWorkflowIdRef.current &&
    Date.now() - lastTransitionTimestampRef.current < TRANSITION_WINDOW_MS;
  const isValidTransition = isExplicitTransition || isNewWorkflowTransition;

  // === HYDRATION TRACE: Identity Guard Evaluation ===
  console.log("[GUI:HYDRATION_TRACE_S9C]", {
    phase: "identity_guard_evaluation",
    rawWorkflowId,
    activePollingWorkflowId: activePollingWorkflowIdRef.current,
    transitionTarget: transitionTargetRef.current,
    previousWorkflowId: previousWorkflowIdRef.current,
    isExplicitTransition,
    isNewWorkflowTransition,
    isValidTransition,
    guardCondition: !!(rawWorkflowId && activePollingWorkflowIdRef.current),
    mismatch: rawWorkflowId && activePollingWorkflowIdRef.current && rawWorkflowId !== activePollingWorkflowIdRef.current,
    timestamp: Date.now()
  });

  if (rawWorkflowId && activePollingWorkflowIdRef.current &&
    rawWorkflowId !== activePollingWorkflowIdRef.current) {
    // === S9F: Transition-Aware Validation ===
    // If this is a valid transition (not stale render), allow hydration
    if (isValidTransition) {
      console.log("[GUI:S9F_TRANSITION_RECOGNIZED]", {
        rawWorkflowId,
        activePollingWorkflowId: activePollingWorkflowIdRef.current,
        isExplicitTransition,
        isNewWorkflowTransition,
        action: "transition_allowed",
        timestamp: Date.now()
      });
      // Allow this workflow through - it's a legitimate transition
    } else {
      // Stale workflow identity detected — suppress render of mismatched workflow
      console.log("[GUI:WORKFLOW_IDENTITY_MISMATCH]", {
        rawWorkflowId,
        activePollingWorkflowId: activePollingWorkflowIdRef.current,
        transitionTarget: transitionTargetRef.current,
        action: "stale_render_suppressed",
        timestamp: Date.now()
      });
      workflowId = null;  // Suppress stale workflow render
    }
  }

  // === S9F: Clear Transition State After Recognition ===
  // Once the transition is recognized and render proceeds, clear the transition marker
  if (isExplicitTransition && workflowId) {
    transitionTargetRef.current = null;
  }

  // FIX 3: Ensure lifecycle status is synchronized with execution panel
  // Derive display status from result, not from isExecuting prop
  const displayStatus = result?.status || (isExecuting ? "ACTIVE" : null);

  // Extract outputs from contract-compliant structure
  const outputs = result?.outputs || [];

  // === LOG 6: WORKFLOW RENDER SNAPSHOT (only when state changes) ===
  useEffect(() => {
    const workflowIdChanged = workflowId !== previousWorkflowIdRef.current;
    const resultStatusChanged = result?.status !== previousResultStatusRef.current;

    if (workflowIdChanged || resultStatusChanged) {
      console.log("[GUI:WORKFLOW_RENDER_STATE]", {
        workflowId,
        renderedState: result?.status,
        renderedStepStatuses: events.map(e => ({ type: e.event_type, stepId: e.data?.step_id, status: e.data?.status })),
        timestamp: Date.now()
      });
      previousWorkflowIdRef.current = workflowId;
      previousResultStatusRef.current = result?.status;
    }
  }, [workflowId, result?.status, events]);

  // Normalize result using shared normalizer
  const normalized = normalizeResult(result);

  // TEMPORARY: Disabled noisy logs for pause/resume debugging
  // log("WORKFLOW_PANEL_RENDER", { activeWorkflowId, resultWorkflowId: result?.workflow_id, finalWorkflowId: workflowId });
  // log("NORMALIZED_RESULT", {
  //   type: normalized?.type,
  //   displayStatus: normalized?.displayStatus,
  //   displayReason: normalized?.displayReason,
  //   workflow_id: result?.workflow_id,
  // });

  function stopPolling(reason = "unknown", wfId = null) {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
      console.log("[GUI:POLL_SHUTDOWN]", {
        workflowId: wfId,
        streamOwner: "WorkflowPanel.eventPoll",
        reason,
        eventCount: events.length,
        timestamp: Date.now()
      });
    }
  }

  // === CONTINUITY GAP REPAIR (PHASE S9B) ===
  // Per TARGETED HARDENING & ALIGNMENT PLANNING: automatic deterministic authority rehydration.
  // Triggered when continuity gaps detected during active polling.
  // MUST be: idempotent, workflow-scoped, duplicate-preserving, terminal-aware.
  function repairContinuity(id, gapInfo) {
    const now = Date.now();

    // === REPAIR DEBOUNCE GUARD ===
    // Prevent infinite repair loops and repair storms.
    const timeSinceLastRepair = now - lastRepairTimestampRef.current;
    if (timeSinceLastRepair < REPAIR_DEBOUNCE_MS) {
      console.log("[GUI:CONTINUITY_REPAIR_SUPPRESSED]", {
        workflowId: id,
        reason: "debounce_active",
        timeSinceLastRepair,
        debounceMs: REPAIR_DEBOUNCE_MS,
        gapInfo,
        timestamp: now
      });
      return;
    }

    // === WORKFLOW ISOLATION GUARD ===
    // Per PROJECTION_CONTINUITY_CONTRACT_V1 §12: repair MUST respect workflow isolation.
    if (id !== activePollingWorkflowIdRef.current) {
      console.log("[GUI:CONTINUITY_REPAIR_REJECTED]", {
        workflowId: id,
        reason: "workflow_isolation_mismatch",
        activeWorkflowId: activePollingWorkflowIdRef.current,
        gapInfo,
        timestamp: now
      });
      return;
    }

    // === TERMINAL STATE GUARD ===
    // Per PROJECTION_CONTINUITY_CONTRACT_V1 §9: terminal states are anchors.
    // Repair MUST NOT resurrect terminal workflows.
    const isTerminal = result?.status === "COMPLETED" || result?.status === "FAILED" || result?.status === "failure";
    if (isTerminal) {
      console.log("[GUI:CONTINUITY_REPAIR_SUPPRESSED]", {
        workflowId: id,
        reason: "terminal_state",
        terminalStatus: result?.status,
        gapInfo,
        timestamp: now
      });
      return;
    }

    // === REPAIR IN PROGRESS GUARD ===
    // Prevent concurrent repair operations.
    if (repairInProgressRef.current) {
      console.log("[GUI:CONTINUITY_REPAIR_SUPPRESSED]", {
        workflowId: id,
        reason: "repair_already_in_progress",
        gapInfo,
        timestamp: now
      });
      return;
    }

    repairInProgressRef.current = true;
    lastRepairTimestampRef.current = now;

    console.log("[GUI:CONTINUITY_REPAIR_TRIGGERED]", {
      workflowId: id,
      gapInfo,
      currentEventCount: events.length,
      latestEventId: latestEventIdRef.current,
      timestamp: now
    });

    // === DETERMINISTIC AUTHORITY REHYDRATION ===
    // Per PROJECTION_CONTINUITY_CONTRACT_V1 §4: hydrate from canonical projection.
    // Full refetch rebuilds local continuity state from authority.
    api.getEvents(id, -1, 1000)
      .then((response) => {
        // === POST-REPAIR WORKFLOW ISOLATION GUARD ===
        if (id !== activePollingWorkflowIdRef.current) {
          console.log("[GUI:CONTINUITY_REPAIR_STALE_RESPONSE]", {
            workflowId: id,
            reason: "workflow_changed_during_repair",
            activeWorkflowId: activePollingWorkflowIdRef.current,
            timestamp: Date.now()
          });
          repairInProgressRef.current = false;
          return;
        }

        if (!response.events || response.events.length === 0) {
          console.log("[GUI:CONTINUITY_REPAIR_EMPTY]", {
            workflowId: id,
            reason: "no_events_from_authority",
            timestamp: Date.now()
          });
          repairInProgressRef.current = false;
          return;
        }

        // === DETERMINISTIC RECONCILIATION ===
        // Preserve duplicate suppression by filtering against existing events.
        // Per PROJECTION_CONTINUITY_CONTRACT_V1 §5: accumulation MUST avoid duplicates.
        setEvents(prev => {
          const existingEventIds = new Set(prev.map(e => e.event_id));
          const authoritativeEvents = response.events.filter(e => !existingEventIds.has(e.event_id));

          // Rebuild continuity anchor from authority
          if (response.events.length > 0) {
            const lastAuthEvent = response.events[response.events.length - 1];
            latestEventIdRef.current = lastAuthEvent.event_id;
            setLatestEventId(lastAuthEvent.event_id);
          }

          console.log("[GUI:CONTINUITY_REPAIR_COMPLETE]", {
            workflowId: id,
            previousEventCount: prev.length,
            authoritativeEventCount: response.events.length,
            newEventsAdded: authoritativeEvents.length,
            nextEventCount: prev.length + authoritativeEvents.length,
            latestEventId: latestEventIdRef.current,
            timestamp: Date.now()
          });

          return [...prev, ...authoritativeEvents];
        });

        repairInProgressRef.current = false;
      })
      .catch((err) => {
        console.log("[GUI:CONTINUITY_REPAIR_FAILED]", {
          workflowId: id,
          error: err?.message || "unknown",
          timestamp: Date.now()
        });
        repairInProgressRef.current = false;
      });
  }

  function fetchEvents(id) {
    // Always read from ref to avoid stale closure in setInterval
    const since = latestEventIdRef.current;
    api.getEvents(id, since, 100)
      .then((response) => {
        // === WORKFLOW ISOLATION GUARD ===
        // Per PROJECTION_CONTINUITY_CONTRACT_V1 §12: continuity MUST remain isolated per workflow_id.
        // If workflowId changed while this fetch was in-flight, discard the response.
        if (id !== activePollingWorkflowIdRef.current) {
          console.log("[GUI:WORKFLOW_ISOLATION_REJECT]", {
            staleFetchWorkflowId: id,
            activeWorkflowId: activePollingWorkflowIdRef.current,
            reason: "in_flight_fetch_for_old_workflow",
            timestamp: Date.now()
          });
          return;
        }
        // Per PROJECTION_CONTINUITY_CONTRACT_V1 §11 (SUB-PHASE 3D):
        // Track bus_sequence_id from response for reconnect gap detection.
        if (response.latest_bus_sequence_id !== undefined) {
          knownBusSeqRef.current = response.latest_bus_sequence_id;
        }

        if (response.events && response.events.length > 0) {
          // Per PROJECTION_CONTINUITY_CONTRACT_V1 §11: detect missing continuity segments
          // Phase 1: Event ID Gap Detection + Auto-Repair (PHASE S9B)
          if (latestEventIdRef.current >= 0) {
            const expectedEventId = latestEventIdRef.current + 1;
            const firstEventId = response.events[0].event_id;
            if (firstEventId !== expectedEventId) {
              const gapInfo = {
                type: "event_id_gap",
                expectedEventId,
                receivedEventId: firstEventId,
                gapSize: firstEventId - expectedEventId
              };
              console.log("[GUI:CONTINUITY_GAP_DETECTED]", {
                workflowId: id,
                ...gapInfo,
                action: "repair_triggered"
              });
              // === PHASE S9B: AUTOMATIC DETERMINISTIC REPAIR ===
              // Trigger authority rehydration to restore continuity.
              repairContinuity(id, gapInfo);
            }
          }

          // Per PROJECTION_CONTINUITY_CONTRACT_V1: Accumulation MUST avoid duplicate application
          setEvents(prev => {
            const existingEventIds = new Set(prev.map(e => e.event_id));
            const newEvents = response.events.filter(e => !existingEventIds.has(e.event_id));
            if (newEvents.length === 0) return prev; // no-op: avoids unnecessary re-render
            const next = [...prev, ...newEvents];
            console.log("[GUI:EVENT_ACCUMULATE]", {
              workflowId: id,
              previousEventCount: prev.length,
              nextEventCount: next.length,
              newEventCount: newEvents.length,
              latestEventId: response.latest_event_id,
              timestamp: Date.now()
            });
            return next;
          });

          // Phase 3: Continuity Anchor Drift Detection + Auto-Repair (PHASE S9B)
          if (latestEventIdRef.current >= 0 && response.latest_event_id < latestEventIdRef.current) {
            const gapInfo = {
              type: "anchor_drift",
              currentAnchor: latestEventIdRef.current,
              serverAnchor: response.latest_event_id,
              driftSize: latestEventIdRef.current - response.latest_event_id
            };
            console.log("[GUI:CONTINUITY_ANCHOR_DRIFT_DETECTED]", {
              workflowId: id,
              ...gapInfo,
              action: "repair_triggered"
            });
            // === PHASE S9B: AUTOMATIC DETERMINISTIC REPAIR ===
            // Trigger authority rehydration to restore continuity anchor.
            repairContinuity(id, gapInfo);
          }

          latestEventIdRef.current = response.latest_event_id;
          setLatestEventId(response.latest_event_id);

          console.log("[GUI:HYDRATION_COMMIT]", {
            workflowId: id,
            latestEventId: response.latest_event_id,
            eventsBatch: response.events.length,
            timestamp: Date.now()
          });
        }
      })
      .catch(() => {
        // 404 or network error — keep polling silently
      });
  }

  useEffect(() => {
    // === HYDRATION TRACE: Effect Entry ===
    console.log("[GUI:HYDRATION_TRACE_EFFECT]", {
      phase: "effect_entry",
      workflowId,
      prevPollingId: activePollingWorkflowIdRef.current,
      hasResult: !!result,
      resultWorkflowId: result?.workflow_id,
      timestamp: Date.now()
    });

    // === PROJECTION RESET BOUNDARY ===
    // Per PROJECTION_CONTINUITY_CONTRACT_V1: each workflowId transition MUST establish
    // a clean projection boundary BEFORE hydration of the new workflow.
    // activePollingWorkflowIdRef is owned exclusively by this effect.
    stopPolling("workflowId_changed", workflowId);

    // Reset projection state ONLY when transitioning between two real workflow IDs.
    // workflowId=null means "waiting for new execution" — do NOT destroy existing events.
    // Destroying events on null transition causes "No step events available" on the
    // just-completed workflow while the new workflow identity is still resolving.
    const prevId = activePollingWorkflowIdRef.current;
    if (workflowId !== null && workflowId !== prevId) {
      console.log("[GUI:EVENT_CLEAR]", {
        previousWorkflowId: prevId,
        newWorkflowId: workflowId,
        clearedEventCount: latestEventIdRef.current,
        reason: "workflow_id_transition",
        timestamp: Date.now()
      });
      setEvents([]);
      setLatestEventId(-1);
      latestEventIdRef.current = -1;
      // Per PROJECTION_CONTINUITY_CONTRACT_V1 §11 (SUB-PHASE 3D):
      // Reset bus sequence anchor on workflow transition.
      knownBusSeqRef.current = 0;
    }

    // === S9F: Set Transition Marker for New Workflows ===
    // When result contains a workflow ID that differs from active polling context,
    // mark this as a transition so the guard recognizes it as valid.
    const resultWorkflowId = result?.workflow_id;
    if (resultWorkflowId && resultWorkflowId !== activePollingWorkflowIdRef.current) {
      transitionTargetRef.current = resultWorkflowId;
      lastTransitionTimestampRef.current = Date.now();
      console.log("[GUI:S9F_TRANSITION_MARKER_SET]", {
        transitionTarget: resultWorkflowId,
        activePollingId: activePollingWorkflowIdRef.current,
        reason: "workflow_id_change_detected",
        timestamp: Date.now()
      });
    }

    // === HYDRATION TRACE: Setting Polling ID ===
    console.log("[GUI:HYDRATION_TRACE_POLLING_ID]", {
      phase: "setting_polling_id",
      oldPollingId: activePollingWorkflowIdRef.current,
      newPollingId: workflowId,
      timestamp: Date.now()
    });

    activePollingWorkflowIdRef.current = workflowId;

    if (!workflowId) return;

    // === RECONNECT REHYDRATION (SUB-PHASE 3B+3E) ===
    // Per PROJECTION_CONTINUITY_CONTRACT_V1 §4 (Hydration Semantics):
    // On workflow switch/reconnect, attempt to refresh from authoritative canonical projection.
    // This repairs continuity gaps without local synthesis.
    // GUI MUST NOT synthesize lifecycle state — canonical projection is the source of truth.
    api.getProjectionContinuity(workflowId)
      .then((continuity) => {
        // Only log — gap repair happens via full re-fetch of events below.
        // Per PROJECTION_CONTINUITY_CONTRACT_V1 §11: detect continuity gaps on reconnect.
        const busSeqGap = continuity.latest_bus_sequence_id > 0 &&
          knownBusSeqRef.current > 0 &&
          continuity.latest_bus_sequence_id > knownBusSeqRef.current;
        if (busSeqGap) {
          console.log("[GUI:RECONNECT_CONTINUITY_GAP]", {
            workflowId,
            knownBusSeq: knownBusSeqRef.current,
            serverBusSeq: continuity.latest_bus_sequence_id,
            missingEvents: continuity.latest_bus_sequence_id - knownBusSeqRef.current,
            action: "full_refetch_on_reconnect"
          });
        }
        console.log("[GUI:PROJECTION_CONTINUITY_HYDRATION]", {
          workflowId,
          projectionVersion: continuity.projection_version,
          projectionState: continuity.projection_state,
          continuityAnchor: continuity.continuity_anchor,
          staleRejections: continuity.stale_rejections,
          isTerminal: continuity.is_terminal,
          latestBusSeq: continuity.latest_bus_sequence_id,
          timestamp: Date.now()
        });
      })
      .catch(() => {
        // 404 = no projection yet (workflow not started) — normal, ignore silently
      });

    console.log("[GUI:STREAM_ATTACH]", {
      workflowId,
      streamOwner: "WorkflowPanel.eventPoll",
      timestamp: Date.now()
    });

    // Initial fetch for new workflow
    fetchEvents(workflowId);

    // Per PROJECTION_CONTINUITY_CONTRACT_V1 §11 (SUB-PHASE 3D): detect event bus pruning on reconnect.
    // Also captures latest_bus_sequence_id for ongoing gap detection.
    api.getEvents(workflowId, -1, 1)
      .then((response) => {
        if (response.latest_bus_sequence_id !== undefined) {
          knownBusSeqRef.current = response.latest_bus_sequence_id;
        }
        if (response.events && response.events.length > 0) {
          const firstEventId = response.events[0].event_id;
          if (firstEventId > 0) {
            console.log("[GUI:RECONNECT_EVENT_LOSS_DETECTED]", {
              workflowId,
              firstAvailableEventId: firstEventId,
              estimatedMissingEvents: firstEventId,
              latestBusSeq: response.latest_bus_sequence_id,
              action: "detected_only"
            });
          }
        }
      })
      .catch(() => { });

    // Start polling
    intervalRef.current = setInterval(() => fetchEvents(workflowId), POLL_INTERVAL_MS);

    return () => stopPolling("effect_cleanup", workflowId);
  }, [workflowId]);

  // === TERMINAL STREAM SHUTDOWN ===
  // Per PROJECTION_CONTINUITY_CONTRACT_V1 §9: terminal states are continuity anchors.
  // Stop event polling when result reaches a terminal state (COMPLETED or FAILED).
  // PAUSED is NOT terminal — per STATE_TRANSITIONS_CONTRACT_V1 PAUSED → ACTIVE is valid.
  const resultStatus = result?.status;
  useEffect(() => {
    const isTerminal = resultStatus === "COMPLETED" || resultStatus === "FAILED" || resultStatus === "failure";
    if (isTerminal) {
      console.log("[GUI:WORKFLOW_COMPLETE]", {
        workflowId,
        terminalStatus: resultStatus,
        eventCount: latestEventIdRef.current,
        timestamp: Date.now()
      });
      if (intervalRef.current) {
        console.log("[GUI:STREAM_SHUTDOWN]", {
          workflowId,
          terminalStatus: resultStatus,
          streamOwner: "WorkflowPanel.eventPoll",
          reason: "workflow_terminal",
          timestamp: Date.now()
        });
        stopPolling("terminal_state", workflowId);
      }
      // Final fetch to capture any events emitted between last poll tick and terminal state
      if (workflowId) {
        fetchEvents(workflowId);
      }
    } else if (!isExecuting && workflowId) {
      // Non-terminal completion (e.g. PAUSED): do one fetch to capture latest events
      fetchEvents(workflowId);
    }
  }, [isExecuting, workflowId, resultStatus]);

  // Build step state from accumulated events
  const steps = buildStepStateFromEvents(events);

  // === TERMINAL RENDER INSTRUMENTATION ===
  const isTerminalRender = resultStatus === "COMPLETED" || resultStatus === "FAILED";
  if (isTerminalRender && steps.length === 0 && events.length > 0) {
    console.log("[GUI:TERMINAL_RENDER]", {
      workflowId,
      terminalStatus: resultStatus,
      eventCount: events.length,
      stepCount: steps.length,
      warning: "events_present_but_no_steps_derived",
      timestamp: Date.now()
    });
  }
  if (isTerminalRender) {
    console.log("[GUI:TERMINAL_RENDER]", {
      workflowId,
      terminalStatus: resultStatus,
      eventCount: events.length,
      stepCount: steps.length,
      timestamp: Date.now()
    });
  }

  // Identify latest completed step for highlighting
  const completedSteps = steps.filter(s => s.status === "COMPLETED");
  const latestCompletedStepId = completedSteps.length
    ? completedSteps[completedSteps.length - 1].id
    : null;

  // === HYDRATION TRACE: Render Evaluation ===
  console.log("[GUI:HYDRATION_TRACE_RENDER]", {
    phase: "render_evaluation",
    workflowId,
    hasResult: !!result,
    isExecuting,
    willRenderEmpty: !result && !isExecuting,
    stepCount: steps.length,
    timestamp: Date.now()
  });

  if (!result && !isExecuting) {
    console.log("[GUI:HYDRATION_TRACE_RENDER]", {
      phase: "empty_render",
      reason: "no_result_and_not_executing",
      workflowId,
      timestamp: Date.now()
    });
    return (
      <section className="panel workflow-panel">
        <h2>Workflow</h2>
        <p className="muted">No execution yet.</p>
      </section>
    );
  }

  // === PROJECTION-ONLY MODE DETECTION ===
  // Per PROJECTION-FIRST HYDRATION ALIGNMENT: Detect projection-only workflows
  const isProjectionOnly = result?._hydrationSource === "projection_only";
  const runtimeContext = result?._runtimeContext;

  console.log("[GUI:HYDRATION_TRACE_RENDER]", {
    phase: "full_render",
    workflowId,
    status: result?.status,
    isProjectionOnly,
    runtimeContext,
    stepCount: steps.length,
    timestamp: Date.now()
  });

  return (
    <section className="panel workflow-panel">
      <h2>Workflow</h2>
      <div className="workflow-meta">
        {result && (
          <span className={`status-pill ${normalized?.displayStatus}`}>{normalized?.displayStatus?.toUpperCase()}</span>
        )}
        {isExecuting && <span className="running-indicator">⟳ Executing…</span>}
        {normalized?.displayReason && <span className="reason-badge">reason: {normalized?.displayReason}</span>}
        {/* === PROJECTION-ONLY INDICATOR === */}
        {/* Per PROJECTION-FIRST HYDRATION ALIGNMENT: Clearly indicate view-only mode */}
        {isProjectionOnly && (
          <span className="projection-only-indicator" title="No active runtime context - view only">
            ○ Projection View
          </span>
        )}
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
