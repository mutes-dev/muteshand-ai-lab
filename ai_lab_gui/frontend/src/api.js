const BASE = "http://localhost:8000";

const HEADERS = {
  "Content-Type": "application/json",
};

export function log(tag, payload) {
  try {
    console.log(`[GUI:${tag}]`, payload);
  } catch { }
}

export async function waitForBackend(expectedAppInstanceId = null, retries = 20, intervalMs = 500) {
  console.log(`[DEBUG] waitForBackend starting: ${retries} retries, ${intervalMs}ms interval`);
  for (let i = 0; i < retries; i++) {
    try {
      console.log(`[DEBUG] Pinging backend /identity attempt ${i + 1}/${retries}`);
      const res = await fetch(`${BASE}/identity`);
      console.log(`[DEBUG] Backend response: ${res.status}`);
      if (res.ok) {
        const identity = await res.json();
        console.log("[DEBUG] Backend identity:", identity);

        // ISSUE-063: Validate identity if expected ID is provided
        if (expectedAppInstanceId) {
          if (identity.app_instance_id !== expectedAppInstanceId) {
            const returnedId = identity.app_instance_id || "missing";
            throw new Error(
              `Backend identity mismatch: expected '${expectedAppInstanceId}', got '${returnedId}'. ` +
              `Another AI Lab backend may be running on port 8000. ` +
              `Close the external backend or restart cleanly.`
            );
          }
        }

        console.log("[DEBUG] Backend is ready and identity verified!");
        return true;
      }
      if (res.status === 404) {
        // /identity not found — external backend or incompatible process
        throw new Error(
          "Port 8000 occupied by a process without /identity endpoint. " +
          "Another AI Lab backend or unrelated service may be running. " +
          "Close the external process or restart cleanly."
        );
      }
    } catch (e) {
      // Distinguish identity mismatch (our thrown error) from network errors
      if (e.message && (
        e.message.includes("Backend identity mismatch") ||
        e.message.includes("Port 8000 occupied")
      )) {
        throw e; // Re-throw specific identity errors
      }
      console.log(`[DEBUG] Backend ping failed: ${e.message}`);
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error("Backend not available after " + retries + " attempts");
}

async function post(path, body) {
  console.log("[API_POST] Starting fetch", { path, body, timestamp: Date.now() });
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: HEADERS,
    body: JSON.stringify(body),
  });
  console.log("[API_POST] Fetch completed", { path, status: res.status, ok: res.ok, timestamp: Date.now() });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    console.log("[API_POST] Response error", { path, error: err, timestamp: Date.now() });
    throw new Error(err.detail || res.statusText);
  }
  const json = await res.json();
  console.log("[API_POST] Response JSON", { path, json, timestamp: Date.now() });
  return json;
}

async function get(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  execute: (input) => post("/execute", { input }),
  pause: async (workflow_id) => {
    console.log("[GUI:CONTROL_DISPATCH]", {
      action: "pause",
      workflowId: workflow_id,
      requestPayload: {},
      timestamp: Date.now()
    });
    log("API_PAUSE_REQUEST", { workflow_id });
    const res = await post(`/pause/${workflow_id}`, {});
    console.log("[GUI:CONTROL_RESPONSE]", {
      action: "pause",
      workflowId: workflow_id,
      response: res,
      timestamp: Date.now()
    });
    log("API_PAUSE_RESPONSE", res);
    return res;
  },
  resume: async (workflow_id) => {
    console.log("[GUI:CONTROL_DISPATCH]", {
      action: "resume",
      workflowId: workflow_id,
      requestPayload: {},
      timestamp: Date.now()
    });
    log("API_RESUME_REQUEST", { workflow_id });
    const res = await post(`/resume/${workflow_id}`, {});
    console.log("[GUI:CONTROL_RESPONSE]", {
      action: "resume",
      workflowId: workflow_id,
      response: res,
      timestamp: Date.now()
    });
    log("API_RESUME_RESPONSE", res);
    return res;
  },
  cancel: async (workflow_id) => {
    // Per WORKFLOW_CANCELLATION_AND_TERMINALIZATION_CONTRACT_V1:
    // Frontend requests cancellation — backend owns lifecycle authority.
    console.log("[GUI:CONTROL_DISPATCH]", {
      action: "cancel",
      workflowId: workflow_id,
      requestPayload: {},
      timestamp: Date.now()
    });
    log("API_CANCEL_REQUEST", { workflow_id });
    const res = await post("/workflow/cancel", { workflow_id });
    console.log("[GUI:CONTROL_RESPONSE]", {
      action: "cancel",
      workflowId: workflow_id,
      response: res,
      timestamp: Date.now()
    });
    log("API_CANCEL_RESPONSE", res);
    return res;
  },
  getStatus: () => get("/status"),
  backgroundStart: (input) => post("/background/start", { input }),
  backgroundList: () => get("/background/list"),
  backgroundStatus: (id) => get(`/background/status/${id}`),
  approvalPending: () => get("/approval/pending"),
  approve: (workflow_id, step_id) => post("/approve", { workflow_id, step_id, approved: true }),
  deny: (workflow_id, step_id) => post("/deny", { workflow_id, step_id, approved: false }),
  debugState: () => get("/debug/control_state"),
  getTrace: (workflowId) => get(`/trace/${workflowId}`),
  getEvents: async (workflowId, since = -1, sinceSequence = -1, limit = 100) => {
    // Per REPLAY_QUERY_PAGINATION:
    // since_sequence (bus_sequence_id) is the authoritative monotonic cursor.
    // since (event_id) is legacy; preserved for backward compatibility.
    const seqParam = sinceSequence >= 0 ? `&since_sequence=${sinceSequence}` : "";
    const res = await get(`/events/${workflowId}?since=${since}${seqParam}&limit=${limit}`);
    log("API_GET_EVENTS", { workflowId, since, sinceSequence, limit, eventCount: res.events?.length });
    return res;
  },
  executeStream: (input, workflow_id = null) => post("/execute/stream", { input, workflow_id }),
  streamWorkflowId: async (bgId) => {
    const res = await get(`/execute/stream/workflow_id/${bgId}`);
    log("API_STREAM_WORKFLOW_ID", { bgId, res });
    return res;
  },
  // Per CANONICAL_PROJECTION_MODEL_V1 §5 + PROJECTION_CONTINUITY_CONTRACT_V1 §4 (SUB-PHASE 3E):
  // Canonical projection refresh — authoritative read from orchestrator-owned projection.
  // GUI MUST use this for hydration on reconnect/reload rather than local synthesis.
  getProjection: (workflowId) => get(`/projection/${workflowId}`),
  getProjectionVersion: (workflowId) => get(`/projection/${workflowId}/version`),
  // Per PROJECTION_CONTINUITY_CONTRACT_V1 §11 (SUB-PHASE 3E):
  // Continuity diagnostics — used to detect gaps on reconnect.
  getProjectionContinuity: (workflowId) => get(`/projection/${workflowId}/continuity`),

  // Per CANONICAL_PROJECTION_MODEL_V1 §7 (Projection Mutation Flow) + GUI_FUNCTIONALITY_CONTRACT_V1:
  // Frontend sends mutation INTENT only.
  // Frontend MUST NOT mutate local state optimistically.
  // Frontend waits for canonical projection refresh after mutation.
  requestMutation: (workflowId, mutationType, payload, actor = "user") => {
    log("MUTATION_INTENT_DISPATCH", { workflowId, mutationType, payload, actor });
    return post(`/workflow/${workflowId}/mutation`, {
      mutation_type: mutationType,
      payload,
      actor,
    });
  },
  // ISSUE-055B Phase 3: Operator-initiated replan for QUEUED_REPLAN_REQUIRED workflows
  replanWorkflow: async (workflow_id) => {
    log("API_REPLAN_REQUEST", { workflow_id });
    const res = await post(`/replan/${workflow_id}`, {});
    log("API_REPLAN_RESPONSE", res);
    return res;
  },

  // Per Phase 3F-XA recovery: discover non-terminal streams on reconnect.
  // DEPRECATED: Use getAuthoritativeWorkflows() for authority-first restoration.
  getActiveStreams: () => get("/execute/stream/active"),
  // Per LIFECYCLE_AUTHORITY_CONTRACT_V1 §WORKFLOW ENUMERATION RULES:
  // Authoritative workflow enumeration from Lifecycle Registry.
  // Frontend MUST use this for reconnect recovery instead of stream-derived sources.
  getAuthoritativeWorkflows: () => get("/workflows/authoritative"),

  // ISSUE-061 Phase 1: Historical workflow enumeration for History/Archive
  getHistoricalWorkflows: () => get("/workflows/historical"),

  // ISSUE-060: Workflow retention operationalization
  // Per GUI_FUNCTIONALITY_CONTRACT_V1: Frontend sends intent only, waits for backend confirmation.
  archiveWorkflow: async (workflow_id) => {
    log("API_ARCHIVE_REQUEST", { workflow_id });
    const res = await post(`/workflow/${workflow_id}/archive`, {});
    log("API_ARCHIVE_RESPONSE", res);
    return res;
  },
  dismissWorkflow: async (workflow_id) => {
    log("API_DISMISS_REQUEST", { workflow_id });
    const res = await post(`/workflow/${workflow_id}/dismiss`, {});
    log("API_DISMISS_RESPONSE", res);
    return res;
  },

  // =============================================================================
  // PHASE 4A.1 — RUNTIME OBSERVABILITY + DETERMINISTIC VALIDATION SUPPORT
  // =============================================================================
  // Per VALIDATION_ARCHITECTURE.txt §9: Runtime Survivability Validation
  // Minimal read-only runtime inspection for debugging and deterministic testing.
  // =============================================================================

  /**
   * GET /runtime/inspect/{workflowId}
   * Returns comprehensive runtime inspection metadata.
   * Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1: execution_generation visibility
   */
  runtimeInspect: (workflowId) => get(`/runtime/inspect/${workflowId}`),

  /**
   * GET /runtime/registry/summary
   * Returns runtime registry summary for survivability debugging.
   * Per LIFECYCLE_AUTHORITY_CONTRACT_V1: Runtime registry visibility
   */
  runtimeRegistrySummary: () => get("/runtime/registry/summary"),

  // =============================================================================
  // ISSUE-074B — SSE EventSource Helper
  // =============================================================================
  // Per ISSUE-074B: Event-hint-only transport. No projection snapshots.
  // EventSource connects to /events/{workflow_id}/sse.
  // Browser auto-reconnect sends Last-Event-ID header for gap repair.
  // =============================================================================
  createWorkflowEventSource: (workflowId, { onMessage, onError, onOpen } = {}) => {
    const url = `${BASE}/events/${workflowId}/sse`;
    const eventSource = new EventSource(url);

    eventSource.addEventListener("workflow_event", (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage?.(data, event.lastEventId);
      } catch (e) {
        console.error("[SSE:PARSE_ERROR]", { workflowId, error: e.message });
      }
    });

    eventSource.onerror = (err) => {
      console.log("[SSE:ERROR]", {
        workflowId,
        readyState: eventSource.readyState,
        error: err,
      });
      onError?.(err);
    };

    eventSource.onopen = () => {
      console.log("[SSE:OPEN]", { workflowId });
      onOpen?.();
    };

    return {
      close: () => {
        console.log("[SSE:CLOSE]", { workflowId });
        eventSource.close();
      },
      get readyState() {
        return eventSource.readyState;
      },
    };
  },

  // =============================================================================
  // ISSUE-077 — MEMORY MANAGEMENT API
  // =============================================================================
  // Per MEMORY_STORAGE_CONTRACT_V1:
  // - Memory is advisory-only, operator-managed context
  // - These helpers call ONLY /memory/* endpoints
  // - No workflow control, governance, or execution functions are invoked
  // =============================================================================

  memoryList: (scope = null, project_id = null, category = null) => {
    const params = new URLSearchParams();
    if (scope) params.set("scope", scope);
    if (project_id) params.set("project_id", project_id);
    if (category) params.set("category", category);
    const query = params.toString();
    return get(`/memory/list${query ? "?" + query : ""}`);
  },

  memoryRead: (scope, key, project_id = null) => {
    const params = new URLSearchParams();
    params.set("scope", scope);
    params.set("key", key);
    if (project_id) params.set("project_id", project_id);
    return get(`/memory/read?${params.toString()}`);
  },

  memoryWrite: (payload) => post("/memory/write", payload),

  memoryUpdate: (payload) => post("/memory/update", payload),

  memoryDelete: (payload) => post("/memory/delete", payload),

  memoryReset: (payload) => post("/memory/reset", payload),

  // =============================================================================
  // ISSUE-094B + ISSUE-094C — LLM BUDGET / PROVIDER ROUTING OBSERVABILITY
  // =============================================================================
  llmBudgetStatus: () => get("/llm/budget/status"),
  llmBudgetRefresh: () => post("/llm/budget/refresh", {}),
  llmSettingsUpdate: (payload) => post("/llm/settings", payload),
  llmSettingsResetLocal: () => post("/llm/settings/reset-local", {}),
  llmUsageRecent: (limit = 10) => get(`/llm/usage/recent?limit=${limit}`),
  llmUsageWorkflow: (workflowId, limit = 50) =>
    get(`/llm/usage/workflow/${encodeURIComponent(workflowId)}?limit=${limit}`),
};
