"""
PLAN MUTATION MANAGER — PHASE 4B.1

Per PLAN_CONTROL_CONTRACT_V1:
- Orchestrator owns all plan mutation authority
- User edits are final and MUST be respected
- Mutations MUST validate before commit
- Invalid edits MUST be rejected with explanation
- System MUST NOT auto-correct dependency structure
- System MUST NOT override user intent without visibility

Per CANONICAL_PROJECTION_MODEL_V1 §7 (Projection Mutation Flow):
Mutation flow:
  1. Intent/action request          ← request_plan_mutation()
  2. API validation                 ← (API layer, schema only)
  3. Orchestrator validation        ← _validate_intent()
  4. Governance/dependency check    ← mutation_validation module
  5. Runtime update                 ← workflow_control functions
  6. Projection regeneration        ← projection_manager.emit_plan_mutated()
  7. Projection re-emission         ← ProjectionManager EventBus
  8. Frontend re-render             ← frontend consumes projection

Per LIFECYCLE_AUTHORITY_CONTRACT_V1:
- Lifecycle transitions MUST pass through request_step_transition()
- This manager MUST NOT bypass lifecycle authority
- ACTIVE step restart uses request_step_transition()

Per PROJECTION_CONTINUITY_CONTRACT_V1 §10:
- Projection invalidation occurs when plan mutates
- Invalid projections MUST refresh from authority
- Rebuild deterministically

SUB-PHASE 3E: Mutation Trace Logging
- All mutations emit a trace event with actor, type, before/after state,
  dependency changes, timestamp, workflow_id
- Trace is observational only

PROHIBITED:
- No optimistic mutation
- No frontend authority
- No bypass of request_step_transition()
- No auto-heal of dependency graph
- No silent field coercion
"""

import time
from typing import Any, Dict, List, Optional

from system.orchestrator.mutation_validation import (
    ALLOWED_MUTATION_TYPES,
    MUTATION_TYPE_EDIT_STEP,
    MUTATION_TYPE_ADD_STEP,
    MUTATION_TYPE_REMOVE_STEP,
    MUTATION_TYPE_RETRY_STEP,
    validate_dependency_graph,
    validate_remove_step,
    validate_reorder,
    validate_edit_payload,
    validate_workflow_mutable,
    validate_step_mutable,
    EDITABLE_STEP_FIELDS,
)
from system.orchestrator.workflow_control import (
    _get_workflow_state,
    request_step_transition,
    _invalidate_dependents,
    _workflow_state_registry,
    _workflow_state_lock,
    _emit_invalidation_trace,
    _sanitize_step_f1,
)
from system.orchestrator.persistence import load_active_workflows, save_workflow


# =============================================================================
# MUTATION TRACE — SUB-PHASE 3E
# =============================================================================

def _emit_mutation_trace(
    workflow_id: str,
    mutation_type: str,
    actor: str,
    previous_state: Optional[Dict[str, Any]],
    new_state: Optional[Dict[str, Any]],
    dependency_changes: Optional[Dict[str, Any]] = None,
    result: str = "success",
    rejection_reason: Optional[str] = None,
) -> None:
    """
    Emit a mutation trace event.

    Per SUB-PHASE 3E: captures actor, mutation_type, before/after state,
    dependency changes, timestamp, workflow_id.

    Trace is observational only — does NOT affect execution.
    FAILURE-ISOLATED: trace failure MUST NOT block mutation commit.
    """
    trace_event = {
        "event_type": "plan_mutation_trace",
        "workflow_id": workflow_id,
        "mutation_type": mutation_type,
        "actor": actor,
        "timestamp": time.time(),
        "result": result,
        "previous_state": previous_state,
        "new_state": new_state,
        "dependency_changes": dependency_changes or {},
        "rejection_reason": rejection_reason,
    }
    try:
        from system.interface.event_bus import publish_event
        publish_event(
            workflow_id=workflow_id,
            event_type="plan_mutation_trace",
            data=trace_event,
        )
    except Exception:
        pass

    try:
        import sys
        print(
            f"[MUTATION_TRACE] wf={workflow_id} type={mutation_type} "
            f"actor={actor} result={result}"
            + (f" reason={rejection_reason}" if rejection_reason else ""),
            file=sys.stderr,
        )
    except Exception:
        pass


# =============================================================================
# PROJECTION INVALIDATION + RE-EMISSION — SUB-PHASE 3C
# =============================================================================

def _invalidate_and_reemit(workflow: Dict[str, Any]) -> None:
    """
    Invalidate stale projection and re-emit canonical projection after mutation.

    Per CANONICAL_PROJECTION_MODEL_V1 §7 steps 6-7:
    - Invalidate stale projections
    - Emit updated canonical projections
    - Preserve projection continuity
    - Preserve monotonic versioning

    Per PROJECTION_CONTINUITY_CONTRACT_V1 §10:
    - Invalid projections MUST refresh from authority
    - Rebuild deterministically

    FAILURE-ISOLATED: projection failure MUST NOT block mutation commit.
    """
    import sys
    wf_id = workflow.get("id", "unknown")

    try:
        from system.orchestrator.projection_manager import get_projection_manager
        proj_mgr = get_projection_manager()

        # Step 1: Mark current projection as INVALIDATED
        proj_mgr.invalidate_workflow(wf_id)

        # Step 2: Read authoritative lifecycle status
        state = _get_workflow_state(wf_id)
        lifecycle_status = state.get("status", "ACTIVE") if state else "ACTIVE"

        # Step 3: Re-emit canonical projection from updated workflow state
        proj_mgr.emit_plan_mutated(workflow, lifecycle_status)

        print(f"[PROJECTION_REEMIT] {wf_id}: projection invalidated and re-emitted (status={lifecycle_status})")
    except Exception as _e:
        # === PROJECTION FAILURE VISIBILITY FIX ===
        # Per PROJECTION_CONTINUITY_CONTRACT_V1: Projection failures MUST be observable.
        # Silent swallowing creates hidden drift between runtime and UI state.
        # FAILURE-ISOLATED: Log/trace the failure but DO NOT block mutation commit.
        _err_str = str(_e)
        print(
            f"[PROJECTION_FAILURE] {wf_id}: projection re-emission failed — {_err_str}",
            file=sys.stderr
        )
        # Emit structured trace for observability
        try:
            _emit_invalidation_trace(
                workflow_id=wf_id,
                invalidation_type="projection_reemit_failure",
                reason="projection_failure_observability",
                details={"error": _err_str, "fallback_status": "ACTIVE"},
            )
        except Exception:
            pass  # Trace emission failure is secondary — already logged above


# =============================================================================
# INTERNAL HELPERS
# =============================================================================

def _load_workflow(workflow_id: str) -> Optional[Dict[str, Any]]:
    """Load workflow from persistence; returns None if not found."""
    for wf in load_active_workflows():
        if wf.get("id") == workflow_id:
            return wf
    return None


def _find_step(workflow: Dict[str, Any], step_id: str) -> Optional[Dict[str, Any]]:
    """Find step by ID in workflow; returns None if not found."""
    for s in workflow.get("steps", []):
        if s.get("id") == step_id:
            return s
    return None


def _snapshot_step(step: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return a shallow copy of step for trace logging (before-state capture)."""
    if step is None:
        return None
    return {k: v for k, v in step.items() if k not in ("execution_result", "output", "evidence_refs", "unresolved_refs", "dependency_refs_used", "validator_results")}


# =============================================================================
# MUTATION INTENT LAYER — SUB-PHASE 3A
# =============================================================================

def request_plan_mutation(
    workflow_id: str,
    mutation_type: str,
    payload: Dict[str, Any],
    actor: str = "user",
) -> Dict[str, Any]:
    """
    Orchestrator-owned mutation intent handler.

    Per CANONICAL_PROJECTION_MODEL_V1 §7: mutation requests MUST:
    - validate before commit
    - preserve workflow integrity
    - preserve lifecycle authority
    - preserve dependency integrity

    Per PLAN_CONTROL_CONTRACT_V1 §EDIT AUTHORITY RULE:
    - User edits are final and MUST be respected
    - System MUST NOT override user intent

    Frontend MUST NOT call workflow_control functions directly.
    Frontend MUST send intent to this function via API.

    Args:
        workflow_id:    Target workflow ID
        mutation_type:  One of ALLOWED_MUTATION_TYPES
        payload:        Mutation-specific payload dict
        actor:          Who initiated (default "user")

    Returns:
        {
          "status": "success" | "failure",
          "mutation_type": str,
          "workflow_id": str,
          "projection_version": int,   # only on success
          "result": dict,              # only on success
          "reason": str,               # only on failure
          "affected_steps": list,      # optional
        }
    """
    # ── 1. Basic input validation ─────────────────────────────────────────────
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id", "mutation_type": mutation_type}

    if mutation_type not in ALLOWED_MUTATION_TYPES:
        return {
            "status": "failure",
            "reason": f"unknown_mutation_type:{mutation_type}",
            "mutation_type": mutation_type,
            "workflow_id": workflow_id,
        }

    # ── 2. Load workflow ──────────────────────────────────────────────────────
    workflow = _load_workflow(workflow_id)
    if workflow is None:
        return {
            "status": "failure",
            "reason": "workflow_not_found",
            "mutation_type": mutation_type,
            "workflow_id": workflow_id,
        }

    # ── 3. Workflow-level lifecycle guard — SUB-PHASE 3D ─────────────────────
    # Per PLAN_CONTROL_CONTRACT_V1 §PLAN LOCKING + SUB-PHASE 3D lifecycle safety:
    # Reject mutation on terminal workflows; preserve FSM authority.
    wf_state = _get_workflow_state(workflow_id)
    workflow_status = wf_state.get("status", "ACTIVE") if wf_state else workflow.get("status", "ACTIVE")

    # retry_step is special: validated inside _handle_retry; skip workflow terminal check
    if mutation_type != MUTATION_TYPE_RETRY_STEP:
        wf_guard = validate_workflow_mutable(workflow_status, mutation_type)
        if not wf_guard["valid"]:
            _emit_mutation_trace(
                workflow_id, mutation_type, actor,
                previous_state={"workflow_status": workflow_status},
                new_state=None,
                result="rejected",
                rejection_reason=wf_guard["reason"],
            )
            return {
                "status": "failure",
                "reason": wf_guard["reason"],
                "mutation_type": mutation_type,
                "workflow_id": workflow_id,
            }

    # ── 4. Dispatch to mutation handler ──────────────────────────────────────
    if mutation_type == MUTATION_TYPE_EDIT_STEP:
        return _handle_edit_step(workflow, payload, actor)

    if mutation_type == MUTATION_TYPE_ADD_STEP:
        return _handle_add_step(workflow, payload, actor)

    if mutation_type == MUTATION_TYPE_REMOVE_STEP:
        return _handle_remove_step(workflow, payload, actor)

    if mutation_type == MUTATION_TYPE_RETRY_STEP:
        return _handle_retry_step(workflow, payload, actor)

    return {
        "status": "failure",
        "reason": f"unhandled_mutation_type:{mutation_type}",
        "mutation_type": mutation_type,
        "workflow_id": workflow.get("id"),
    }


# =============================================================================
# MUTATION HANDLERS
# =============================================================================

def _handle_edit_step(
    workflow: Dict[str, Any],
    payload: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Handle edit_step mutation.

    Per PLAN_CONTROL_CONTRACT_V1 §MID-EXECUTION EDIT RULES:
    - COMPLETED steps: locked — reject
    - ACTIVE steps: restart required — ACTIVE → PENDING via request_step_transition
    - FUTURE steps: fully editable

    Per PLAN_CONTROL_CONTRACT_V1 §PLAN EDIT DEPENDENCY VALIDATION:
    - After edit, validate full dependency graph
    """
    workflow_id = workflow.get("id")
    step_id = payload.get("step_id")
    updates = payload.get("updates", {})

    if not step_id:
        return {"status": "failure", "reason": "missing_step_id",
                "mutation_type": MUTATION_TYPE_EDIT_STEP, "workflow_id": workflow_id}

    step = _find_step(workflow, step_id)
    if step is None:
        return {"status": "failure", "reason": "step_not_found",
                "mutation_type": MUTATION_TYPE_EDIT_STEP, "workflow_id": workflow_id}

    # Before-state snapshot for trace
    before = _snapshot_step(step)

    # Step-level lifecycle guard
    step_guard = validate_step_mutable(step, MUTATION_TYPE_EDIT_STEP)
    if not step_guard["valid"]:
        _emit_mutation_trace(workflow_id, MUTATION_TYPE_EDIT_STEP, actor,
                             previous_state=before, new_state=None,
                             result="rejected", rejection_reason=step_guard["reason"])
        return {"status": "failure", "reason": step_guard["reason"],
                "mutation_type": MUTATION_TYPE_EDIT_STEP, "workflow_id": workflow_id}

    # Edit payload field validation
    payload_guard = validate_edit_payload(updates)
    if not payload_guard["valid"]:
        _emit_mutation_trace(workflow_id, MUTATION_TYPE_EDIT_STEP, actor,
                             previous_state=before, new_state=None,
                             result="rejected", rejection_reason=payload_guard["reason"])
        return {"status": "failure", "reason": payload_guard["reason"],
                "mutation_type": MUTATION_TYPE_EDIT_STEP, "workflow_id": workflow_id,
                "detail": payload_guard}

    # Apply field updates (only allowed fields)
    dep_before = list(step.get("depends_on", []))
    for field, value in updates.items():
        if field in EDITABLE_STEP_FIELDS:
            step[field] = value

    # === CANONICAL EXECUTION INTENT SYNCHRONIZATION ===
    # step["purpose"] is the user-editable intent (projection/UI).
    # step["input"] is the runtime execution base (escalation/retry).
    # These MUST be identical after mutation or retry/escalation logic
    # will snapshot and inject stale input from the pre-edit era.
    if "purpose" in updates:
        step["input"] = updates["purpose"]
        # === SEMANTIC EXPECTATION REGENERATION ===
        # Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1 §11:
        # Semantic expectations MUST be regenerated when planner signals change.
        # Deterministic, advisory-only, no LLM.
        from system.orchestrator.semantic_expectation import derive_semantic_expectation
        step["semantic_expectation"] = derive_semantic_expectation(
            agent=step.get("agent"),
            purpose=updates["purpose"],
        )

    # === DERIVED EXECUTION ARTIFACT INVALIDATION ===
    # tool_call is COMPILED EXECUTION STATE derived from purpose/input.
    # When semantic execution intent changes, tool_call MUST be invalidated
    # to force regeneration from updated canonical state.
    # Without this, stale compiled artifacts survive mutation → execution divergence.
    semantic_fields_changed = any(field in updates for field in ["purpose", "input", "tool_call"])
    if semantic_fields_changed:
        old_tool_call = step.pop("tool_call", None)
        if old_tool_call:
            print(f"[MUTATION_INVALIDATION] tool_call cleared for step {step_id}: was '{old_tool_call}'")

    # === EXECUTION ARTIFACT INVALIDATION — CONTRACT-CORRECTED ===
    # Per EXECUTION_IDENTITY_AND_REPLAY_CONTRACT_V1 §LINEAGE ISOLATION:
    # ANY modification to non-PENDING steps creates NEW execution lineage.
    # Therefore ALL execution-derived artifacts become INVALID — regardless of which
    # specific fields were changed.
    #
    # Previous semantic_fields_changed check was INSUFFICIENT:
    # - Editing only "description" still creates new execution lineage
    # - User intent has changed (they edited the step)
    # - Replay MUST generate fresh execution, not use stale artifacts
    #
    # This applies to ALL non-PENDING terminal/executable states:
    # - ACTIVE: already handled by restart_required, included for completeness
    # - BLOCKED: prior failed execution_result is now obsolete (edit = new intent = new execution)
    # - FAILED: prior terminal failure output is now obsolete (retry will re-execute with new context)
    #
    # Without this, stale execution artifacts survive into replay lineage,
    # causing projection divergence and workflow_output aggregation from wrong generation.
    _step_status = step.get("status", "PENDING")
    if _step_status in ("ACTIVE", "BLOCKED", "FAILED"):
        # Clear all execution-derived artifacts — ANY edit creates new lineage
        _had_execution_result = step.get("execution_result") is not None
        _had_output = step.get("output") is not None
        _had_blocked_reason = step.get("blocked_reason") is not None

        step.pop("execution_result", None)
        step.pop("output", None)
        step.pop("blocked_reason", None)

        # Emit structured invalidation trace per S9D conventions
        _emit_invalidation_trace(
            workflow_id=workflow_id,
            invalidation_type="execution_artifacts",
            step_id=step_id,
            details={
                "previous_status": _step_status,
                "execution_result_cleared": _had_execution_result,
                "output_cleared": _had_output,
                "blocked_reason_cleared": _had_blocked_reason,
                "trigger": "step_edit_any_field",
                "semantic_change": semantic_fields_changed  # Informational only
            },
            actor=actor
        )
        print(f"[MUTATION_INVALIDATION] execution artifacts cleared for {_step_status} step {step_id} "
              f"(execution_result={_had_execution_result}, output={_had_output}, blocked_reason={_had_blocked_reason})")

    dep_after = list(step.get("depends_on", []))

    # Validate full dependency graph after edit
    dep_validation = validate_dependency_graph(workflow.get("steps", []))
    if not dep_validation["valid"]:
        # Rollback field updates
        for field in updates:
            if field in EDITABLE_STEP_FIELDS:
                step[field] = before.get(field, step.get(field))
        _emit_mutation_trace(workflow_id, MUTATION_TYPE_EDIT_STEP, actor,
                             previous_state=before, new_state=None,
                             result="rejected", rejection_reason=dep_validation["reason"])
        return {"status": "failure", "reason": dep_validation["reason"],
                "mutation_type": MUTATION_TYPE_EDIT_STEP, "workflow_id": workflow_id,
                "affected_steps": dep_validation.get("affected_steps", [])}

    # ACTIVE step restart — Per PLAN_CONTROL_CONTRACT_V1 §MID-EXECUTION EDIT RULES
    # Previous execution result is discarded; step restarts
    restart_required = step_guard.get("restart_required", False)
    if restart_required:
        # Use lifecycle authority — ACTIVE → PENDING with restart reason
        ok = request_step_transition(step, "PENDING", reason="edit_restart")
        if not ok:
            # Rollback
            for field in updates:
                if field in EDITABLE_STEP_FIELDS:
                    step[field] = before.get(field, step.get(field))
            return {"status": "failure", "reason": "restart_transition_rejected",
                    "mutation_type": MUTATION_TYPE_EDIT_STEP, "workflow_id": workflow_id}

        # === PHASE-IVB: EXECUTION GENERATION COORDINATION ===
        # Increment execution_generation to invalidate stale execution owners.
        # This is NON-authoritative coordination metadata only. It does NOT gate lifecycle
        # transitions. Per PHASE-IVA EXECUTION LEASE COORDINATION DESIGN AUDIT.
        # Mirrors retry_step generation increment for consistent stale-owner suppression.
        with _workflow_state_lock:
            _current_gen = _workflow_state_registry.get(workflow_id, {}).get("execution_generation", 1)
            _workflow_state_registry[workflow_id]["execution_generation"] = _current_gen + 1
            _new_gen = _current_gen + 1
            print(f"[EXECUTION_GENERATION] Mutation restart wf={workflow_id} gen={_new_gen}")

        # === PHASE S9D: STRUCTURED INVALIDATION TRACE — MUTATION RESTART ===
        # Emit observability trace for mutation-triggered invalidation.
        _emit_invalidation_trace(
            workflow_id=workflow_id,
            invalidation_type="mutation_restart",
            step_id=step_id,
            details={
                "previous_generation": _current_gen,
                "new_generation": _new_gen,
                "trigger": "mutation_edit_restart",
                "restart_reason": "edit_restart"
            },
            actor=actor
        )

        step["retries"] = 0
        step.pop("execution_result", None)
        step.pop("output", None)
        step.pop("_original_input", None)
        step.pop("_extracted_constraints", None)
        step.pop("_validator_signals", None)
        step.pop("_validator_advisory", None)
        step.pop("_validator_decision", None)
        step.pop("_drift_signal", None)
        step.pop("_signal_analysis", None)

    step.pop("_original_input", None)
    step.pop("_extracted_constraints", None)
    step.pop("_validator_signals", None)
    step.pop("_validator_advisory", None)
    step.pop("_validator_decision", None)
    step.pop("_drift_signal", None)
    step.pop("_signal_analysis", None)

    # Invalidate dependent steps per DEPENDENCY_MODEL_CONTRACT_V1 §10
    invalidated = _invalidate_dependents(workflow, step_id)

    # Persist
    save_workflow(workflow)

    after = _snapshot_step(step)
    dep_changes = {"before": dep_before, "after": dep_after} if dep_before != dep_after else {}
    _emit_mutation_trace(workflow_id, MUTATION_TYPE_EDIT_STEP, actor,
                         previous_state=before, new_state=after,
                         dependency_changes=dep_changes, result="success")

    # Projection invalidation + re-emission — SUB-PHASE 3C
    _invalidate_and_reemit(workflow)

    from system.orchestrator.projection_manager import get_projection_manager
    proj_version = get_projection_manager().get_projection_version(workflow_id)

    return {
        "status": "success",
        "mutation_type": MUTATION_TYPE_EDIT_STEP,
        "workflow_id": workflow_id,
        "step": after,
        "restart_required": restart_required,
        "invalidated_steps": invalidated,
        "projection_version": proj_version,
    }


def _handle_add_step(
    workflow: Dict[str, Any],
    payload: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Handle add_step mutation.

    Per PLAN_CONTROL_CONTRACT_V1 §PLAN EDITING:
    - User MAY add steps
    - New step MUST validate structure and dependency graph

    Per LIFECYCLE_AUTHORITY_CONTRACT_V1:
    - New step starts at PENDING (no lifecycle transition needed)
    """
    workflow_id = workflow.get("id")
    step_data = payload.get("step_data", {})

    if not step_data.get("id"):
        return {"status": "failure", "reason": "missing_step_id",
                "mutation_type": MUTATION_TYPE_ADD_STEP, "workflow_id": workflow_id}

    # Check for duplicate step ID
    if _find_step(workflow, step_data["id"]) is not None:
        return {"status": "failure", "reason": "duplicate_step_id",
                "mutation_type": MUTATION_TYPE_ADD_STEP, "workflow_id": workflow_id}

    # Build new step with required defaults
    new_step = dict(step_data)
    new_step["type"] = new_step.get("type", "EXECUTE_API")
    new_step["purpose"] = new_step.get("purpose", "New step")
    new_step["tool_call"] = new_step.get("tool_call", "")
    new_step["expected_outcome"] = new_step.get("expected_outcome", "Execution completed")
    new_step["risk"] = new_step.get("risk", "LOW")
    new_step["importance"] = new_step.get("importance", "MEDIUM")
    new_step["resource_targets"] = new_step.get("resource_targets", [])
    new_step["depends_on"] = new_step.get("depends_on", [])
    from system.orchestrator.workflow_control import request_step_transition as _rst_pm
    _rst_pm(new_step, "PENDING", "new_step_initialization", validate=False)
    new_step["retries"] = 0
    new_step["max_retries"] = new_step.get("max_retries", 3)
    # === SEMANTIC EXPECTATION DERIVATION ===
    # Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1 §5:
    # Planner-derived semantic expectations are deterministic advisory metadata.
    from system.orchestrator.semantic_expectation import derive_semantic_expectation
    new_step["semantic_expectation"] = derive_semantic_expectation(
        agent=new_step.get("agent"),
        purpose=new_step.get("purpose"),
    )

    # Temporarily add to workflow for graph validation
    workflow.setdefault("steps", []).append(new_step)

    dep_validation = validate_dependency_graph(workflow["steps"])
    if not dep_validation["valid"]:
        workflow["steps"].pop()   # rollback
        _emit_mutation_trace(workflow_id, MUTATION_TYPE_ADD_STEP, actor,
                             previous_state=None, new_state=None,
                             result="rejected", rejection_reason=dep_validation["reason"])
        return {"status": "failure", "reason": dep_validation["reason"],
                "mutation_type": MUTATION_TYPE_ADD_STEP, "workflow_id": workflow_id,
                "affected_steps": dep_validation.get("affected_steps", [])}

    save_workflow(workflow)

    after = _snapshot_step(new_step)
    _emit_mutation_trace(workflow_id, MUTATION_TYPE_ADD_STEP, actor,
                         previous_state=None, new_state=after, result="success")

    _invalidate_and_reemit(workflow)

    from system.orchestrator.projection_manager import get_projection_manager
    proj_version = get_projection_manager().get_projection_version(workflow_id)

    return {
        "status": "success",
        "mutation_type": MUTATION_TYPE_ADD_STEP,
        "workflow_id": workflow_id,
        "step": after,
        "projection_version": proj_version,
    }


def _handle_remove_step(
    workflow: Dict[str, Any],
    payload: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Handle remove_step mutation.

    Per PLAN_CONTROL_CONTRACT_V1 §INVALID EDITS:
    - Cannot remove COMPLETED steps (locked)
    - Cannot remove a step that other steps depend on (orphan prevention)
    """
    workflow_id = workflow.get("id")
    step_id = payload.get("step_id")

    if not step_id:
        return {"status": "failure", "reason": "missing_step_id",
                "mutation_type": MUTATION_TYPE_REMOVE_STEP, "workflow_id": workflow_id}

    steps = workflow.get("steps", [])
    step_index = None
    step = None
    for i, s in enumerate(steps):
        if s.get("id") == step_id:
            step_index = i
            step = s
            break

    if step is None:
        return {"status": "failure", "reason": "step_not_found",
                "mutation_type": MUTATION_TYPE_REMOVE_STEP, "workflow_id": workflow_id}

    before = _snapshot_step(step)

    # Step lifecycle guard
    step_guard = validate_step_mutable(step, MUTATION_TYPE_REMOVE_STEP)
    if not step_guard["valid"]:
        _emit_mutation_trace(workflow_id, MUTATION_TYPE_REMOVE_STEP, actor,
                             previous_state=before, new_state=None,
                             result="rejected", rejection_reason=step_guard["reason"])
        return {"status": "failure", "reason": step_guard["reason"],
                "mutation_type": MUTATION_TYPE_REMOVE_STEP, "workflow_id": workflow_id}

    # Dependent check — cannot remove if other steps depend on this one
    dep_guard = validate_remove_step(steps, step_id)
    if not dep_guard["valid"]:
        _emit_mutation_trace(workflow_id, MUTATION_TYPE_REMOVE_STEP, actor,
                             previous_state=before, new_state=None,
                             result="rejected", rejection_reason=dep_guard["reason"])
        return {"status": "failure", "reason": dep_guard["reason"],
                "mutation_type": MUTATION_TYPE_REMOVE_STEP, "workflow_id": workflow_id,
                "dependent_step_id": dep_guard.get("dependent_step_id"),
                "affected_steps": dep_guard.get("affected_steps", [])}

    # Remove step
    steps.pop(step_index)

    # Validate remaining graph
    dep_validation = validate_dependency_graph(steps)
    if not dep_validation["valid"]:
        steps.insert(step_index, step)  # rollback
        _emit_mutation_trace(workflow_id, MUTATION_TYPE_REMOVE_STEP, actor,
                             previous_state=before, new_state=None,
                             result="rejected", rejection_reason=dep_validation["reason"])
        return {"status": "failure", "reason": dep_validation["reason"],
                "mutation_type": MUTATION_TYPE_REMOVE_STEP, "workflow_id": workflow_id}

    save_workflow(workflow)

    _emit_mutation_trace(workflow_id, MUTATION_TYPE_REMOVE_STEP, actor,
                         previous_state=before, new_state=None, result="success")

    _invalidate_and_reemit(workflow)

    from system.orchestrator.projection_manager import get_projection_manager
    proj_version = get_projection_manager().get_projection_version(workflow_id)

    return {
        "status": "success",
        "mutation_type": MUTATION_TYPE_REMOVE_STEP,
        "workflow_id": workflow_id,
        "removed_step_id": step_id,
        "projection_version": proj_version,
    }


def _handle_retry_step(
    workflow: Dict[str, Any],
    payload: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    """
    Handle retry_step mutation.

    Per HAND_ARCHITECTURE_V2: User has absolute authority to retry FAILED steps.
    Per STATE_TRANSITIONS_CONTRACT_V1: FAILED/BLOCKED → RETRY (user authority action).

    Delegates to workflow_control.retry_step for lifecycle-safe execution.
    This wrapper adds mutation tracing and projection re-emission.
    """
    from system.orchestrator.workflow_control import retry_step

    workflow_id = workflow.get("id")
    step_id = payload.get("step_id")

    if not step_id:
        return {"status": "failure", "reason": "missing_step_id",
                "mutation_type": MUTATION_TYPE_RETRY_STEP, "workflow_id": workflow_id}

    step = _find_step(workflow, step_id)
    before = _snapshot_step(step)

    # Delegate to authoritative retry_step in workflow_control
    result = retry_step(workflow_id, step_id)

    if result.get("status") == "failure":
        _emit_mutation_trace(workflow_id, MUTATION_TYPE_RETRY_STEP, actor,
                             previous_state=before, new_state=None,
                             result="rejected", rejection_reason=result.get("reason"))
        return {
            "status": "failure",
            "reason": result.get("reason"),
            "mutation_type": MUTATION_TYPE_RETRY_STEP,
            "workflow_id": workflow_id,
        }

    # Reload workflow after retry_step saved it
    workflow_reloaded = _load_workflow(workflow_id)
    after_step = _find_step(workflow_reloaded, step_id) if workflow_reloaded else None
    after = _snapshot_step(after_step)

    _emit_mutation_trace(workflow_id, MUTATION_TYPE_RETRY_STEP, actor,
                         previous_state=before, new_state=after, result="success")

    if workflow_reloaded:
        _invalidate_and_reemit(workflow_reloaded)

    from system.orchestrator.projection_manager import get_projection_manager
    proj_version = get_projection_manager().get_projection_version(workflow_id)

    return {
        "status": "success",
        "mutation_type": MUTATION_TYPE_RETRY_STEP,
        "workflow_id": workflow_id,
        "step": after,
        "projection_version": proj_version,
    }
