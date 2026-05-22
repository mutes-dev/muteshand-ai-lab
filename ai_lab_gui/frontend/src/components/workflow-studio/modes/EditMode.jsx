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

import { useState, useCallback, useEffect, useRef } from "react";
import { StepCardList } from "../../shared/StepCard.jsx";
import { useStepIndexMap } from "../../../hooks/useStepIndexMap.js";
import { isRecoverableTerminal, isImmutableTerminal } from "../../../constants/workflow.js";

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
  const { lifecycle_status } = projection || {};
  const isImmutable = isImmutableTerminal(lifecycle_status);
  const isRecoverable = isRecoverableTerminal(lifecycle_status);

  // UI-only draft state (isolated to EditMode, non-authoritative)
  const [editingStepId, setEditingStepId] = useState(null);
  const [draftValues, setDraftValues] = useState({});
  const [isSaving, setIsSaving] = useState(false);
  const [editErrors, setEditErrors] = useState({});

  // Persistent convergence feedback state
  // null | 'pending' | 'confirmed'
  const [convergenceState, setConvergenceState] = useState(null);
  const prevProjectionVersionRef = useRef(projection?.projection_version);

  // Track projection version changes to detect convergence
  useEffect(() => {
    const currentVersion = projection?.projection_version;
    if (
      convergenceState === "pending" &&
      currentVersion !== undefined &&
      currentVersion !== prevProjectionVersionRef.current
    ) {
      setConvergenceState("confirmed");
      const timer = setTimeout(() => setConvergenceState(null), 3000);
      return () => clearTimeout(timer);
    }
    prevProjectionVersionRef.current = currentVersion;
  }, [projection?.projection_version, convergenceState]);

  const stepIndexMap = useStepIndexMap(steps);

  // === EDIT ACTIONS ===

  const handleEdit = useCallback((step) => {
    setEditingStepId(step.step_id);
    // Initialize draft with current canonical values
    setDraftValues({
      purpose: step.purpose || "",
      expected_outcome: step.expected_outcome || "",
      risk: step.risk || "MEDIUM",
      importance: step.importance || "MEDIUM",
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
      // Begin persistent convergence feedback
      setConvergenceState("pending");
    } catch (error) {
      // Display governance-aware explanation from backend
      const humanized = humanizeMutationRejection(error.message);
      setEditErrors({ [stepId]: humanized });
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
      // Begin persistent convergence feedback for retry
      setConvergenceState("pending");
    } catch (error) {
      const humanized = humanizeMutationRejection(error.message);
      setEditErrors({ [step.step_id]: humanized });
    } finally {
      setIsSaving(false);
    }
  }, [onMutationIntent, workflowId]);

  // === RENDER ===

  // Immutable terminal states (COMPLETED, CANCELLED) are non-mutable.
  // Recoverable terminal states (FAILED) allow operational mutation and retry.
  if (isImmutable) {
    const isCancelled = lifecycle_status === "CANCELLED";
    return (
      <div className="mode-content mode-content--edit mode-content--disabled">
        <div className="edit-disabled-notice">
          <span className="notice-icon">🔒</span>
          <span className="notice-text">
            {isCancelled
              ? "This workflow was intentionally cancelled."
              : `Editing is disabled — workflow is ${lifecycle_status?.toLowerCase() || "completed"}.`}
            <span className="notice-sub muted">
              {isCancelled
                ? "Cancelled workflows are immutable to preserve execution history. They cannot be retried or modified."
                : "Immutable terminal states do not support mutation or retry."}
            </span>
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
      {/* Edit Instructions — context-aware per lifecycle state */}
      <div className="edit-instructions">
        {lifecycle_status === "PAUSED" ? (
          <span className="edit-instructions--paused">
            <span className="paused-badge">Paused</span>
            <span className="muted">
              Execution is suspended — operational mutations are safe to perform.
            </span>
          </span>
        ) : isRecoverable ? (
          <span className="edit-instructions__recoverable">
            <span className="recoverable-badge">Recoverable</span>
            <span className="muted">
              This workflow failed — steps may be edited and retried.
              Retry creates a new execution attempt.
            </span>
          </span>
        ) : (
          <span className="muted">
            Click ✎ to edit a step. Changes are sent as mutation requests.
          </span>
        )}
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

      {/* Disabled State Notice — ACTIVE immutability with explicit explanation */}
      {disabled && (
        <div className="edit-disabled-overlay">
          <span className="edit-disabled-overlay__icon">🚫</span>
          <span className="edit-disabled-overlay__text">
            Workflow is ACTIVE — mutations are prohibited during execution.
          </span>
          <span className="edit-disabled-overlay__hint muted">
            Pause the workflow to enable editing.
          </span>
        </div>
      )}

      {/* Mutation Convergence Feedback — projection-authoritative */}
      {convergenceState === "pending" && (
        <div className="edit-convergence-notice muted">
          <span className="convergence-spinner">◌</span>
          Mutation accepted — awaiting projection refresh...
        </div>
      )}
      {convergenceState === "confirmed" && (
        <div className="edit-convergence-notice edit-convergence-notice--confirmed">
          <span>✓</span>
          Projection updated
        </div>
      )}
      {isSaving && !convergenceState && (
        <div className="edit-convergence-notice muted">
          <span className="convergence-spinner">◌</span>
          Sending mutation request...
        </div>
      )}
    </div>
  );
}

/**
 * Humanize raw backend mutation rejection reasons into operator-facing
 * governance explanations. Returns { message, category } where category is
 * 'governance' (protective boundary) or 'system' (unexpected failure).
 *
 * Per GUI_FUNCTIONALITY_CONTRACT_V1 §ACTIVE EXECUTION EDIT BEHAVIOR:
 * Frontend MUST render rejection state with governance clarity.
 *
 * Preserves backend authority — no frontend legality synthesis.
 */
function humanizeMutationRejection(reason) {
  if (!reason) {
    return { message: "An unexpected error occurred.", category: "system" };
  }

  // Governance: terminal workflow
  if (reason.startsWith("workflow_terminal_mutation_rejected:COMPLETED")) {
    return {
      message: "This workflow is completed and immutable to preserve execution history.",
      category: "governance",
    };
  }
  if (reason.startsWith("workflow_terminal_mutation_rejected:CANCELLED")) {
    return {
      message: "This workflow was cancelled and can no longer be modified.",
      category: "governance",
    };
  }
  if (reason.startsWith("workflow_terminal_mutation_rejected:FAILED")) {
    return {
      message: "This workflow failed. Retry is allowed, but direct mutation is restricted.",
      category: "governance",
    };
  }

  // Governance: step-level immutability
  if (reason === "completed_step_locked" || reason === "step_completed_locked") {
    return {
      message: "This step already completed successfully and is locked to preserve execution integrity.",
      category: "governance",
    };
  }

  // Governance: retry legality
  if (reason.startsWith("cannot_retry_")) {
    const status = reason.replace("cannot_retry_", "").replace("_step", "");
    return {
      message: `${status} steps cannot be retried because execution is not in a recoverable state.`,
      category: "governance",
    };
  }

  // Governance: lifecycle field protection
  if (reason === "lifecycle_field_mutation_rejected") {
    return {
      message: "Lifecycle state is orchestrator-controlled and cannot be edited manually.",
      category: "governance",
    };
  }

  // Governance: dependency integrity
  if (reason.startsWith("orphan_dependency_reference:")) {
    return {
      message: "This edit would break the dependency chain. Remove the orphaned reference first.",
      category: "governance",
    };
  }
  if (reason === "circular_dependency_detected") {
    return {
      message: "This edit would create a circular dependency. Adjust step ordering.",
      category: "governance",
    };
  }
  if (reason.startsWith("step_has_dependents:")) {
    return {
      message: "This step is required by other steps. Remove dependent references first.",
      category: "governance",
    };
  }
  if (reason.startsWith("dependency_order_violation:")) {
    return {
      message: "This reordering would place a step before its dependency.",
      category: "governance",
    };
  }
  if (reason === "order_must_include_all_steps") {
    return {
      message: "Reordering must include every step without duplication.",
      category: "governance",
    };
  }

  // System-level errors
  if (reason === "missing_workflow_id" || reason === "workflow_not_found") {
    return { message: "Workflow not found. It may have been deleted.", category: "system" };
  }
  if (reason.startsWith("unknown_mutation_type:")) {
    return { message: "Unsupported mutation type.", category: "system" };
  }
  if (reason === "missing_step_id") {
    return { message: "Step identifier is missing.", category: "system" };
  }
  if (reason === "duplicate_step_id") {
    return { message: "A step with this ID already exists.", category: "system" };
  }
  if (reason === "step_not_found") {
    return { message: "Step not found. The workflow may have changed.", category: "system" };
  }
  if (reason === "mutation_manager_unavailable") {
    return { message: "Mutation service is temporarily unavailable.", category: "system" };
  }

  // Fallback: pass through raw for unknown reasons
  return { message: reason, category: "system" };
}
