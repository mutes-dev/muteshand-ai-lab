import { useRef, useEffect, useCallback } from "react";

// =============================================================================
// ISSUE-074C — Sprint 9C-1C: Frontend WebSocket Hook
// =============================================================================
// Per OBSERVABILITY_AND_DASHBOARD_ARCHITECTURE_CONTRACT_V1 §4:
// WebSocket is transport-only. Frontend remains projection-only.
//
// Per GUI_FUNCTIONALITY_CONTRACT_V1:
// Frontend sends intent only. Command ack = request accepted;
// lifecycle truth arrives via events.
//
// Per PROJECTION_CONTINUITY_CONTRACT_V1:
// Reconnect replay uses bus_sequence_id as authoritative cursor.
// Clients MUST deduplicate by bus_sequence_id.
// =============================================================================

const WS_BASE = "ws://localhost:8000";

/**
 * React hook for workflow-scoped WebSocket live event streaming.
 *
 * Responsibilities:
 * - Manage WebSocket lifecycle (open, message, error, close)
 * - Send initialization commands on open (client_hello, client_ready, subscribe_workflow)
 * - Handle incoming messages (event, ack, error, heartbeat)
 * - Dedupe events by bus_sequence_id
 * - Transform WebSocket events to existing frontend event shape
 * - On close/error, notify parent for fallback to polling/SSE
 *
 * Does NOT:
 * - Send lifecycle mutation commands (pause, resume, cancel, retry, etc.)
 * - Synthesize lifecycle truth
 * - Replace projection/snapshot refresh
 */
export function useWorkflowWebSocket({
  workflowId,
  onEvent,
  onConnectionChange,
  knownBusSeqRef,
  enabled = true,
}) {
  const wsRef = useRef(null);
  const seenBusSeqRef = useRef(new Set());
  const closedIntentionallyRef = useRef(false);

  // Ref wrappers for callbacks to avoid re-subscription on identity changes
  const onEventRef = useRef(onEvent);
  const onConnectionChangeRef = useRef(onConnectionChange);
  const knownBusSeqRefWrapper = useRef(knownBusSeqRef);
  onEventRef.current = onEvent;
  onConnectionChangeRef.current = onConnectionChange;
  knownBusSeqRefWrapper.current = knownBusSeqRef;

  const sendCommand = useCallback(
    (command, payload = {}) => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        const msg = {
          type: "command",
          schema_version: 1,
          message_id: `cmd_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
          workflow_id: workflowId,
          timestamp: new Date().toISOString(),
          command,
          payload,
        };
        try {
          ws.send(JSON.stringify(msg));
        } catch (e) {
          console.error("[WS:SEND_ERROR]", { workflowId, command, error: e.message });
        }
      }
    },
    [workflowId]
  );

  useEffect(() => {
    if (!enabled || !workflowId) return;

    // Clear dedupe set on new connection
    seenBusSeqRef.current.clear();
    closedIntentionallyRef.current = false;

    const url = `${WS_BASE}/ws/workflows/${workflowId}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("[WS:OPEN]", { workflowId });
      onConnectionChangeRef.current?.("connected");

      // Send safe non-mutating initialization commands
      sendCommand("client_hello");
      sendCommand("client_ready");

      // Subscribe with last known bus_sequence_id for replay
      const sinceSeq = knownBusSeqRefWrapper.current?.current ?? 0;
      sendCommand("subscribe_workflow", {
        since_sequence: sinceSeq > 0 ? sinceSeq : undefined,
      });
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
      } catch (e) {
        console.error("[WS:PARSE_ERROR]", { workflowId, error: e.message });
      }
    };

    ws.onclose = (event) => {
      console.log("[WS:CLOSE]", { workflowId, code: event.code, reason: event.reason });
      wsRef.current = null;
      onConnectionChangeRef.current?.("disconnected");
    };

    ws.onerror = (err) => {
      console.error("[WS:ERROR]", { workflowId, error: err });
      wsRef.current = null;
      onConnectionChangeRef.current?.("error");
    };

    function handleMessage(msg) {
      if (!msg || typeof msg !== "object") return;

      switch (msg.type) {
        case "event": {
          const busSeq = msg.bus_sequence_id;
          if (busSeq !== undefined) {
            // Update shared knownBusSeqRef
            if (knownBusSeqRefWrapper.current) {
              knownBusSeqRefWrapper.current.current = busSeq;
            }
            // Dedupe by bus_sequence_id
            if (seenBusSeqRef.current.has(busSeq)) {
              console.log("[WS:DEDUPE]", { workflowId, bus_sequence_id: busSeq });
              return;
            }
            seenBusSeqRef.current.add(busSeq);
          }

          // Transform WebSocket event to existing frontend event shape
          // so setEvents dedupe logic works seamlessly
          const normalizedEvent = {
            event_id: busSeq ?? -1,
            event_type: msg.event_type,
            data: msg.payload ?? {},
            timestamp: msg.timestamp,
            bus_sequence_id: busSeq,
          };

          onEventRef.current?.(normalizedEvent);
          break;
        }

        case "ack": {
          console.log("[WS:ACK]", {
            workflowId,
            command: msg.command,
            status: msg.status,
            payload: msg.payload,
          });
          break;
        }

        case "error": {
          console.error("[WS:SERVER_ERROR]", {
            workflowId,
            status: msg.status,
            reason: msg.reason,
            detail: msg.detail,
          });
          break;
        }

        case "heartbeat": {
          console.log("[WS:HEARTBEAT]", { workflowId });
          break;
        }

        default: {
          console.warn("[WS:UNKNOWN_TYPE]", { workflowId, type: msg.type });
        }
      }
    }

    return () => {
      closedIntentionallyRef.current = true;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        try {
          ws.close();
        } catch (e) {
          // ignore
        }
      }
      wsRef.current = null;
    };
  }, [workflowId, enabled, sendCommand]);

  return {
    sendCommand,
    get readyState() {
      return wsRef.current?.readyState ?? WebSocket.CLOSED;
    },
  };
}
