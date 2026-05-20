/**
 * EDIT MODE — PHASE 5 EDITMODE CONSOLIDATION
 *
 * Per WORKFLOW_STUDIO_PHASE5_EDITMODE_CONSOLIDATION:
 * Canonical inline editing surface using StepCard editable mode.
 *
 * Replaces Phase 3 PlanMutationPanel wrapper with direct StepCardList rendering.
 *
 * Authority notes per MUTATION_LEGALITY_CONTRACT:
 * - Edit intents are requests, not commands
 * - Backend validates mutation legality
 * - Frontend waits for projection refresh
 * - No optimistic local state mutation
 * - Draft state is UI-only, discarded on cancel
 */

import { useState, useCallback } from "react";
import { StepCardList } from "../../shared/StepCard.jsx";
import { useStepIndexMap } from "../../../hooks/useStepIndexMap.js";

/**
 * EditMode — PHASE 5 CONSOLIDATED — canonical inline editing surface
 *
 * Uses StepCardList in editable mode with:
 * - Inline edit fields (purpose, expected outcome)
 * - Draft state management (UI-only)
 * - Save/Cancel affordances
 * - Retry mutation controls
 * - Dependency visualization
 *
 * Mutation Flow (preserved):
 * 1. User clicks edit → step enters edit mode
 * 2. User modifies fields → draft state updates (UI only)
 * 3. User clicks save → onMutationIntent dispatched
 * 4. Backend validates → processes mutation
 * 5. fetchProjection() called → canonical projection refresh
 * 6. UI updates from new projection (NO optimistic update)
 *
 * @param {Object} props
 * @param {Object} props.projection — full workflow projection
 * @param {Array} props.steps — step projections
 * @param {string} props.workflowId — workflow identifier
 * @param {boolean} props.disabled — disable editing (during execution)
 * @param {Function} props.onMutationIntent — mutation intent dispatcher
 */
export default function EditMode({
  projection,
  steps,
  workflowId,
  disabled,
  onMutationIntent,
}) {
  const { projection_state } = projection || {};
  const isTerminal = projection_state === "TERMINAL";

  // UI-only draft state (isolated to EditMode, non-authoritative)
  const [editingStepId, setEditingStepId] = useState(null);
  const [draftValues, setDraftValues] = useState({});
  const [isSaving, setIsSaving] = useState(false);
  const [editErrors, setEditErrors] = useState({});

  const stepIndexMap = useStepIndexMap(steps);

  // === EDIT ACTIONS ===

  const handleEdit = useCallback((step) => {
    setEditingStepId(step.step_id);
    // Initialize draft with current canonical values
    setDraftValues({
      purpose: step.purpose || "",
      expected_outcome: step.expected_outcome || "",
      depends_on: step.depends_on || [],
    });
    setEditErrors({});
  }, []);

  const handleDraftChange = useCallback((changes) => {
    setDraftValues((prev) => ({ ...prev, ...changes }));
  }, []);

  const handleCancel = useCallback((stepId) => {
    setEditingStepId(null);
    setDraftValues({});
    setEditErrors((prev) => {
      const { [stepId]: _, ...rest } = prev;
      return rest;
    });
  }, []);

  const handleSave = useCallback(async (stepId, values) => {
    setIsSaving(true);
    setEditErrors({});

    try {
      // Dispatch mutation intent (non-authoritative request)
      await onMutationIntent?.({
        type: "edit_step",
        workflowId,
        stepId,
        payload: values,
      });

      // Clear edit state on successful mutation
      setEditingStepId(null);
      setDraftValues({});
    } catch (error) {
      // Display validation/error from backend
      setEditErrors({ [stepId]: error.message || "Save failed" });
    } finally {
      setIsSaving(false);
    }
  }, [onMutationIntent, workflowId]);

  const handleRetry = useCallback(async (step) => {
    setIsSaving(true);
    try {
      await onMutationIntent?.({
        type: "retry_step",
        workflowId,
        stepId: step.step_id,
      });
    } catch (error) {
      setEditErrors({ [step.step_id]: error.message || "Retry failed" });
    } finally {
      setIsSaving(false);
    }
  }, [onMutationIntent, workflowId]);

  // === RENDER ===

  if (isTerminal) {
    return (
      <div className="mode-content mode-content--edit mode-content--disabled">
        <div className="edit-disabled-notice">
          <span className="notice-icon">🔒</span>
          <span className="notice-text">
            Editing is disabled for completed workflows.
          </span>
        </div>
      </div>
    );
  }

  if (!steps || steps.length === 0) {
    return (
      <div className="mode-content mode-content--empty">
        <div className="mode-placeholder muted">No steps available for editing.</div>
      </div>
    );
  }

  return (
    <div className="mode-content mode-content--edit">
      {/* Edit Instructions */}
      <div className="edit-instructions muted">
        Click ✎ to edit a step. Changes are saved as mutation requests.
      </div>

      {/* Editable Step List */}
      <StepCardList
        steps={steps}
        mode="editable"
        stepIndexMap={stepIndexMap}
        onEdit={disabled ? null : handleEdit}
        onRetry={disabled ? null : handleRetry}
        showEditButtons={!disabled}
        showRetryButtons={!disabled}
        isEditable={true}
        // Phase 5 editable props
        editingStepId={editingStepId}
        draftValues={draftValues}
        onDraftChange={handleDraftChange}
        onSave={handleSave}
        onCancel={handleCancel}
        isSaving={isSaving}
        editErrors={editErrors}
      />

      {/* Disabled State Notice */}
      {disabled && (
        <div className="edit-disabled-overlay muted">
          Editing is disabled during workflow execution.
        </div>
      )}
    </div>
  );
}
