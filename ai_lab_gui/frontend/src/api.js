const BASE = "http://localhost:8000";

const HEADERS = {
  "Content-Type": "application/json",
};

export function log(tag, payload) {
  try {
    console.log(`[GUI:${tag}]`, payload);
  } catch { }
}

export async function waitForBackend(retries = 20, intervalMs = 500) {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`${BASE}/status`);
      if (res.ok) return;
    } catch (_) { }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error("Backend not available after " + retries + " attempts");
}

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: HEADERS,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
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
  setOverride: (value) => post("/override", { value }),
  getStatus: () => get("/status"),
  backgroundStart: (input) => post("/background/start", { input }),
  backgroundList: () => get("/background/list"),
  backgroundStatus: (id) => get(`/background/status/${id}`),
  approvalPending: () => get("/approval/pending"),
  approve: (workflow_id, step_id) => post("/approve", { workflow_id, step_id, approved: true }),
  deny: (workflow_id, step_id) => post("/deny", { workflow_id, step_id, approved: false }),
  debugState: () => get("/debug/control_state"),
  getTrace: (workflowId) => get(`/trace/${workflowId}`),
  getEvents: async (workflowId, since = -1, limit = 100) => {
    const res = await get(`/events/${workflowId}?since=${since}&limit=${limit}`);
    log("API_GET_EVENTS", { workflowId, since, limit, eventCount: res.events?.length });
    return res;
  },
  executeStream: (input, workflow_id = null) => post("/execute/stream", { input, workflow_id }),
  streamWorkflowId: async (bgId) => {
    const res = await get(`/execute/stream/workflow_id/${bgId}`);
    log("API_STREAM_WORKFLOW_ID", { bgId, res });
    return res;
  },
};
