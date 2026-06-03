import { useState, useEffect, useRef } from "react";
import { api } from "../api";
import { log } from "../utils/log.js";
import { normalizeResult } from "../utils/normalizeResult.js";
import { STATUS_COLOR } from "../constants/workflow.js";

const POLL_INTERVAL_MS = 500;  // Faster polling for live updates (500ms)

// Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
// Build per-step transition history from authoritative events.
// Returns map of step_id → array of {from, to, timestamp, bus_sequence_id}
function buildStepTransitionsFromEvents(events) {
  const transitions = {};
  for (const event of events) {
    const { event_type, data, timestamp, bus_sequence_id } = event;
    const stepId = data?.step_id;
    if (!stepId) continue;
    if (event_type === "state_transition" && data?.previous_state && data?.new_state) {
      if (!transitions[stepId]) transitions[stepId] = [];
      transitions[stepId].push({
        from: data.previous_state,
        to: data.new_state,
        timestamp,
        bus_sequence_id,
      });
    }
  }
  return transitions;
}

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

      case "step_retry":
        // Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
        // Track retry_generation from retry events for operator lineage visibility.
        stepState[stepId].retry_generation = data?.retry_count || 0;
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

// ISSUE-055B Phase 2 Correction: safe helper to detect dead QUEUED shells
function isDeadQueuedReplanRequired(metadata) {
  if (!metadata) return false;
  if (metadata.status !== "QUEUED") return false;
  if (metadata.projection_expected_missing !== true) return false;
  if (metadata.actionability === "PLANNING_REPLAN") return true;
  if (metadata.planning_actionability === "REPLAN_REQUIRED") return true;
  return false;
}

export default function WorkflowPanel({ result, isExecuting, projection, resolvedWorkflowStatus, selectedWorkflowMetadata = null, onRequestProjectionRefresh = null }) {
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
  // ISSUE-074B: SSE EventSource refs
  const eventSourceRef = useRef(null);
  const sseConnectedRef = useRef(false);

  // === ISSUE-069: Event-informed projection refetch debounce ===
  // Per ISSUE-069 audit: events may signal projection freshness but must NOT be applied
  // as projection truth. Debounce prevents refetch storms under high event volume.
  const lastProjectionRefetchAtRef = useRef(0);
  const PROJECTION_REFETCH_DEBOUNCE_MS = 200;

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

  // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1:
  // Frontend derives display status from backend projection ONLY.
  // No local inference from isExecuting or other props.
  const displayStatus = result?.status || null;

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

  // ISSUE-074B: Close SSE EventSource and reset connected flag
  function closeEventSource(reason = "unknown") {
    if (eventSourceRef.current) {
      console.log("[GUI:SSE_CLOSE]", { workflowId, reason });
      if (eventSourceRef.current._fallbackTimer) {
        clearTimeout(eventSourceRef.current._fallbackTimer);
      }
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      sseConnectedRef.current = false;
    }
  }

  // ISSUE-069: Debounced projection refetch triggered by new events.
  // Events are observational-only; they signal that canonical projection may be fresher.
  // Actual projection state is always fetched from the backend /projection endpoint.
  function triggerDebouncedProjectionRefetch(id) {
    const now = Date.now();
    const elapsed = now - lastProjectionRefetchAtRef.current;
    if (elapsed < PROJECTION_REFETCH_DEBOUNCE_MS) {
      console.log("[GUI:PROJECTION_REFETCH_SUPPRESSED]", {
        workflowId: id,
        elapsed,
        debounceMs: PROJECTION_REFETCH_DEBOUNCE_MS,
        reason: "debounce_active",
        timestamp: now
      });
      return;
    }
    lastProjectionRefetchAtRef.current = now;
    console.log("[GUI:PROJECTION_REFETCH_TRIGGERED]", {
      workflowId: id,
      elapsed,
      reason: "event_informed_debounced",
      timestamp: now
    });
    if (onRequestProjectionRefresh) {
      onRequestProjectionRefresh();
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
    // Repair MUST NOT resurrect IMMUTABLE terminal workflows.
    // FAILED is recoverable — repair is allowed in case retry events were missed.
    const isImmutableTerminal = result?.status === "COMPLETED" || result?.status === "CANCELLED" || result?.status === "failure";
    if (isImmutableTerminal) {
      console.log("[GUI:CONTINUITY_REPAIR_SUPPRESSED]", {
        workflowId: id,
        reason: "terminal_state_immutable",
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
    api.getEvents(id, -1, -1, 1000)
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

  // ISSUE-074B: Start SSE event discovery with polling fallback
  function startEventDiscovery(id) {
    closeEventSource("workflow_switch");

    // ISSUE-055B Phase 2 Correction: suppress event discovery for dead QUEUED shells
    if (isDeadQueuedReplanRequired(selectedWorkflowMetadata)) {
      console.log("[GUI:EVENT_DISCOVERY_SUPPRESSED]", {
        workflowId: id,
        reason: "queued_replan_required_projection_expected_missing",
        timestamp: Date.now(),
      });
      return;
    }

    const es = api.createWorkflowEventSource(id, {
      onMessage: (data, lastEventId) => {
        // === WORKFLOW ISOLATION GUARD ===
        if (id !== activePollingWorkflowIdRef.current) {
          console.log("[GUI:SSE_ISOLATION_REJECT]", {
            workflowId: id,
            activeWorkflowId: activePollingWorkflowIdRef.current,
            timestamp: Date.now(),
          });
          return;
        }

        console.log("[GUI:SSE_HINT]", {
          workflowId: id,
          eventType: data.event_type,
          busSequenceId: data.bus_sequence_id,
          lastEventId,
          timestamp: Date.now(),
        });

        // Update continuity anchor from SSE hint
        if (data.bus_sequence_id !== undefined) {
          knownBusSeqRef.current = data.bus_sequence_id;
        }

        // ISSUE-074B: SSE hints trigger the existing debounced projection refetch path.
        // Events remain observational-only; projection truth comes from /projection.
        triggerDebouncedProjectionRefetch(id);
      },
      onError: () => {
        sseConnectedRef.current = false;
        // If polling isn't running and workflow is still active, start fallback polling
        if (!intervalRef.current && id === activePollingWorkflowIdRef.current) {
          const isImmutableTerminal = result?.status === "COMPLETED" || result?.status === "CANCELLED" || result?.status === "failure";
          if (!isImmutableTerminal) {
            console.log("[GUI:SSE_FALLBACK_POLLING]", {
              workflowId: id,
              reason: "sse_error",
              timestamp: Date.now(),
            });
            fetchEvents(id);
            intervalRef.current = setInterval(() => fetchEvents(id), POLL_INTERVAL_MS);
          }
        }
      },
      onOpen: () => {
        sseConnectedRef.current = true;
        console.log("[GUI:SSE_CONNECTED]", {
          workflowId: id,
          action: "stop_polling",
          timestamp: Date.now(),
        });
        stopPolling("sse_took_over", id);
      },
    });

    eventSourceRef.current = es;

    // Fallback: if SSE doesn't connect within 3s, start polling
    const fallbackTimer = setTimeout(() => {
      if (!sseConnectedRef.current && id === activePollingWorkflowIdRef.current && !intervalRef.current) {
        console.log("[GUI:SSE_FALLBACK_TIMER]", {
          workflowId: id,
          reason: "connection_timeout",
          timestamp: Date.now(),
        });
        fetchEvents(id);
        intervalRef.current = setInterval(() => fetchEvents(id), POLL_INTERVAL_MS);
      }
    }, 3000);

    // Store timer on the ES wrapper so cleanup can clear it
    es._fallbackTimer = fallbackTimer;
  }

  function fetchEvents(id) {
    // ISSUE-074B: Skip polling when SSE is the active event discovery path
    if (sseConnectedRef.current) {
      return;
    }
    // ISSUE-055B Phase 2 Correction: suppress event polling for dead QUEUED shells
    if (isDeadQueuedReplanRequired(selectedWorkflowMetadata)) {
      console.log("[GUI:EVENT_FETCH_SUPPRESSED]", {
        workflowId: id,
        reason: "queued_replan_required_projection_expected_missing",
        timestamp: Date.now(),
      });
      return;
    }
    // Always read from ref to avoid stale closure in setInterval
    const since = latestEventIdRef.current;
    api.getEvents(id, since, -1, 100)
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
          let hadNewEvents = false;
          setEvents(prev => {
            const existingEventIds = new Set(prev.map(e => e.event_id));
            const newEvents = response.events.filter(e => !existingEventIds.has(e.event_id));
            if (newEvents.length === 0) return prev; // no-op: avoids unnecessary re-render
            hadNewEvents = true;
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

          // ISSUE-069: Event-informed projection refetch
          // Events are observational-only; they signal that projection may be fresh.
          // Actual projection state is still fetched from canonical backend endpoint.
          if (hadNewEvents) {
            triggerDebouncedProjectionRefetch(id);
          }

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

    // ISSUE-055B Phase 2 Correction: skip event polling for dead QUEUED shells
    if (isDeadQueuedReplanRequired(selectedWorkflowMetadata)) {
      console.log("[GUI:EVENT_POLL_SUPPRESSED]", {
        workflowId,
        reason: "queued_replan_required_projection_expected_missing",
        timestamp: Date.now(),
      });
      return;
    }

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
    api.getEvents(workflowId, -1, -1, 1)
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

    // ISSUE-074B: Start SSE event discovery with polling fallback
    startEventDiscovery(workflowId);

    return () => {
      if (eventSourceRef.current?._fallbackTimer) {
        clearTimeout(eventSourceRef.current._fallbackTimer);
      }
      closeEventSource("effect_cleanup");
      stopPolling("effect_cleanup", workflowId);
    };
  }, [workflowId, selectedWorkflowMetadata]);

  // === TERMINAL STREAM SHUTDOWN ===
  // Per PROJECTION_CONTINUITY_CONTRACT_V1 §9: terminal states are continuity anchors.
  // Stop event polling for IMMUTABLE terminals (COMPLETED, CANCELLED, failure).
  // Keep polling for RECOVERABLE terminals (FAILED) — retry may create new events.
  // PAUSED is NOT terminal — per STATE_TRANSITIONS_CONTRACT_V1 PAUSED → ACTIVE is valid.
  const resultStatus = result?.status;
  useEffect(() => {
    const isImmutableTerminal = resultStatus === "COMPLETED" || resultStatus === "CANCELLED" || resultStatus === "failure";
    const isRecoverableTerminal = resultStatus === "FAILED";
    if (isImmutableTerminal) {
      console.log("[GUI:WORKFLOW_COMPLETE]", {
        workflowId,
        terminalStatus: resultStatus,
        immutable: true,
        eventCount: latestEventIdRef.current,
        timestamp: Date.now()
      });
      if (intervalRef.current) {
        console.log("[GUI:STREAM_SHUTDOWN]", {
          workflowId,
          terminalStatus: resultStatus,
          streamOwner: "WorkflowPanel.eventPoll",
          reason: "workflow_terminal_immutable",
          timestamp: Date.now()
        });
        stopPolling("terminal_state_immutable", workflowId);
      }
      // ISSUE-074B: Also close SSE on immutable terminal
      closeEventSource("terminal_state_immutable");
      // Final fetch to capture any events emitted between last poll tick and terminal state
      if (workflowId) {
        fetchEvents(workflowId);
      }
    } else if (isRecoverableTerminal) {
      // FAILED is recoverable — keep polling for retry events
      console.log("[GUI:WORKFLOW_RECOVERABLE]", {
        workflowId,
        terminalStatus: resultStatus,
        action: "polling_continues_for_retry",
        timestamp: Date.now()
      });
    } else if (!isExecuting && workflowId) {
      // Non-terminal completion (e.g. PAUSED): do one fetch to capture latest events
      fetchEvents(workflowId);
    }
  }, [isExecuting, workflowId, resultStatus]);

  // Build event-derived step state (for enrichment and fallback during early execution)
  const eventSteps = buildStepStateFromEvents(events);
  const eventStepMap = new Map(eventSteps.map((s) => [s.id, s]));

  // === PROJECTION AUTHORITY REALIGNMENT ===
  // Per CANONICAL_PROJECTION_MODEL_V1 §2: Canonical projection is the authoritative
  // read-model for lifecycle state. Events are advisory and non-authoritative.
  // WorkflowPanel MUST derive step STATUS from canonical projection, not from event
  // stream reconstruction. Event data is retained for enrichment only.
  //
  // Authority chain:
  //   1. focusedProjection.steps (live projection from WorkflowProjectionView)
  //   2. result.steps (canonical projection from stream or loadProjectionOnlyWorkflow)
  //   3. eventSteps (fallback when projection has not yet hydrated)
  const authoritySteps = projection?.steps?.length > 0
    ? projection.steps
    : result?.steps?.length > 0
      ? result.steps
      : [];

  const projectionSteps = authoritySteps.length > 0
    ? authoritySteps.map((step, i) => {
      const stepId = step.id || step.step_id || `step-${i}`;
      const eventStep = eventStepMap.get(stepId);

      const projectionStatus = step.status || "PENDING";
      const eventStatus = eventStep?.status;
      const isActiveExecution = result?.status === "ACTIVE" || isExecuting;
      const isProjectionTerminal = ["COMPLETED", "FAILED", "CANCELLED", "BLOCKED"].includes(projectionStatus);

      // During active execution, trust event stream for ACTIVE/COMPLETED to avoid
      // stale projection from pre-execution fetch. Projection always wins for
      // terminal and non-normal states.
      let status = projectionStatus;
      if (isActiveExecution && !isProjectionTerminal && (eventStatus === "ACTIVE" || eventStatus === "COMPLETED")) {
        status = eventStatus;
      }

      return {
        id: stepId,
        status,
        purpose: step.purpose || stepId,
        retries: step.retries || 0,
        retry_generation: step.retry_generation || 0,
        execution_result: eventStep?.execution_result || null,
        blocked_reason: step.blocked_reason || null,
        messages: eventStep?.messages || [],
        last_decision: eventStep?.last_decision || null,
      };
    })
    : [];

  // Use projection as authority when available; events as fallback for live execution
  // when projection has not yet hydrated (e.g. new execution startup window).
  const steps = projectionSteps.length > 0 ? projectionSteps : eventSteps;

  // === CANCELLATION DISPLAY SUPPRESSION ===
  // Suppress active/processing affordances when workflow-level status is CANCELLED
  const isWorkflowCancelled = resolvedWorkflowStatus === "CANCELLED";

  // === TERMINAL RENDER INSTRUMENTATION ===
  const isTerminalRender = resultStatus === "COMPLETED" || resultStatus === "FAILED" || resultStatus === "CANCELLED";
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
      {/* === OBSERVABILITY META — NOT LIFECYCLE AUTHORITY === */}
      {/* Per PHASE 4G-A.6: runtime_activity removed — now renders in GlobalRuntimeStatus only */}
      {/* WorkflowPanel focuses on event/step observability only */}
      <div className="workflow-meta">
        {normalized?.displayReason && <span className="reason-badge">reason: {normalized?.displayReason}</span>}
        {/* Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
            execution_generation is authoritative workflow execution identity.
            Frontend renders only — NEVER interprets as lifecycle authority. */}
        {result?.execution_generation > 1 && (
          <span
            className="execution-generation-badge"
            style={{ fontSize: "0.75rem", color: "#94a3b8", marginLeft: "0.5rem" }}
            title="Execution generation increments when a new execution attempt invalidates stale runtime ownership"
          >
            Gen {result.execution_generation}
          </span>
        )}
        {/* === PROJECTION-ONLY INDICATOR === */}
        {/* Per PROJECTION-FIRST HYDRATION ALIGNMENT: Clearly indicate view-only mode */}
        {isProjectionOnly && (
          <span className="projection-only-indicator" title="No active runtime context - view only">
            ○ Projection View
          </span>
        )}
      </div>

      {/* === EXECUTION CONTINUITY SUMMARY (SUB-PHASE 3B) === */}
      {steps.length > 0 && (
        <div className="execution-summary">
          {steps.find(s => s.status === "ACTIVE") && !isWorkflowCancelled && (
            <span className="summary-active">
              Active: {steps.find(s => s.status === "ACTIVE").purpose}
            </span>
          )}
          {latestCompletedStepId && (
            <span className="summary-completed">
              Last completed: {steps.find(s => s.id === latestCompletedStepId)?.purpose}
            </span>
          )}
          <span className="summary-progress muted">
            {steps.filter(s => s.status === "COMPLETED").length} / {steps.length} completed
          </span>
          {isWorkflowCancelled && (
            <span className="summary-cancelled muted">
              Workflow cancelled — step list is historical
            </span>
          )}
        </div>
      )}

      {/* Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
          Derive per-step transition history from authoritative events. */}
      {(() => {
        const stepTransitions = buildStepTransitionsFromEvents(events);
        return steps.length > 0 ? (
          <ol className="step-list">
            {steps.map((step, i) => {
              const status = step.status || "PENDING";
              const color = STATUS_COLOR[status] || "#94a3b8";

              // Match output to step by step_id
              const stepOutput = outputs.find(o => o.step_id === step.id);

              // Check if this is the latest completed step for highlighting
              const isLatestCompleted = step.id === latestCompletedStepId;

              const transitions = stepTransitions[step.id];

              return (
                <li key={step.id || i} className={`step-item${status === "ACTIVE" ? " step-item--active" : ""}${isLatestCompleted ? " latest-completed" : ""}`}>
                  <span className={`step-dot${status === "ACTIVE" ? " step-dot--active" : ""}`} style={{ background: color }} />
                  <span className="step-name">{step.purpose || step.id || `Step ${i + 1}`}</span>
                  <span className="step-status" style={{ color }}>{status}</span>
                  {step.retries > 0 && (
                    <span className="retry-count" title="Automatic recovery retries (governance-driven)">({step.retries} attempt{step.retries !== 1 ? "s" : ""})</span>
                  )}
                  {step.retry_generation > 0 && (
                    <span className="retry-generation-count" style={{ fontSize: "0.7rem", color: "#94a3b8", marginLeft: "0.25rem" }} title="User-initiated retry attempts">
                      ({step.retry_generation} user retry{step.retry_generation !== 1 ? "s" : ""})
                    </span>
                  )}
                  {/* Live retry indicator — display-only observability from event stream.
                      Per ISSUE-059B: shows current automatic retry attempt during active execution.
                      Does NOT alter step object, merge logic, or projection-derived retry count. */}
                  {(() => {
                    const _eventStep = eventStepMap.get(step.id);
                    const _isActiveExecution = result?.status === "ACTIVE" || isExecuting;
                    const _liveRetries = Number(_eventStep?.retries || 0);
                    if (
                      _isActiveExecution &&
                      !isWorkflowCancelled &&
                      _eventStep &&
                      Number.isFinite(_liveRetries) &&
                      _liveRetries > 0
                    ) {
                      return (
                        <span
                          className="live-retry-indicator"
                          style={{ fontSize: "0.7rem", color: "#f59e0b", marginLeft: "0.25rem" }}
                          title="Live automatic retry attempt count from event stream (observational only)"
                        >
                          (Live attempt {_liveRetries})
                        </span>
                      );
                    }
                    return null;
                  })()}
                  {status === "ACTIVE" && !isWorkflowCancelled && (
                    <div className="step-processing">
                      {result?.status === "PAUSED" ? "⏸ frozen" : "… processing"}
                    </div>
                  )}
                  {status === "COMPLETED" && stepOutput && (
                    <div className="step-output fade-in">
                      → {stepOutput.execution_result?.result ?? "No result"}
                    </div>
                  )}
                  {/* Transition History — derived ONLY from authoritative state_transition events */}
                  {transitions && transitions.length > 0 && (
                    <div className="step-transitions" style={{ fontSize: "0.7rem", color: "#94a3b8", marginTop: "0.25rem", marginLeft: "1.25rem" }}>
                      {transitions.map((t, idx) => (
                        <span key={idx} title={`Seq ${t.bus_sequence_id} — ${t.timestamp}`}>
                          {t.from} → {t.to}{idx < transitions.length - 1 ? ", " : ""}
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="muted">{isExecuting ? "Waiting for events…" : "No step events available."}</p>
        );
      })()}

      {events.length > 0 && (
        <span
          className="event-count"
          title="Events received — chronology available in Workflow Studio"
          style={{
            color: "#94a3b8",
            fontSize: "0.75rem",
            padding: "0.25rem 0",
            display: "block",
          }}
        >
          {events.length} events received
        </span>
      )}
    </section>
  );
}

