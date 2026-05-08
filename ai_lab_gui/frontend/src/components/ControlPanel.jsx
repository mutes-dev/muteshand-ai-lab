import { useState, useEffect } from "react";
import { api } from "../api.js";
import { log } from "../utils/log.js";

export default function ControlPanel({
  onBackgroundStart,
  onResumeStreamStart,
  workflowId
}) {
  const [status, setStatus] = useState({ paused: false, override: false });
  const [bgInput, setBgInput] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchStatus();
    const id = setInterval(fetchStatus, 2000);
    return () => clearInterval(id);
  }, []);

  async function fetchStatus() {
    try {
      const s = await api.getStatus();
      setStatus(s);
    } catch (_) { }
  }

  async function act(fn) {
    setError(null);
    try {
      await fn();
      await fetchStatus();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handlePause() {
    log("PAUSE_CLICK", { workflowId });
    const res = await api.pause();
    log("PAUSE_RESPONSE", res);
    await fetchStatus();
  }

  async function handleResume() {
    log("RESUME_CLICK", { workflowId });
    const res = await api.resume(workflowId);
    log("RESUME_RESPONSE", res);
    await fetchStatus();
    // Start streaming for the new bg_id returned by resume
    if (res.bg_id && onResumeStreamStart) {
      onResumeStreamStart(res.bg_id);
    }
  }

  async function handleBgStart() {
    if (!bgInput.trim()) return;
    try {
      const res = await api.backgroundStart(bgInput.trim());
      setBgInput("");
      if (onBackgroundStart) onBackgroundStart(res.workflow_id);
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <section className="panel control-panel">
      <h2>Controls</h2>

      <div className="control-row">
        <div className="status-indicators">
          <span className={`indicator ${status.paused ? "on" : "off"}`}>
            {status.paused ? "⏸ Paused" : "▶ Running"}
          </span>
          <span className={`indicator ${status.override ? "on-warn" : "off"}`}>
            {status.override ? "🚀 Override ON" : "🛑 Override OFF"}
          </span>
        </div>

        <div className="btn-group">
          <button className="btn-control" onClick={() => act(handlePause)} disabled={status.paused}>
            Pause
          </button>
          <button
            className="btn-control"
            onClick={() => {
              if (!workflowId) {
                console.warn("[ControlPanel] No workflow_id available for resume");
                log("RESUME_ERROR", { reason: "no_workflow_id" });
                return;
              }
              act(handleResume);
            }}
            disabled={!status.paused || !workflowId}
          >
            Resume
          </button>
          <button
            className={`btn-control ${status.override ? "active" : ""}`}
            onClick={() => act(() => api.setOverride(!status.override))}
          >
            Toggle Override
          </button>
        </div>
      </div>

      <div className="bg-start-row">
        <input
          className="bg-input"
          placeholder="Background task input…"
          value={bgInput}
          onChange={(e) => setBgInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleBgStart()}
        />
        <button className="btn-secondary" onClick={handleBgStart} disabled={!bgInput.trim()}>
          Start Background
        </button>
      </div>

      {error && <div className="error-badge">⚠ {error}</div>}
    </section>
  );
}
