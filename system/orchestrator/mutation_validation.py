"""
MUTATION VALIDATION — PHASE 4B.1 SUB-PHASE 3B

Per PLAN_CONTROL_CONTRACT_V1:
- Plan edits MUST preserve dependency correctness
- Removing a step referenced by depends_on MUST be rejected
- Circular dependencies MUST be rejected
- Orphaned dependency references MUST be rejected
- Dependency graph MUST remain a valid DAG after every mutation
- System MUST NOT auto-heal silently

Per CANONICAL_PROJECTION_MODEL_V1 §7 (Projection Mutation Flow):
- All plan edits MUST pass dependency validation before commit
- Mutation MUST reject invalid dependency graphs

Per LIFECYCLE_AUTHORITY_CONTRACT_V1:
- This module does NOT own lifecycle authority
- Validates plan structure only; lifecycle transitions remain with workflow_control

PROHIBITED:
- No lifecycle mutations
- No auto-repair of dependency graph
- No silent correction
"""

from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# ALLOWED MUTATION TYPES
# =============================================================================

MUTATION_TYPE_EDIT_STEP   = "edit_step"
MUTATION_TYPE_ADD_STEP    = "add_step"
MUTATION_TYPE_REMOVE_STEP = "remove_step"
MUTATION_TYPE_RETRY_STEP  = "retry_step"

ALLOWED_MUTATION_TYPES = frozenset({
    MUTATION_TYPE_EDIT_STEP,
    MUTATION_TYPE_ADD_STEP,
    MUTATION_TYPE_REMOVE_STEP,
    MUTATION_TYPE_RETRY_STEP,
})

# Fields the user may edit on a step (per PLAN_CONTROL_CONTRACT_V1)
EDITABLE_STEP_FIELDS = frozenset({
    "purpose",
    "tool_call",
    "expected_outcome",
    "risk",
    "importance",
    "resource_targets",
    "depends_on",
})

# Lifecycle fields that mutations MUST NOT touch
PROTECTED_LIFECYCLE_FIELDS = frozenset({
    "status",
    "retries",
    "execution_result",
    "output",
    "blocked_reason",
    "_transition_reason",
    "_approval_resumed",
})

# Terminal workflow states — mutations on COMPLETED/FAILED workflows rejected
# (ACTIVE step edit is allowed per contract with restart semantics)
TERMINAL_WORKFLOW_STATES = frozenset({"COMPLETED", "FAILED"})

# Step states that are locked from mutation
LOCKED_STEP_STATES = frozenset({"COMPLETED"})


# =============================================================================
# DEPENDENCY GRAPH VALIDATION
# =============================================================================

def validate_dependency_graph(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate that the step list forms a valid Directed Acyclic Graph (DAG).

    Per PLAN_CONTROL_CONTRACT_V1 §VALIDATION RULES:
    - All depends_on references MUST exist
    - No circular dependencies
    - Graph MUST be a valid DAG

    Args:
        steps: list of step dicts, each with 'id' and 'depends_on'

    Returns:
        {"valid": True} on success
        {"valid": False, "reason": str, "affected_steps": [...]} on failure
    """
    step_ids = {s.get("id") for s in steps if s.get("id")}

    # 1. Orphan reference check
    for step in steps:
        step_id = step.get("id")
        for dep_id in step.get("depends_on", []):
            if dep_id not in step_ids:
                return {
                    "valid": False,
                    "reason": f"orphan_dependency_reference:{dep_id}",
                    "affected_steps": [step_id],
                    "missing_ref": dep_id,
                }

    # 2. Circular dependency check (DFS)
    adj: Dict[str, List[str]] = {s.get("id"): list(s.get("depends_on", [])) for s in steps}

    visited: Dict[str, str] = {}  # step_id -> "done" | "in_progress"
    cycle_path: List[str] = []

    def _dfs(node: str, path: List[str]) -> bool:
        """Return True if a cycle is found."""
        state = visited.get(node)
        if state == "done":
            return False
        if state == "in_progress":
            cycle_path.clear()
            cycle_path.extend(path)
            return True
        visited[node] = "in_progress"
        for dep in adj.get(node, []):
            if _dfs(dep, path + [dep]):
                return True
        visited[node] = "done"
        return False

    for step_id in step_ids:
        if visited.get(step_id) != "done":
            if _dfs(step_id, [step_id]):
                return {
                    "valid": False,
                    "reason": "circular_dependency_detected",
                    "affected_steps": list(step_ids),
                    "cycle_path": cycle_path,
                }

    return {"valid": True}


def validate_remove_step(
    steps: List[Dict[str, Any]],
    step_id: str,
) -> Dict[str, Any]:
    """
    Validate that removing step_id does not break the dependency graph.

    Per PLAN_CONTROL_CONTRACT_V1 §INVALID EDITS:
    - Removing a step referenced in another step's depends_on MUST be rejected.

    Returns:
        {"valid": True} or {"valid": False, "reason": ..., "affected_steps": [...]}
    """
    for step in steps:
        if step_id in step.get("depends_on", []):
            return {
                "valid": False,
                "reason": f"step_has_dependents:{step_id}",
                "affected_steps": [step.get("id")],
                "dependent_step_id": step.get("id"),
            }
    return {"valid": True}


def validate_reorder(
    steps: List[Dict[str, Any]],
    new_order: List[str],
) -> Dict[str, Any]:
    """
    Validate that reordering steps does not violate dependency positional constraints.

    Per PLAN_CONTROL_CONTRACT_V1 §INVALID EDITS:
    - Steps MUST NOT be reordered in a way that places a step before its dependency.

    Args:
        steps: current step list
        new_order: list of step IDs in proposed new order

    Returns:
        {"valid": True} or {"valid": False, "reason": ..., "affected_steps": [...]}
    """
    step_map = {s.get("id"): s for s in steps}
    current_ids = set(step_map.keys())

    if set(new_order) != current_ids:
        return {
            "valid": False,
            "reason": "order_must_include_all_steps",
            "affected_steps": list(current_ids.symmetric_difference(set(new_order))),
        }

    # Build position map in new order
    position = {sid: i for i, sid in enumerate(new_order)}

    for step_id in new_order:
        step = step_map.get(step_id)
        if step is None:
            continue
        step_pos = position[step_id]
        for dep_id in step.get("depends_on", []):
            dep_pos = position.get(dep_id)
            if dep_pos is None:
                return {
                    "valid": False,
                    "reason": f"orphan_dependency_reference:{dep_id}",
                    "affected_steps": [step_id],
                }
            if dep_pos >= step_pos:
                return {
                    "valid": False,
                    "reason": f"dependency_order_violation:{step_id}_depends_on_{dep_id}",
                    "affected_steps": [step_id, dep_id],
                }

    return {"valid": True}


def validate_edit_payload(
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate that an edit payload only touches allowed fields.

    Per PLAN_CONTROL_CONTRACT_V1 §EDIT VALIDATION:
    - System MUST validate structure
    - System MUST NOT allow lifecycle field mutation via edit

    Returns:
        {"valid": True} or {"valid": False, "reason": ..., "rejected_fields": [...]}
    """
    rejected = [f for f in updates if f in PROTECTED_LIFECYCLE_FIELDS]
    if rejected:
        return {
            "valid": False,
            "reason": "lifecycle_field_mutation_rejected",
            "rejected_fields": rejected,
        }

    unknown = [f for f in updates if f not in EDITABLE_STEP_FIELDS]
    if unknown:
        return {
            "valid": False,
            "reason": "unknown_fields_in_edit_payload",
            "unknown_fields": unknown,
        }

    return {"valid": True}


# =============================================================================
# WORKFLOW-LEVEL MUTATION GUARD
# =============================================================================

def validate_workflow_mutable(
    workflow_status: str,
    mutation_type: str,
) -> Dict[str, Any]:
    """
    Validate that the workflow is in a mutable state for the requested mutation.

    Per PLAN_CONTROL_CONTRACT_V1 §PLAN LOCKING:
    - COMPLETED/FAILED (terminal) workflows: most mutations rejected
    - ACTIVE workflows: edit/add/remove allowed with lifecycle protections
    - PAUSED/BLOCKED workflows: mutations allowed

    Per SUB-PHASE 3D (Lifecycle-Safe Mutation Handling):
    - Reject mutation on TERMINAL workflows when invalid
    - reject_mutation_on_active_execution_state for unsafe types

    Returns:
        {"valid": True} or {"valid": False, "reason": str}
    """
    if workflow_status in TERMINAL_WORKFLOW_STATES:
        # Only retry_step is never valid on terminal workflows
        # Per contract: terminal = locked; no mutation allowed
        return {
            "valid": False,
            "reason": f"workflow_terminal_mutation_rejected:{workflow_status}",
        }

    if workflow_status not in ("ACTIVE", "PAUSED", "BLOCKED", "QUEUED"):
        return {
            "valid": False,
            "reason": f"unknown_workflow_state:{workflow_status}",
        }

    return {"valid": True}


def validate_step_mutable(
    step: Dict[str, Any],
    mutation_type: str,
) -> Dict[str, Any]:
    """
    Validate that the target step is in a mutable state.

    Per PLAN_CONTROL_CONTRACT_V1 §PLAN LOCKING:
    - COMPLETED steps = locked (reject all mutations except view)
    - ACTIVE steps = editable with restart semantics
    - FUTURE steps = fully editable

    Returns:
        {"valid": True, "restart_required": bool}
        or {"valid": False, "reason": str}
    """
    status = step.get("status", "PENDING")

    if status in LOCKED_STEP_STATES:
        if mutation_type == MUTATION_TYPE_REMOVE_STEP:
            return {
                "valid": False,
                "reason": "completed_step_locked",
            }
        if mutation_type == MUTATION_TYPE_EDIT_STEP:
            return {
                "valid": False,
                "reason": "step_completed_locked",
            }

    restart_required = (status == "ACTIVE" and mutation_type == MUTATION_TYPE_EDIT_STEP)

    if mutation_type == MUTATION_TYPE_RETRY_STEP:
        if status not in ("FAILED", "BLOCKED"):
            return {
                "valid": False,
                "reason": f"cannot_retry_{status}_step",
            }

    return {"valid": True, "restart_required": restart_required}
