/**
 * MEMORY PANEL — ISSUE-077 (Sprint 6)
 *
 * Per MEMORY_STORAGE_CONTRACT_V1:
 * - Memory is advisory-only, operator-managed context
 * - Memory MUST NOT influence execution_result, governance, lifecycle, or projection truth
 * - This panel provides visibility and manual operator control ONLY
 *
 * Per GUI_FUNCTIONALITY_CONTRACT_V1:
 * - GUI sends operator intent only
 * - GUI MUST NOT synthesize authority
 * - GUI MUST NOT assume mutation success before backend confirmation
 *
 * Per ISSUE-078 BOUNDARY:
 * - No memory context injection into planner/agent/workflow
 * - No automatic learning or adaptation
 *
 * PROHIBITED:
 * - No integration with Execution Result, lifecycle badges, retry metadata
 * - No projection truth claims
 * - No Task Hub / History / AG1 behavior changes
 */

import { useState, useEffect, useCallback } from "react";
import { api } from "../api.js";
import DangerConfirmModal from "./DangerConfirmModal.jsx";

const SCOPE_GLOBAL = "GLOBAL";
const SCOPE_PROJECT = "PROJECT";

const CATEGORIES = ["behavior", "preference", "pattern", "context"];

const LS_SCOPE_KEY = "memory_panel_scope";
const LS_PROJECT_KEY = "memory_panel_project_id";
const LS_PROJECT_HISTORY_KEY = "memory_panel_project_history";

function formatValue(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function parseInputValue(raw) {
  const trimmed = raw.trim();
  if (trimmed === "") return "";
  try {
    return JSON.parse(trimmed);
  } catch {
    return trimmed;
  }
}

function loadProjectHistory() {
  try {
    return JSON.parse(localStorage.getItem(LS_PROJECT_HISTORY_KEY) || "[]");
  } catch {
    return [];
  }
}

function saveProjectHistory(id) {
  if (!id || !id.trim()) return;
  const existing = loadProjectHistory();
  const updated = [id.trim(), ...existing.filter((x) => x !== id.trim())].slice(0, 20);
  try {
    localStorage.setItem(LS_PROJECT_HISTORY_KEY, JSON.stringify(updated));
  } catch {
    // localStorage unavailable — not fatal
  }
}

export default function MemoryPanel() {
  const [scope, setScope] = useState(() => localStorage.getItem(LS_SCOPE_KEY) || SCOPE_GLOBAL);
  const [projectId, setProjectId] = useState(() => localStorage.getItem(LS_PROJECT_KEY) || "");
  const [projectHistory, setProjectHistory] = useState(loadProjectHistory);
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Create form state
  const [createKey, setCreateKey] = useState("");
  const [createValue, setCreateValue] = useState("");
  const [createCategory, setCreateCategory] = useState("context");
  const [createConfidence, setCreateConfidence] = useState(0.5);
  const [createEditable, setCreateEditable] = useState(true);
  const [createDeletable, setCreateDeletable] = useState(true);

  // Edit state
  const [editingKey, setEditingKey] = useState(null);
  const [editValue, setEditValue] = useState("");

  // Danger modal state
  const [modalConfig, setModalConfig] = useState(null);
  const [modalCallback, setModalCallback] = useState(null);

  // Persist scope and projectId to localStorage on change
  useEffect(() => {
    try { localStorage.setItem(LS_SCOPE_KEY, scope); } catch { /* non-fatal */ }
  }, [scope]);

  useEffect(() => {
    try { localStorage.setItem(LS_PROJECT_KEY, projectId); } catch { /* non-fatal */ }
  }, [projectId]);

  const loadEntries = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const pid = scope === SCOPE_PROJECT ? projectId || null : null;
      const res = await api.memoryList(scope, pid);
      setEntries(res.entries || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [scope, projectId]);

  useEffect(() => {
    loadEntries();
  }, [loadEntries]);

  function requestDangerConfirm(config, callback) {
    setModalConfig(config);
    setModalCallback(() => callback);
  }

  function handleModalConfirm() {
    setModalConfig(null);
    if (modalCallback) modalCallback();
    setModalCallback(null);
  }

  function handleModalCancel() {
    setModalConfig(null);
    setModalCallback(null);
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!createKey.trim()) {
      setError("Key is required");
      return;
    }
    setError(null);
    try {
      const payload = {
        scope,
        key: createKey.trim(),
        value: parseInputValue(createValue),
        category: createCategory,
        confidence: parseFloat(createConfidence) || 0.5,
        editable: createEditable,
        deletable: createDeletable,
      };
      if (scope === SCOPE_PROJECT) {
        const pid = projectId.trim() || undefined;
        payload.project_id = pid;
        if (pid) {
          saveProjectHistory(pid);
          setProjectHistory(loadProjectHistory());
        }
      }
      await api.memoryWrite(payload);
      setCreateKey("");
      setCreateValue("");
      setCreateCategory("context");
      setCreateConfidence(0.5);
      setCreateEditable(true);
      setCreateDeletable(true);
      await loadEntries();
    } catch (err) {
      setError(err.message);
    }
  }

  function handleDelete(entry) {
    requestDangerConfirm(
      {
        title: "Delete Memory Entry",
        confirmLabel: "Delete Entry",
        rows: [
          { label: "Action", value: "Delete Entry" },
          { label: "Scope", value: entry.scope },
          ...(entry.scope === SCOPE_PROJECT ? [{ label: "Project ID", value: entry.project_id || "—" }] : []),
          { label: "Key", value: entry.key },
          { label: "Category", value: entry.category },
        ],
      },
      async () => {
        setError(null);
        try {
          const payload = { scope: entry.scope, key: entry.key };
          if (entry.scope === SCOPE_PROJECT) payload.project_id = entry.project_id;
          await api.memoryDelete(payload);
          await loadEntries();
        } catch (err) {
          setError(err.message);
        }
      }
    );
  }

  function startEdit(entry) {
    if (!entry.editable) {
      setError("This entry is not editable.");
      return;
    }
    setEditingKey(entry.key);
    setEditValue(formatValue(entry.value));
  }

  async function handleSaveEdit(entry) {
    setError(null);
    try {
      const payload = {
        scope: entry.scope,
        key: entry.key,
        value: parseInputValue(editValue),
      };
      if (entry.scope === SCOPE_PROJECT) {
        payload.project_id = entry.project_id;
      }
      await api.memoryUpdate(payload);
      setEditingKey(null);
      setEditValue("");
      await loadEntries();
    } catch (err) {
      setError(err.message);
    }
  }

  function cancelEdit() {
    setEditingKey(null);
    setEditValue("");
  }

  function handleReset() {
    const scopeLabel = scope === SCOPE_GLOBAL ? "Global" : "Project";
    const pid = scope === SCOPE_PROJECT ? (projectId.trim() || "—") : null;
    requestDangerConfirm(
      {
        title: `Reset ${scopeLabel} Memory`,
        confirmLabel: `Reset ${scopeLabel} Memory`,
        rows: [
          { label: "Action", value: "Reset Memory" },
          { label: "Scope", value: scope },
          ...(pid ? [{ label: "Project ID", value: pid }] : []),
          { label: "Effect", value: "All entries in this scope will be permanently removed" },
        ],
      },
      async () => {
        setError(null);
        try {
          const payload = { scope };
          if (scope === SCOPE_PROJECT) {
            payload.project_id = projectId.trim() || undefined;
          }
          await api.memoryReset(payload);
          await loadEntries();
        } catch (err) {
          setError(err.message);
        }
      }
    );
  }

  function handleScopeChange(newScope) {
    setScope(newScope);
    setEditingKey(null);
  }

  function handleProjectIdChange(val) {
    setProjectId(val);
  }

  function handleProjectIdBlur() {
    if (projectId.trim()) {
      saveProjectHistory(projectId.trim());
      setProjectHistory(loadProjectHistory());
    }
  }

  return (
    <>
      <DangerConfirmModal
        config={modalConfig}
        onConfirm={handleModalConfirm}
        onCancel={handleModalCancel}
      />

      <section className="panel memory-panel">
        <div className="memory-panel-header">
          <h2>Memory Inspector</h2>
          <span className="memory-advisory-label">Advisory / Operator-Managed Context</span>
        </div>

        {/* Scope selector */}
        <div className="memory-scope-bar">
          <button
            className={scope === SCOPE_GLOBAL ? "active" : ""}
            onClick={() => handleScopeChange(SCOPE_GLOBAL)}
          >
            Global
          </button>
          <button
            className={scope === SCOPE_PROJECT ? "active" : ""}
            onClick={() => handleScopeChange(SCOPE_PROJECT)}
          >
            Project
          </button>
        </div>

        {/* Project ID input with datalist */}
        {scope === SCOPE_PROJECT && (
          <div className="memory-project-input">
            <label htmlFor="memory-project-id-input">Project ID</label>
            <input
              id="memory-project-id-input"
              type="text"
              list="memory-project-id-list"
              value={projectId}
              onChange={(e) => handleProjectIdChange(e.target.value)}
              onBlur={handleProjectIdBlur}
              placeholder="Enter or select project identifier"
              autoComplete="off"
            />
            {projectHistory.length > 0 && (
              <datalist id="memory-project-id-list">
                {projectHistory.map((pid) => (
                  <option key={pid} value={pid} />
                ))}
              </datalist>
            )}
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="memory-error">
            {error}
          </div>
        )}

        {/* Entries list */}
        <div className="memory-entries">
          {loading ? (
            <p className="memory-loading">Loading entries…</p>
          ) : entries.length === 0 ? (
            <p className="memory-empty">No entries found.</p>
          ) : (
            <table className="memory-table">
              <thead>
                <tr>
                  <th>Key</th>
                  <th>Category</th>
                  <th>Value</th>
                  <th>Confidence</th>
                  <th>Source</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id}>
                    <td className="memory-cell-key">{entry.key}</td>
                    <td className="memory-cell-category">{entry.category}</td>
                    <td className="memory-cell-value">
                      {editingKey === entry.key ? (
                        <textarea
                          className="memory-edit-textarea"
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          rows={3}
                        />
                      ) : (
                        <span title={formatValue(entry.value)}>
                          {formatValue(entry.value).length > 60
                            ? formatValue(entry.value).slice(0, 60) + "…"
                            : formatValue(entry.value)}
                        </span>
                      )}
                    </td>
                    <td className="memory-cell-confidence">{entry.confidence}</td>
                    <td className="memory-cell-source">{entry.source}</td>
                    <td className="memory-cell-actions">
                      {editingKey === entry.key ? (
                        <>
                          <button
                            className="memory-btn-save"
                            onClick={() => handleSaveEdit(entry)}
                          >
                            Save
                          </button>
                          <button
                            className="memory-btn-cancel"
                            onClick={cancelEdit}
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            className="memory-btn-edit"
                            onClick={() => startEdit(entry)}
                            disabled={!entry.editable}
                            title={entry.editable ? "Edit" : "Not editable"}
                          >
                            Edit
                          </button>
                          <button
                            className="memory-btn-delete memory-btn-danger"
                            onClick={() => handleDelete(entry)}
                            disabled={!entry.deletable}
                            title={entry.deletable ? "Delete" : "Not deletable"}
                          >
                            Delete
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Create form */}
        <form className="memory-create-form" onSubmit={handleCreate}>
          <h3>Add Entry</h3>
          <div className="memory-form-row">
            <input
              type="text"
              placeholder="Key"
              value={createKey}
              onChange={(e) => setCreateKey(e.target.value)}
              required
            />
            <select
              value={createCategory}
              onChange={(e) => setCreateCategory(e.target.value)}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <input
              type="number"
              min="0"
              max="1"
              step="0.1"
              value={createConfidence}
              onChange={(e) => setCreateConfidence(e.target.value)}
              title="Confidence (0.0–1.0)"
            />
          </div>
          <textarea
            placeholder="Value (string or JSON)"
            value={createValue}
            onChange={(e) => setCreateValue(e.target.value)}
            rows={3}
          />
          <div className="memory-form-row">
            <label className="memory-checkbox">
              <input
                type="checkbox"
                checked={createEditable}
                onChange={(e) => setCreateEditable(e.target.checked)}
              />
              Editable
            </label>
            <label className="memory-checkbox">
              <input
                type="checkbox"
                checked={createDeletable}
                onChange={(e) => setCreateDeletable(e.target.checked)}
              />
              Deletable
            </label>
            <button type="submit" className="memory-btn-create">
              Add Entry
            </button>
          </div>
        </form>

        {/* Reset control */}
        <div className="memory-reset-bar">
          <button className="memory-btn-reset memory-btn-danger" onClick={handleReset}>
            Reset {scope === SCOPE_GLOBAL ? "Global" : "Project"} Memory
          </button>
          <span className="memory-reset-hint">
            Destructive — requires confirmation
          </span>
        </div>
      </section>
    </>
  );
}
