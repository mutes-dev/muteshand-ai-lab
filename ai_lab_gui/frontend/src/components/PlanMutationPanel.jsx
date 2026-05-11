/**
 * PLAN MUTATION PANEL — PHASE 4B.1 SUB-PHASE 3E (Frontend)
 *
 * Per CANONICAL_PROJECTION_MODEL_V1 §7 (Projection Mutation Flow):
 * - Frontend sends mutation INTENT only
 * - Frontend waits for canonical projection refresh (step 8)
 * - Frontend MUST NOT directly mutate canonical projections
 * - Frontend MUST NOT optimistically update local state
 *
 * Per GUI_FUNCTIONALITY_CONTRACT_V1 §LIFECYCLE ACTION MODEL:
 * - GUI actions REQUEST mutations — they do NOT define them
 * - Lifecycle transitions are validated and committed by Lifecycle Authority
 * - GUI MUST NOT assume transition success before authority confirmation
 *
 * Per PLAN_CONTROL_CONTRACT_V1 §PLAN EDITING:
 * - edit step, add step, retry step are allowed in this phase
 * - reorder/drag-drop deferred (not this phase)
 *
 * PROHIBITED:
 * - No optimistic local state mutation
 * - No local dependency reconstruction
 * - No lifecycle synthesis
 * - No drag/drop reorder
 * - No batch editing
 * - No collaborative editing
 */

import { useState } from "react";
import { api } from "../api.js";

// Allowed mutation types this phase
const MUTATION_EDIT_STEP   = "edit_step";
const MUTATION_ADD_STEP    = "add_step";
const MUTATION_RETRY_STEP  = "retry_step";

// Fields editable per PLAN_CONTROL_CONTRACT_V1 §EDIT VALIDATION
const EDITABLE_FIELDS = ["purpose", "expected_outcome", "risk", "importance"];

const RISK_OPTIONS    = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const IMPORTANCE_OPTIONS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

/**
 * PlanMutationPanel
 *
 * Provides edit step modal, add step action, retry action.
 * All mutations are sent as intents via api.requestMutation().
 * After intent dispatched, waits for canonical projection refresh — NO optimistic update.
 *
 * Props:
 *   workflowId       — active workflow_id (required for all mutation requests)
 *   steps            — canonical StepProjection[] from WorkflowProjection
 *   onMutationComplete — callback(result) when mutation succeeds and projection is refreshed
 *   disabled         — disable all controls (e.g. during execution or terminal state)
 */
export default function PlanMutationPanel({
  workflowId,
  steps = [],
  onMutationComplete,
  disabled = false,
}) {
  // Modal state — only one modal open at a time
  const [editModal, setEditModal]   = useState(null);  // {step} or null
  const [addModal, setAddModal]     = useState(false);
  const [pending, setPending]       = useState(false);
  const [lastError, setLastError]   = useState(null);
  const [lastResult, setLastResult] = useState(null);

  // ── Shared mutation dispatch ────────────────────────────────────────────────
  async function dispatchMutation(mutationType, payload) {
    if (!workflowId) {
      setLastError("No active workflow — cannot send mutation intent.");
      return;
    }
    setPending(true);
    setLastError(null);
    setLastResult(null);

    try {
      // Send intent — API forwards to orchestrator authority
      // Per CANONICAL_PROJECTION_MODEL_V1 §7: GUI sends intent, waits for projection re-emission
      const result = await api.requestMutation(workflowId, mutationType, payload);

      // Per GUI_FUNCTIONALITY_CONTRACT_V1: do NOT optimistically update local state
      // The canonical projection will be refreshed via poll (WorkflowProjectionView)
      setLastResult(result);
      if (onMutationComplete) onMutationComplete(result);
    } catch (err) {
      // Report rejection; per contract — GUI MUST explain failure to user
      setLastError(err.message || "mutation_failed");
    } finally {
      setPending(false);
      setEditModal(null);
      setAddModal(false);
    }
  }

  // ── EDIT STEP ───────────────────────────────────────────────────────────────
  function openEditModal(step) {
    if (disabled || pending) return;
    setLastError(null);
    setLastResult(null);
    setEditModal({ step, fields: { ...step } });
  }

  function handleEditFieldChange(field, value) {
    setEditModal(prev => ({
      ...prev,
      fields: { ...prev.fields, [field]: value },
    }));
  }

  async function submitEdit() {
    if (!editModal) return;
    const { step, fields } = editModal;

    // Build updates: only include fields that changed
    const updates = {};
    for (const f of EDITABLE_FIELDS) {
      if (fields[f] !== step[f]) {
        updates[f] = fields[f];
      }
    }

    if (Object.keys(updates).length === 0) {
      setEditModal(null);
      return;
    }

    await dispatchMutation(MUTATION_EDIT_STEP, {
      step_id: step.step_id,
      updates,
    });
  }

  // ── ADD STEP ────────────────────────────────────────────────────────────────
  const [addFields, setAddFields] = useState({
    id: "",
    purpose: "",
    expected_outcome: "",
    tool_call: "",
    risk: "LOW",
    importance: "MEDIUM",
    depends_on_raw: "",
  });

  function handleAddFieldChange(field, value) {
    setAddFields(prev => ({ ...prev, [field]: value }));
  }

  async function submitAdd() {
    const step_data = {
      id:               addFields.id.trim(),
      purpose:          addFields.purpose.trim(),
      expected_outcome: addFields.expected_outcome.trim(),
      tool_call:        addFields.tool_call.trim(),
      risk:             addFields.risk,
      importance:       addFields.importance,
      depends_on:       addFields.depends_on_raw
        .split(",")
        .map(s => s.trim())
        .filter(Boolean),
    };

    if (!step_data.id) {
      setLastError("Step ID is required.");
      return;
    }

    await dispatchMutation(MUTATION_ADD_STEP, { step_data });

    // Reset add form
    setAddFields({
      id: "", purpose: "", expected_outcome: "",
      tool_call: "", risk: "LOW", importance: "MEDIUM", depends_on_raw: "",
    });
  }

  // ── RETRY STEP ──────────────────────────────────────────────────────────────
  async function handleRetry(step) {
    if (disabled || pending) return;
    await dispatchMutation(MUTATION_RETRY_STEP, { step_id: step.step_id });
  }

  // ── Retry-eligible steps ────────────────────────────────────────────────────
  const retryableSteps = steps.filter(s => s.status === "FAILED" || s.status === "BLOCKED");

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="plan-mutation-panel">
      <div className="mutation-panel-header">
        <h3 className="mutation-panel-title">Plan Controls</h3>
        {disabled && <span className="plan-badge plan-badge--readonly">locked</span>}
        {pending && <span className="plan-badge plan-badge--pending">sending…</span>}
      </div>

      {/* Status feedback */}
      {lastError && (
        <div className="mutation-error" role="alert">
          ✗ {lastError}
        </div>
      )}
      {lastResult && !lastError && (
        <div className="mutation-success">
          ✓ Mutation accepted — awaiting projection refresh
          {lastResult.projection_version && (
            <span className="muted"> (v{lastResult.projection_version})</span>
          )}
        </div>
      )}

      {/* Step edit actions */}
      {steps.length > 0 && !disabled && (
        <section className="mutation-section">
          <h4 className="mutation-section-title">Edit Step</h4>
          <ul className="mutation-step-list">
            {steps.map(step => (
              <li key={step.step_id} className="mutation-step-item">
                <span className="mutation-step-name muted">
                  {step.purpose || step.step_id}
                </span>
                <span
                  className="plan-step-status-badge"
                  style={{ fontSize: "0.75rem", marginRight: "0.4rem" }}
                >
                  {step.status}
                </span>
                {step.status !== "COMPLETED" && (
                  <button
                    className="btn-ghost btn-sm"
                    onClick={() => openEditModal(step)}
                    disabled={pending}
                    aria-label={`Edit step ${step.purpose || step.step_id}`}
                  >
                    Edit
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Retry actions */}
      {retryableSteps.length > 0 && !disabled && (
        <section className="mutation-section">
          <h4 className="mutation-section-title">Retry / Resume</h4>
          <ul className="mutation-step-list">
            {retryableSteps.map(step => (
              <li key={step.step_id} className="mutation-step-item">
                <span className="mutation-step-name muted">
                  {step.purpose || step.step_id}
                </span>
                <span
                  className="plan-step-status-badge"
                  style={{ fontSize: "0.75rem", marginRight: "0.4rem" }}
                >
                  {step.status}
                </span>
                <button
                  className="btn-ghost btn-sm"
                  onClick={() => handleRetry(step)}
                  disabled={pending}
                  aria-label={`Retry step ${step.purpose || step.step_id}`}
                >
                  Retry
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Add step toggle */}
      {!disabled && (
        <section className="mutation-section">
          <button
            className="btn-ghost"
            onClick={() => { setAddModal(m => !m); setLastError(null); setLastResult(null); }}
            disabled={pending}
          >
            {addModal ? "▲ Cancel add" : "+ Add step"}
          </button>

          {addModal && (
            <div className="mutation-add-form fade-in">
              <label className="mutation-field-label">
                Step ID *
                <input
                  className="mutation-input"
                  value={addFields.id}
                  onChange={e => handleAddFieldChange("id", e.target.value)}
                  placeholder="unique-step-id"
                />
              </label>
              <label className="mutation-field-label">
                Purpose
                <input
                  className="mutation-input"
                  value={addFields.purpose}
                  onChange={e => handleAddFieldChange("purpose", e.target.value)}
                  placeholder="What this step does"
                />
              </label>
              <label className="mutation-field-label">
                Expected Outcome
                <input
                  className="mutation-input"
                  value={addFields.expected_outcome}
                  onChange={e => handleAddFieldChange("expected_outcome", e.target.value)}
                  placeholder="Expected result"
                />
              </label>
              <label className="mutation-field-label">
                Tool Call
                <input
                  className="mutation-input"
                  value={addFields.tool_call}
                  onChange={e => handleAddFieldChange("tool_call", e.target.value)}
                  placeholder="USE_TOOL: tool_name"
                />
              </label>
              <label className="mutation-field-label">
                Risk
                <select
                  className="mutation-select"
                  value={addFields.risk}
                  onChange={e => handleAddFieldChange("risk", e.target.value)}
                >
                  {RISK_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </label>
              <label className="mutation-field-label">
                Importance
                <select
                  className="mutation-select"
                  value={addFields.importance}
                  onChange={e => handleAddFieldChange("importance", e.target.value)}
                >
                  {IMPORTANCE_OPTIONS.map(i => <option key={i} value={i}>{i}</option>)}
                </select>
              </label>
              <label className="mutation-field-label">
                Depends On (step IDs, comma-separated)
                <input
                  className="mutation-input"
                  value={addFields.depends_on_raw}
                  onChange={e => handleAddFieldChange("depends_on_raw", e.target.value)}
                  placeholder="step-id-1, step-id-2"
                />
              </label>
              <button
                className="btn-primary btn-sm"
                onClick={submitAdd}
                disabled={pending || !addFields.id.trim()}
              >
                {pending ? "Sending…" : "Add Step"}
              </button>
            </div>
          )}
        </section>
      )}

      {/* Edit modal */}
      {editModal && (
        <div className="mutation-modal-overlay" role="dialog" aria-modal="true"
             aria-label="Edit step">
          <div className="mutation-modal fade-in">
            <h4 className="mutation-modal-title">
              Edit Step: {editModal.step.purpose || editModal.step.step_id}
            </h4>
            {EDITABLE_FIELDS.map(field => (
              <label key={field} className="mutation-field-label">
                {field.replace(/_/g, " ")}
                {field === "risk" ? (
                  <select
                    className="mutation-select"
                    value={editModal.fields[field] ?? ""}
                    onChange={e => handleEditFieldChange(field, e.target.value)}
                  >
                    {RISK_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
                  </select>
                ) : field === "importance" ? (
                  <select
                    className="mutation-select"
                    value={editModal.fields[field] ?? ""}
                    onChange={e => handleEditFieldChange(field, e.target.value)}
                  >
                    {IMPORTANCE_OPTIONS.map(i => <option key={i} value={i}>{i}</option>)}
                  </select>
                ) : (
                  <input
                    className="mutation-input"
                    value={editModal.fields[field] ?? ""}
                    onChange={e => handleEditFieldChange(field, e.target.value)}
                  />
                )}
              </label>
            ))}
            <div className="mutation-modal-actions">
              <button
                className="btn-primary btn-sm"
                onClick={submitEdit}
                disabled={pending}
              >
                {pending ? "Sending…" : "Save"}
              </button>
              <button
                className="btn-ghost btn-sm"
                onClick={() => setEditModal(null)}
                disabled={pending}
              >
                Cancel
              </button>
            </div>
            <p className="muted mutation-modal-note">
              Intent will be validated by orchestrator. UI updates after projection refresh.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
