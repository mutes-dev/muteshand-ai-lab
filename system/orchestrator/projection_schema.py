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
