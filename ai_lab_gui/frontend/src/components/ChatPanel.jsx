import { useState } from "react";
import { api } from "../api.js";

export default function ChatPanel({ onResult }) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handleSend() {
    if (!input.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.execute(input.trim());
      onResult(result);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
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
          disabled={loading}
        />
        <button className="btn-primary" onClick={handleSend} disabled={loading || !input.trim()}>
          {loading ? "Running…" : "Send →"}
        </button>
      </div>
      {error && <div className="error-badge">⚠ {error}</div>}
    </section>
  );
}
