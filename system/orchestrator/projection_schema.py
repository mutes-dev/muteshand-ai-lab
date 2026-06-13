"""
CANONICAL PROJECTION SCHEMA — PHASE 4A.0

Per CANONICAL_PROJECTION_MODEL_V1:
- Canonical projections are orchestrator-owned synchronized read models
- Every projection MUST include: workflow_id, projection_version,
  projection_timestamp, projection_type
- Projection identity MUST remain stable across reload/reconnect/hydration
- Projections are NOT execution truth, NOT lifecycle authority

Per LIFECYCLE_AUTHORITY_CONTRACT_V1:
- Projections consume lifecycle truth but do NOT define it
- Projection lifecycle is separate from workflow lifecycle

Per PROJECTION_CONTINUITY_CONTRACT_V1:
- Newer valid projections supersede older projections
- Projection state is NOT authoritative execution truth

PROHIBITED:
- No lifecycle authority logic here
- No frontend logic here
- No continuity reconciliation here
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


# ── Projection Types (per CANONICAL_PROJECTION_MODEL_V1 §2) ─────────────────

PROJECTION_TYPE_WORKFLOW = "workflow"
PROJECTION_TYPE_PLAN = "plan"
PROJECTION_TYPE_STEP = "step"
PROJECTION_TYPE_OUTPUT = "output"
PROJECTION_TYPE_TRACE = "trace"

VALID_PROJECTION_TYPES = frozenset({
    PROJECTION_TYPE_WORKFLOW,
    PROJECTION_TYPE_PLAN,
    PROJECTION_TYPE_STEP,
    PROJECTION_TYPE_OUTPUT,
    PROJECTION_TYPE_TRACE,
})

# ── Projection Lifecycle States (per CANONICAL_PROJECTION_MODEL_V1 §6) ───────

PROJECTION_STATE_ACTIVE = "ACTIVE"
PROJECTION_STATE_STALE = "STALE"
PROJECTION_STATE_INVALIDATED = "INVALIDATED"
PROJECTION_STATE_TERMINAL = "TERMINAL"

VALID_PROJECTION_STATES = frozenset({
    PROJECTION_STATE_ACTIVE,
    PROJECTION_STATE_STALE,
    PROJECTION_STATE_INVALIDATED,
    PROJECTION_STATE_TERMINAL,
})

# ── Terminal workflow states that anchor terminal projection ──────────────────

TERMINAL_WORKFLOW_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


def _utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# PROJECTION IDENTITY BUILDER
# =============================================================================

def build_projection_identity(
    workflow_id: str,
    projection_type: str,
    projection_version: int,
    projection_timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build the canonical projection identity block.

    Per CANONICAL_PROJECTION_MODEL_V1 §3:
    - workflow_id: required
    - projection_version: monotonically increasing integer
    - projection_timestamp: UTC ISO-8601
    - projection_type: one of VALID_PROJECTION_TYPES

    Returns:
        dict with all four required identity fields
    """
    if projection_type not in VALID_PROJECTION_TYPES:
        raise ValueError(
            f"Invalid projection_type '{projection_type}'. "
            f"Must be one of: {sorted(VALID_PROJECTION_TYPES)}"
        )
    return {
        "workflow_id": workflow_id,
        "projection_type": projection_type,
        "projection_version": projection_version,
        "projection_timestamp": projection_timestamp or _utc_now_iso(),
    }


# =============================================================================
# STEP PROJECTION
# =============================================================================

def build_step_projection(
    workflow_id: str,
    step: Dict[str, Any],
    projection_version: int,
    projection_state: str = PROJECTION_STATE_ACTIVE,
) -> Dict[str, Any]:
    """
    Build a canonical StepProjection.

    Per CANONICAL_PROJECTION_MODEL_V1 §2 (Step Projection):
    - Contains plan-visible step fields only
    - Does NOT include tool_call or execution_result (execution-internal)
    - Includes projection identity

    Per PLAN_STEP_CONTRACT_V1:
    - plan steps MUST NOT include tool_call

    Args:
        workflow_id: owning workflow identifier
        step: internal step dict
        projection_version: monotonic version counter
        projection_state: ACTIVE / STALE / INVALIDATED / TERMINAL

    Returns:
        Canonical StepProjection dict
    """
    identity = build_projection_identity(
        workflow_id=workflow_id,
        projection_type=PROJECTION_TYPE_STEP,
        projection_version=projection_version,
    )
    return {
        **identity,
        "projection_state": projection_state,
        "step_id": step.get("id"),
        "step_type": step.get("type"),
        "purpose": step.get("purpose"),
        "expected_outcome": step.get("expected_outcome"),
        "risk": step.get("risk"),
        "importance": step.get("importance"),
        "depends_on": step.get("depends_on", []),
        "resource_targets": step.get("resource_targets", []),
        "status": step.get("status", "PENDING"),
        "retries": step.get("retries", 0),
        # Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
        # _retry_generation is user-initiated retry count; exposed for operator lineage visibility.
        "retry_generation": step.get("_retry_generation", 0),
        # === SEMANTIC GATE (Phase 4G-A.9): blocked_reason is ONLY valid on BLOCKED steps ===
        # Per DEPENDENCY_MODEL_CONTRACT_V1: blocked_reason must not appear on non-BLOCKED steps.
        # This prevents impossible projection states (e.g. COMPLETED + blocked_reason).
        "blocked_reason": step.get("blocked_reason") if step.get("status") == "BLOCKED" else None,
        # Per CANONICAL_PROJECTION_MODEL_V1 §3 (SEMANTIC OBSERVABILITY RELATIONSHIP):
        # Expose semantic_expectation as read-only metadata.
        # Projection MUST NOT synthesize or mutate — passthrough from planner only.
        # Per SEMANTIC_EXPECTATION_MODEL_CONTRACT_V1: authority belongs to planner.
        "semantic_expectation": step.get("semantic_expectation"),
        # === ISSUE-073: AG1 attribution metadata — read-only observability only ===
        # Per AGENT_CONTRACT_V1 and AGENT_GOVERNANCE_CONTRACT_V1:
        # Projection MUST NOT infer lifecycle, retry, actionability, or recoverability.
        # Frontend MUST NOT synthesize authority from these fields.
        "agent_metadata": step.get("_agent_metadata") or None,
    }


# =============================================================================
# OUTPUT PROJECTION
# =============================================================================

def build_output_projection(
    workflow_id: str,
    step_id: str,
    execution_result: Any,
    projection_version: int,
    projection_state: str = PROJECTION_STATE_ACTIVE,
) -> Dict[str, Any]:
    """
    Build a canonical OutputProjection for a completed step.

    Per CANONICAL_PROJECTION_MODEL_V1 §2 (Output Projection):
    - Contains execution output separated from plan step
    - Includes projection identity

    Args:
        workflow_id: owning workflow identifier
        step_id: step that produced this output
        execution_result: raw execution output
        projection_version: monotonic version counter
        projection_state: projection lifecycle state

    Returns:
        Canonical OutputProjection dict
    """
    identity = build_projection_identity(
        workflow_id=workflow_id,
        projection_type=PROJECTION_TYPE_OUTPUT,
        projection_version=projection_version,
    )
    return {
        **identity,
        "projection_state": projection_state,
        "step_id": step_id,
        "execution_result": execution_result,
    }


# =============================================================================
# PLAN PROJECTION
# =============================================================================

def build_plan_projection(
    workflow_id: str,
    steps: List[Dict[str, Any]],
    projection_version: int,
    projection_state: str = PROJECTION_STATE_ACTIVE,
) -> Dict[str, Any]:
    """
    Build a canonical PlanProjection from workflow steps.

    Per CANONICAL_PROJECTION_MODEL_V1 §8 (Plan Projection Model):
    - Contains plan-visible step list
    - Frontend requests edits through this projection
    - Does NOT contain execution truth

    Args:
        workflow_id: owning workflow identifier
        steps: list of internal step dicts
        projection_version: monotonic version counter
        projection_state: projection lifecycle state

    Returns:
        Canonical PlanProjection dict
    """
    identity = build_projection_identity(
        workflow_id=workflow_id,
        projection_type=PROJECTION_TYPE_PLAN,
        projection_version=projection_version,
    )
    step_projections = [
        build_step_projection(
            workflow_id=workflow_id,
            step=s,
            projection_version=projection_version,
            projection_state=projection_state,
        )
        for s in steps
    ]
    return {
        **identity,
        "projection_state": projection_state,
        "steps": step_projections,
        "step_count": len(step_projections),
    }


def _is_permanent_block_reason(blocked_reason: str) -> bool:
    """
    Check if a blocked_reason indicates a permanent block that caused workflow FAILED.

    Mirrors the permanent block logic from orchestrator_runtime.py post-loop terminalization.
    """
    if not blocked_reason:
        return False
    return (
        blocked_reason.startswith("dependency_failed")
        or (
            blocked_reason.startswith("dependency_not_completed")
            and blocked_reason.split(":")[-1] in ("FAILED", "BLOCKED")
        )
        or blocked_reason in ("max_retries_exceeded", "escalated")
    )


def _is_stale_dependency_reason(step: Dict[str, Any], steps_by_id: Dict[str, Dict[str, Any]]) -> bool:
    """
    Check if a BLOCKED step's dependency reason is stale (dependency status mismatch).

    A stale reason occurs when a step is blocked with e.g.
    'dependency_not_completed:step_2:BLOCKED' but step_2 is actually COMPLETED.
    Retrying the current step forces scheduler re-evaluation, which clears the stale block.

    Returns True if the blocked reason is stale and the current step should be retried.
    """
    reason = step.get("blocked_reason", "")
    if not (reason.startswith("dependency_not_completed") or reason.startswith("dependency_failed")):
        return False
    parts = reason.split(":")
    if len(parts) < 3:
        return False
    dep_id = parts[1]
    claimed_status = parts[-1]
    dep = steps_by_id.get(dep_id)
    if dep is None:
        return True  # Dependency missing → stale
    actual_status = dep.get("status")
    return actual_status != claimed_status


def _compute_retry_target_step_id(
    steps: List[Dict[str, Any]],
    lifecycle_status: Optional[str] = None,
) -> Optional[str]:
    """
    Compute the authoritative retry target step ID from workflow steps.

    Per ISSUE-057 CONTRACT AUDIT:
    - Backend decides retry target; frontend consumes it.
    - FAILED steps are primary retry targets.
    - BLOCKED steps with permanent-block reasons may be retry targets if no FAILED step,
      but only if they are NOT downstream victim steps of another retry target.
    - Stale dependency-blocked reasons (dependency status mismatch) indicate the
      current step should be retried to force scheduler re-evaluation.

    Per BLOCKED SEMANTIC AUTHORITY FIX:
    - Retry target is ONLY computed for FAILED lifecycle status.
    - Projection MUST NOT infer retry target from BLOCKED steps for non-FAILED workflows.

    Returns:
        step_id string or None
    """
    # Guard: retry target is only valid for FAILED workflows.
    if lifecycle_status != "FAILED":
        return None

    steps_by_id = {s.get("id"): s for s in steps if s.get("id")}

    # Rule 1: First FAILED step in order
    for step in steps:
        if step.get("status") == "FAILED":
            return step.get("id")

    # Rule 2: BLOCKED with permanent-block reason (only if no FAILED steps)
    for step in steps:
        if step.get("status") == "BLOCKED":
            reason = step.get("blocked_reason", "")
            if not _is_permanent_block_reason(reason):
                continue
            # Stale dependency reason → retry current step to force re-evaluation
            if _is_stale_dependency_reason(step, steps_by_id):
                return step.get("id")
            # Direct causative reasons (max_retries_exceeded, escalated)
            if reason in ("max_retries_exceeded", "escalated"):
                return step.get("id")
            # dependency_failed or dependency_not_completed with matching dependency status
            # → current step is a downstream victim, skip
            continue

    # Rule 3: No valid retry target
    return None


def _compute_failure_metadata(
    steps: List[Dict[str, Any]],
    workflow_error: Optional[str],
    lifecycle_status: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute failure metadata for FAILED workflow projection enrichment.

    Per ISSUE-057 FIX F: execution result failure clarity.
    This is observability enrichment only — does NOT affect lifecycle authority.

    Per BLOCKED SEMANTIC AUTHORITY FIX:
    - Failure metadata is ONLY computed for FAILED lifecycle status.
    - Projection MUST NOT synthesize failure truth for non-FAILED workflows.

    Returns:
        dict with failure_reason, failed_step_id, failed_step_label,
        last_successful_output, last_successful_step_id
    """
    # Guard: failure metadata is only valid for FAILED workflows.
    if lifecycle_status != "FAILED":
        return {
            "failure_reason": None,
            "failed_step_id": None,
            "failed_step_label": None,
            "last_successful_output": None,
            "last_successful_step_id": None,
        }

    metadata: Dict[str, Any] = {
        "failure_reason": workflow_error or None,
        "failed_step_id": None,
        "failed_step_label": None,
        "last_successful_output": None,
        "last_successful_step_id": None,
    }

    # Find the causative failed step (FAILED status)
    for step in steps:
        if step.get("status") == "FAILED":
            metadata["failed_step_id"] = step.get("id")
            metadata["failed_step_label"] = step.get("purpose") or step.get("id")
            exec_res = step.get("execution_result")
            if exec_res and isinstance(exec_res, dict):
                metadata["failure_reason"] = exec_res.get("reason") or workflow_error or "step_failed"
            break

    # Fallback: if no FAILED step, identify causative BLOCKED step with permanent-block reason
    steps_by_id = {s.get("id"): s for s in steps if s.get("id")}
    if metadata["failed_step_id"] is None:
        for step in steps:
            if step.get("status") == "BLOCKED":
                reason = step.get("blocked_reason", "")
                if not _is_permanent_block_reason(reason):
                    continue
                # Stale dependency or direct causative → current step is the failure source
                if _is_stale_dependency_reason(step, steps_by_id) or reason in ("max_retries_exceeded", "escalated"):
                    metadata["failed_step_id"] = step.get("id")
                    metadata["failed_step_label"] = step.get("purpose") or step.get("id")
                    metadata["failure_reason"] = reason or workflow_error or "step_blocked"
                    break
                # Matching dependency status → downstream victim, skip and look for upstream

    # Find last successful step (for last_successful_output)
    for step in reversed(steps):
        if step.get("status") == "COMPLETED":
            exec_res = step.get("execution_result")
            if exec_res and isinstance(exec_res, dict) and exec_res.get("status") == "success":
                metadata["last_successful_output"] = exec_res.get("result")
                metadata["last_successful_step_id"] = step.get("id")
            break

    return metadata


# =============================================================================
# WORKFLOW PROJECTION
# =============================================================================

def build_workflow_projection(
    workflow: Dict[str, Any],
    projection_version: int,
    lifecycle_status: str,
    projection_state: Optional[str] = None,
    workflow_output: Optional[Any] = None,
    runtime_activity: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a canonical WorkflowProjection.

    Per CANONICAL_PROJECTION_MODEL_V1 §2 (Workflow Projection):
    - Top-level projection aggregating plan, steps, outputs
    - Consumes lifecycle_status from Lifecycle Authority — does NOT define it
    - Includes projection identity on root AND sub-projections

    Per CANONICAL_PROJECTION_MODEL_V1 §14 (Terminal Projection Rules):
    - Terminal workflow states (COMPLETED/FAILED) → projection_state = TERMINAL

    Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    - runtime_activity is owned by Runtime Registry (authoritative)
    - Projection REFLECTS runtime_activity — does NOT derive or synthesize it
    - Source: _workflow_state_registry[workflow_id]["runtime_activity"]

    Args:
        workflow: internal workflow dict
        projection_version: monotonic version counter
        lifecycle_status: authoritative lifecycle state (from _get_workflow_state)
        projection_state: override; if None, derived from lifecycle_status
        workflow_output: top-level output (from workflow["output"])
        runtime_activity: explicit override (e.g. from caller with registry read);
                          if None, read authoritatively from runtime registry.

    Returns:
        Canonical WorkflowProjection dict
    """
    workflow_id = workflow.get("id", "unknown")
    steps = workflow.get("steps", [])

    # === AUTHORITATIVE RUNTIME ACTIVITY READ ===
    # Per RUNTIME_REGISTRY_AND_EXECUTION_COORDINATION_CONTRACT_V1 §9:
    # runtime_activity MUST be read from runtime registry, NOT derived from step states.
    # Projection is a reflection layer — it observes, does NOT generate.
    if runtime_activity is None:
        try:
            from system.orchestrator.workflow_control import _get_workflow_state as _gws_proj
            _reg_state = _gws_proj(workflow_id) or {}
            runtime_activity = _reg_state.get("runtime_activity", "IDLE")
            # === [AUTH:PROJECTION_BUILD] Lifecycle authority validation ===
            _reg_status = _reg_state.get("status", "UNKNOWN")
            if lifecycle_status != _reg_status:
                print(f"[AUTH:PROJECTION_BUILD] workflow_id={workflow_id} runtime_registry_status={_reg_status} emitted_projection_status={lifecycle_status} runtime_activity={runtime_activity} projection_source=build_workflow_projection")
        except Exception:
            runtime_activity = "IDLE"

    # Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
    # execution_generation is authoritative workflow execution identity for stale-owner invalidation.
    # Exposed for operator observability — frontend NEVER interprets as lifecycle authority.
    try:
        from system.orchestrator.workflow_control import _get_workflow_state as _gws_exec_gen
        _reg_state_exec = _gws_exec_gen(workflow_id) or {}
        execution_generation = _reg_state_exec.get("execution_generation", 1)
    except Exception:
        execution_generation = 1

    # Derive projection_state from lifecycle if not overridden
    if projection_state is None:
        if lifecycle_status in TERMINAL_WORKFLOW_STATES:
            projection_state = PROJECTION_STATE_TERMINAL
        else:
            projection_state = PROJECTION_STATE_ACTIVE

    identity = build_projection_identity(
        workflow_id=workflow_id,
        projection_type=PROJECTION_TYPE_WORKFLOW,
        projection_version=projection_version,
    )

    # Build step and output sub-projections
    step_projections = []
    output_projections = []
    for step in steps:
        step_projections.append(
            build_step_projection(
                workflow_id=workflow_id,
                step=step,
                projection_version=projection_version,
                projection_state=projection_state,
            )
        )
        exec_res = step.get("execution_result")
        if exec_res is not None:
            output_projections.append(
                build_output_projection(
                    workflow_id=workflow_id,
                    step_id=step.get("id"),
                    execution_result=exec_res,
                    projection_version=projection_version,
                    projection_state=projection_state,
                )
            )

    # === ISSUE-057: AUTHORITATIVE RETRY TARGET + FAILURE METADATA ===
    # Per FIX E/C2: Backend computes retry_target_step_id from authoritative step states.
    # Per FIX F: Failure metadata is observability enrichment only.
    retry_target_step_id = _compute_retry_target_step_id(steps, lifecycle_status)
    failure_metadata = _compute_failure_metadata(steps, workflow.get("error"), lifecycle_status)

    # === ISSUE-062: FAILED ACTIONABILITY METADATA ===
    # Projection reflects backend-authored metadata only; does NOT authorize retry.
    _failed_recoverable = workflow.get("failed_recoverable")
    _retry_disabled_reason = workflow.get("retry_disabled_reason")
    _actionability_reason = workflow.get("actionability_reason")
    _terminalization_reason = workflow.get("terminalization_reason")
    if lifecycle_status == "FAILED" and _failed_recoverable is None:
        _failed_recoverable = True  # backward compatibility default
    _retry_eligible = False
    _target_step = None
    if _failed_recoverable and retry_target_step_id is not None:
        # ISSUE-098A: Normal retry boundedness — projection must reflect
        # the same retries < max_retries rule enforced by workflow_control.
        _target_step = next(
            (s for s in steps if s.get("id") == retry_target_step_id), None
        )
        if _target_step is not None:
            _retries = _target_step.get("retries", 0)
            _max_retries = _target_step.get("max_retries", 3)
            _retry_eligible = _retries < _max_retries

    # === ISSUE-098A: FORCE RETRY CANDIDATE METADATA ===
    # Projection exposes explicit force retry actionability so frontend
    # does not synthesize eligibility from raw retries/max_retries.
    _force_retry_candidate = False
    _force_retry_remaining = 0
    _force_retry_disabled_reason = None
    _FORCE_RETRY_LIMIT = 1  # Duplicated here to avoid circular import
    if _failed_recoverable and retry_target_step_id is not None and _target_step is not None:
        _retries = _target_step.get("retries", 0)
        _max_retries = _target_step.get("max_retries", 3)
        if _retries >= _max_retries:
            _force_count = _target_step.get("_force_retry_count", 0)
            _force_remaining = _FORCE_RETRY_LIMIT - _force_count
            if _force_remaining > 0:
                _force_retry_candidate = True
                _force_retry_remaining = _force_remaining
            else:
                _force_retry_disabled_reason = "force_retry_budget_exhausted"
        else:
            _force_retry_disabled_reason = "normal_retries_not_exhausted"
    elif not _failed_recoverable:
        _force_retry_disabled_reason = "not_recoverable"
    elif retry_target_step_id is None:
        _force_retry_disabled_reason = "no_retry_target"

    return {
        **identity,
        "projection_state": projection_state,
        "workflow_name": workflow.get("name"),
        "lifecycle_status": lifecycle_status,
        "runtime_activity": runtime_activity,
        "steps": step_projections,
        "outputs": output_projections,
        "workflow_output": workflow_output,
        "step_count": len(step_projections),
        "output_count": len(output_projections),
        # Per EXECUTION_LINEAGE_AND_OBSERVABILITY_AUDIT:
        # execution_generation increments on retry to invalidate stale execution ownership.
        "execution_generation": execution_generation,
        # Per ISSUE-057 FIX E: Authoritative retry target — backend-decided, frontend-consumed.
        "retry_target_step_id": retry_target_step_id,
        # Per ISSUE-057 FIX F: Failure observability metadata.
        "failure_reason": failure_metadata["failure_reason"],
        "failed_step_id": failure_metadata["failed_step_id"],
        "failed_step_label": failure_metadata["failed_step_label"],
        "last_successful_output": failure_metadata["last_successful_output"],
        "last_successful_step_id": failure_metadata["last_successful_step_id"],
        # === ISSUE-062: FAILED actionability metadata (read-only projection fields) ===
        "failed_recoverable": _failed_recoverable,
        "retry_eligible": _retry_eligible,
        "retry_disabled_reason": _retry_disabled_reason,
        "actionability_reason": _actionability_reason,
        "terminalization_reason": _terminalization_reason,
        # === ISSUE-098A: Force retry candidate metadata ===
        "force_retry_candidate": _force_retry_candidate,
        "force_retry_remaining": _force_retry_remaining,
        "force_retry_disabled_reason": _force_retry_disabled_reason,
    }


# =============================================================================
# TRACE PROJECTION
# =============================================================================

def build_trace_projection(
    workflow_id: str,
    trace_entries: List[Dict[str, Any]],
    projection_version: int,
    projection_state: str = PROJECTION_STATE_ACTIVE,
) -> Dict[str, Any]:
    """
    Build a canonical TraceProjection.

    Per CANONICAL_PROJECTION_MODEL_V1 §2 (Trace Projection):
    - Read-only observability view
    - Does NOT affect execution
    - Includes projection identity

    Args:
        workflow_id: owning workflow identifier
        trace_entries: list of trace event dicts
        projection_version: monotonic version counter
        projection_state: projection lifecycle state

    Returns:
        Canonical TraceProjection dict
    """
    identity = build_projection_identity(
        workflow_id=workflow_id,
        projection_type=PROJECTION_TYPE_TRACE,
        projection_version=projection_version,
    )
    return {
        **identity,
        "projection_state": projection_state,
        "entries": trace_entries,
        "entry_count": len(trace_entries),
    }


# =============================================================================
# PROJECTION VALIDATION UTILITY
# =============================================================================

def validate_projection_identity(projection: Dict[str, Any]) -> bool:
    """
    Validate that a projection dict contains all required identity fields.

    Per CANONICAL_PROJECTION_MODEL_V1 §3:
    All four fields (workflow_id, projection_type, projection_version,
    projection_timestamp) are REQUIRED.

    Returns:
        True if valid, False otherwise
    """
    required = {"workflow_id", "projection_type", "projection_version", "projection_timestamp"}
    if not all(k in projection for k in required):
        return False
    if projection.get("projection_type") not in VALID_PROJECTION_TYPES:
        return False
    if not isinstance(projection.get("projection_version"), int):
        return False
    return True
