import { useState } from "react";
import { api, log } from "../api.js";

// Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
// Frontend does NOT synthesize workflow ownership
// Backend provides authoritative workflow identity via projection

export default function ChatPanel({ onResult, onExecutionStart, onStreamStart, isExecuting }) {
  const [input, setInput] = useState("");
  const [error, setError] = useState(null);

  async function handleSend() {
    if (!input.trim()) return;
    setError(null);

    // Per GUI_FUNCTIONALITY_CONTRACT_V1: Chat must always operate on a workflow
    // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
    // Backend creates workflow and returns authoritative workflow_id in projection
    log("CHAT_SEND", { input: input.trim() });

    if (onExecutionStart) onExecutionStart();
    try {
      // Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1: Frontend is projection-only
      // Backend provides authoritative workflow identity - no local ownership synthesis
      const stream = await api.executeStream(input.trim());
      if (onStreamStart) onStreamStart(stream.bg_id);
    } catch (e) {
      setError(e.message);
    }
  }

  function handleKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
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
          disabled={isExecuting}
        />
        <button className="btn-primary" onClick={handleSend} disabled={isExecuting || !input.trim()}>
          {isExecuting ? "Running…" : "Send →"}
        </button>
      </div>
      {error && <div className="error-badge">⚠ {error}</div>}
    </section>
  );
}
