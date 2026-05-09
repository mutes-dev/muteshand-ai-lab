import { useState } from "react";
import { api, log } from "../api.js";

export default function ChatPanel({ onResult, onExecutionStart, onStreamStart, isExecuting, activeWorkflowId }) {
  const [input, setInput] = useState("");
  const [error, setError] = useState(null);

  async function handleSend() {
    if (!input.trim()) return;
    setError(null);

    // Per GUI_FUNCTIONALITY_CONTRACT_V1: Chat must always operate on a workflow
    // If no active workflow, we let backend create one and return workflow_id
    log("CHAT_SEND", { input: input.trim(), activeWorkflowId });

    if (onExecutionStart) onExecutionStart();
    try {
      // Include activeWorkflowId if available - backend will use it or create new workflow
      const stream = await api.executeStream(input.trim(), activeWorkflowId);
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
