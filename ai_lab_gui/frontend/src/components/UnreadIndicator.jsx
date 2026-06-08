import { useState, useEffect } from "react";
import { api } from "../api.js";

/**
 * UnreadIndicator — ISSUE-096B Run 2
 * Minimal unread notification count badge in app chrome.
 * Polls GET /notifications every 5 seconds.
 * Does NOT expand into a full notification panel.
 */
export default function UnreadIndicator() {
  const [count, setCount] = useState(0);

  useEffect(() => {
    async function poll() {
      try {
        const res = await api.getNotifications();
        setCount(res.unread ?? 0);
      } catch (e) {
        console.log("[UnreadIndicator:poll_error]", e.message);
      }
    }
    poll();
    const id = setInterval(poll, 5000);
    return () => clearInterval(id);
  }, []);

  if (count === 0) return null;

  return (
    <span className="unread-indicator" title={`${count} unread notification${count !== 1 ? "s" : ""}`}>
      <span className="unread-indicator__dot">●</span>
      <span className="unread-indicator__count">{count}</span>
    </span>
  );
}
