const BASE = "http://localhost:8000";

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
    headers: { "Content-Type": "application/json" },
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
  pause: () => post("/pause", {}),
  resume: () => post("/resume", {}),
  setOverride: (value) => post("/override", { value }),
  getStatus: () => get("/status"),
  backgroundStart: (input) => post("/background/start", { input }),
  backgroundList: () => get("/background/list"),
  backgroundStatus: (id) => get(`/background/status/${id}`),
  approvalPending: () => get("/approval/pending"),
  approve: (step_id) => post("/approve", { step_id, approved: true }),
  deny: (step_id) => post("/deny", { step_id, approved: false }),
  debugState: () => get("/debug/control_state"),
  getTrace: (workflowId) => get(`/trace/${workflowId}`),
};
