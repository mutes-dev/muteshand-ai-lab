import { useState, useEffect } from "react";
import { api } from "../api.js";
import { log } from "../utils/log.js";

export default function ControlPanel({
  onBackgroundStart,
  onResumeStreamStart,
  workflowId
}) {
  const [bgInput, setBgInput] = useState("");
  const [error, setError] = useState(null);

  async function act(fn) {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    }
  }

  async function handlePause() {
    log("PAUSE_CLICK", { workflowId });
    const res = await api.pause(workflowId);
    log("PAUSE_RESPONSE", res);
  }

  async function handleResume() {
    log("RESUME_CLICK", { workflowId });
    const res = await api.resume(workflowId);
    log("RESUME_RESPONSE", res);
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
        <div className="btn-group">
          <button className="btn-control" onClick={() => act(handlePause)}>
            Pause
          </button>
          <button
            className="btn-control"
            onClick={() => act(handleResume)}
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
