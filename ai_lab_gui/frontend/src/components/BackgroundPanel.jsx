import { useState, useEffect } from "react";
import { api } from "../api.js";

const STATUS_COLOR = {
  COMPLETED: "#22c55e",
  FAILED: "#ef4444",
  ACTIVE: "#3b82f6",
  QUEUED: "#94a3b8",
};

export default function BackgroundPanel({ triggerRefresh }) {
  const [workflows, setWorkflows] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);

  useEffect(() => {
    fetchList();
    const id = setInterval(fetchList, 3000);
    return () => clearInterval(id);
  }, [triggerRefresh]);

  async function fetchList() {
    try {
      const res = await api.backgroundList();
      setWorkflows(res.workflows ?? []);
    } catch (_) { }
  }

  async function fetchDetail(id) {
    if (selected === id) {
      setSelected(null);
      setDetail(null);
      return;
    }
    try {
      const res = await api.backgroundStatus(id);
      setDetail(res);
      setSelected(id);
    } catch (e) {
      setDetail({ error: e.message });
    }
  }

  return (
    <section className="panel background-panel">
      <h2>Background Workflows</h2>
      {workflows.length === 0 ? (
        <p className="muted">No background workflows.</p>
      ) : (
        <ul className="bg-list">
          {workflows.map((wf) => {
            const color = STATUS_COLOR[wf.status] ?? "#94a3b8";
            return (
              <li
                key={wf.workflow_id}
                className={`bg-item ${selected === wf.workflow_id ? "selected" : ""}`}
                onClick={() => fetchDetail(wf.workflow_id)}
              >
                <span className="bg-dot" style={{ background: color }} />
                <span className="bg-id">{wf.workflow_id.slice(0, 8)}…</span>
                <span className="bg-status" style={{ color }}>{wf.status}</span>
                <span className="bg-time">{wf.started_at ? new Date(wf.started_at).toLocaleString() : ""}</span>
              </li>
            );
          })}
        </ul>
      )}

      {detail && (
        <div className="bg-detail">
          <h3>Detail: {detail.workflow_id?.slice(0, 8)}…</h3>
          <table className="detail-table">
            <tbody>
              <tr><td>Status</td><td>{detail.status}</td></tr>
              <tr><td>Started</td><td>{detail.started_at ? new Date(detail.started_at).toLocaleString() : "—"}</td></tr>
              <tr><td>Completed</td><td>{detail.completed_at ? new Date(detail.completed_at).toLocaleString() : "—"}</td></tr>
              {detail.error && <tr><td>Error</td><td className="error-text">{detail.error}</td></tr>}
            </tbody>
          </table>
          {detail.result && (
            <pre className="json-dump">{JSON.stringify(detail.result, null, 2)}</pre>
          )}
        </div>
      )}
    </section>
  );
}
