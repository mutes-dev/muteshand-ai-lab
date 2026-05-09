"""
WORKFLOW CONTROL — Pause/Resume, Plan Control, and Control Actions

Per STATE_TRANSITIONS_CONTRACT_V1:
- ACTIVE → PAUSED (user action)
- PAUSED → ACTIVE (resume)

Per GUI_FUNCTIONALITY_CONTRACT_V1:
- ALL actions require workflow_id
- ALL actions require step_id when applicable

Per PLAN_CONTROL_CONTRACT_V1:
- COMPLETED steps = locked
- ACTIVE steps = editable with restart
- FUTURE steps = fully editable
- Validate dependencies after any edit
"""

from typing import Dict, Any, List, Optional
import threading
import time

from system.orchestrator.persistence import load_active_workflows, save_workflow
from system.orchestrator.workflow_validator import validate_workflow
from system.interface import event_emitter


# In-memory workflow state registry (per-workflow state transitions)
# workflow_id -> {"status": str, "last_updated": float}
_workflow_state_registry: Dict[str, Dict[str, Any]] = {}
_workflow_state_lock = threading.RLock()


# ============================================================================
# WORKFLOW STATE MANAGEMENT (Internal)
# ============================================================================

def _get_workflow_state(workflow_id: str) -> Optional[Dict[str, Any]]:
    """Get current state for workflow from registry or persistence."""
    with _workflow_state_lock:
        # Check in-memory registry first
        if workflow_id in _workflow_state_registry:
            return _workflow_state_registry[workflow_id].copy()

    # Fall back to persistence
    workflows = load_active_workflows()
    for wf in workflows:
        if wf.get("id") == workflow_id:
            return {
                "status": wf.get("status", "QUEUED"),
                "last_updated": time.time()
            }
    return None


def _update_workflow_state(workflow_id: str, new_status: str, reason: str = None) -> bool:
    """Update workflow state in registry and persistence."""
    with _workflow_state_lock:
        _workflow_state_registry[workflow_id] = {
            "status": new_status,
            "last_updated": time.time(),
            "reason": reason
        }

    # Also update in persistence
    workflows = load_active_workflows()
    for wf in workflows:
        if wf.get("id") == workflow_id:
            wf["status"] = new_status
            if reason:
                wf["status_reason"] = reason
            save_workflow(wf)
            return True
    return False


def _is_valid_state_transition(current: str, new: str) -> bool:
    """Check if state transition is valid per STATE_TRANSITIONS_CONTRACT_V1."""
    valid_transitions = {
        "QUEUED": ["ACTIVE"],
        "ACTIVE": ["PAUSED", "BLOCKED", "COMPLETED", "FAILED"],
        "PAUSED": ["ACTIVE", "FAILED"],
        "BLOCKED": ["ACTIVE", "FAILED"],
        "COMPLETED": [],  # Terminal
        "FAILED": []      # Terminal
    }
    return new in valid_transitions.get(current, [])


def _invalidate_dependents(workflow: dict, changed_step_id: str, visited: set = None) -> List[str]:
    """
    Invalidate all dependent steps after a plan edit.
    Per DEPENDENCY_MODEL_CONTRACT_V1 Section 10:
    - Dependent steps MUST be re-evaluated when dependency changes
    - NO stale execution: clear execution_result and output

    Args:
        workflow: The workflow dict
        changed_step_id: The step ID that was modified
        visited: Set of already visited step IDs (for recursion tracking)

    Returns:
        List of step IDs that were invalidated
    """
    if visited is None:
        visited = set()

    if changed_step_id in visited:
        return []
    visited.add(changed_step_id)

    invalidated = []
    steps = workflow.get("steps", [])

    # Find all steps that depend on changed_step_id
    for step in steps:
        step_id = step.get("id")
        if step_id in visited:
            continue

        depends_on = step.get("depends_on", [])
        if changed_step_id in depends_on:
            # This step depends on the changed step
            # Reset to PENDING (will be re-evaluated by scheduler)
            if step.get("status") not in ("COMPLETED", "FAILED"):
                step["status"] = "PENDING"
                step.pop("execution_result", None)
                step.pop("output", None)
                invalidated.append(step_id)

                # Recursively invalidate dependents of this step
                invalidated.extend(_invalidate_dependents(workflow, step_id, visited))

    return invalidated


# ============================================================================
# SUB-PHASE 3B — PAUSE/RESUME
# ============================================================================

def pause_workflow(workflow_id: str) -> Dict[str, Any]:
    """
    Pause a workflow using state transition.
    Per STATE_TRANSITIONS_CONTRACT_V1: ACTIVE → PAUSED

    Args:
        workflow_id: The workflow to pause

    Returns:
        {"status": "success", "previous_state": str, "new_state": "PAUSED"}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}

    current_state = _get_workflow_state(workflow_id)
    if current_state is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    current = current_state.get("status", "QUEUED")

    # Per STATE_TRANSITIONS_CONTRACT_V1: Only ACTIVE can → PAUSED
    if current != "ACTIVE":
        return {
            "status": "failure",
            "reason": f"invalid_transition:{current}_to_PAUSED"
        }

    if not _is_valid_state_transition(current, "PAUSED"):
        return {"status": "failure", "reason": f"invalid_state_transition:{current}→PAUSED"}

    # Perform transition
    if not _update_workflow_state(workflow_id, "PAUSED", "user_pause"):
        return {"status": "failure", "reason": "update_failed"}

    # Emit event per TRACE_LOGGING_CONTRACT_V1
    try:
        event_emitter.emit_state_transition(
            workflow_id=workflow_id,
            step_id=None,
            previous_state=current,
            new_state="PAUSED",
            reason="user_pause"
        )
        event_emitter.emit_event(
            event_type="PROJECT_PAUSED",
            workflow_id=workflow_id,
            data={"timestamp": time.time(), "reason": "user_pause"}
        )
    except Exception:
        pass  # Event emission failure must not affect execution

    return {
        "status": "success",
        "previous_state": current,
        "new_state": "PAUSED",
        "workflow_id": workflow_id
    }


def resume_workflow(workflow_id: str) -> Dict[str, Any]:
    """
    Resume a workflow using state transition.
    Per STATE_TRANSITIONS_CONTRACT_V1: PAUSED → ACTIVE

    Args:
        workflow_id: The workflow to resume

    Returns:
        {"status": "success", "previous_state": "PAUSED", "new_state": "ACTIVE"}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}

    current_state = _get_workflow_state(workflow_id)
    if current_state is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    current = current_state.get("status", "QUEUED")

    # Per STATE_TRANSITIONS_CONTRACT_V1: Only PAUSED can → ACTIVE
    if current != "PAUSED":
        return {
            "status": "failure",
            "reason": f"invalid_transition:{current}_to_ACTIVE"
        }

    if not _is_valid_state_transition(current, "ACTIVE"):
        return {"status": "failure", "reason": f"invalid_state_transition:{current}→ACTIVE"}

    # Perform transition
    if not _update_workflow_state(workflow_id, "ACTIVE", "user_resume"):
        return {"status": "failure", "reason": "update_failed"}

    # Emit event per TRACE_LOGGING_CONTRACT_V1
    try:
        event_emitter.emit_state_transition(
            workflow_id=workflow_id,
            step_id=None,
            previous_state=current,
            new_state="ACTIVE",
            reason="user_resume"
        )
        event_emitter.emit_event(
            event_type="PROJECT_RESUMED",
            workflow_id=workflow_id,
            data={"timestamp": time.time(), "reason": "user_resume"}
        )
    except Exception:
        pass

    return {
        "status": "success",
        "previous_state": current,
        "new_state": "ACTIVE",
        "workflow_id": workflow_id
    }


# ============================================================================
# SUB-PHASE 3C — PLAN CONTROL
# ============================================================================

def get_plan(workflow_id: str) -> Dict[str, Any]:
    """
    Get the execution plan for a workflow.

    Args:
        workflow_id: The workflow ID

    Returns:
        {"status": "success", "steps": [...], "workflow_status": str}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}

    workflows = load_active_workflows()
    for wf in workflows:
        if wf.get("id") == workflow_id:
            return {
                "status": "success",
                "workflow_id": workflow_id,
                "workflow_status": wf.get("status", "QUEUED"),
                "steps": wf.get("steps", [])
            }

    return {"status": "failure", "reason": "workflow_not_found"}


def edit_step(workflow_id: str, step_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Edit a step in the workflow plan.
    Per PLAN_CONTROL_CONTRACT_V1:
    - COMPLETED steps = locked (reject)
    - ACTIVE steps = editable with restart
    - FUTURE steps = fully editable
    - Validate dependencies after edit

    Args:
        workflow_id: The workflow ID
        step_id: The step ID to edit
        updates: Dictionary of fields to update

    Returns:
        {"status": "success", "step": updated_step}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}
    if not step_id:
        return {"status": "failure", "reason": "missing_step_id"}

    # Load workflow
    workflows = load_active_workflows()
    workflow = None
    for wf in workflows:
        if wf.get("id") == workflow_id:
            workflow = wf
            break

    if workflow is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    # Find step
    step = None
    for s in workflow.get("steps", []):
        if s.get("id") == step_id:
            step = s
            break

    if step is None:
        return {"status": "failure", "reason": "step_not_found"}

    # Check step state per PLAN_CONTROL_CONTRACT_V1
    step_status = step.get("status", "PENDING")

    if step_status == "COMPLETED":
        return {"status": "failure", "reason": "step_completed_locked"}

    # Apply updates
    allowed_fields = [
        "purpose", "tool_call", "expected_outcome", "risk",
        "importance", "resource_targets", "depends_on"
    ]

    for field, value in updates.items():
        if field in allowed_fields:
            step[field] = value

    # If ACTIVE step edited, mark for restart per PLAN_CONTROL_CONTRACT_V1
    restart_required = False
    if step_status == "ACTIVE":
        step["status"] = "PENDING"  # Reset to PENDING for restart
        step["retries"] = 0
        step.pop("execution_result", None)
        step.pop("output", None)
        restart_required = True

    # Validate dependency graph after edit
    validation = validate_workflow(workflow)
    if validation["status"] == "failure":
        # Reject edit if validation fails
        return {"status": "failure", "reason": f"validation_failed:{validation.get('reason')}"}

    # === DEPENDENCY RE-EVALUATION (Phase 4A.1) ===
    # Per DEPENDENCY_MODEL_CONTRACT_V1 Section 10:
    # Invalidate all dependent steps when a step is edited
    invalidated_steps = _invalidate_dependents(workflow, step_id)

    # Save updated workflow
    save_workflow(workflow)

    return {
        "status": "success",
        "step": step,
        "restart_required": restart_required,
        "invalidated_steps": invalidated_steps,
        "workflow_id": workflow_id
    }


def add_step(workflow_id: str, step_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add a new step to the workflow plan.
    Per PLAN_CONTROL_CONTRACT_V1: Validates and appends step.

    Args:
        workflow_id: The workflow ID
        step_data: The step definition (must include id, purpose, etc.)

    Returns:
        {"status": "success", "step": new_step}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}

    # Load workflow
    workflows = load_active_workflows()
    workflow = None
    for wf in workflows:
        if wf.get("id") == workflow_id:
            workflow = wf
            break

    if workflow is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    # Check workflow state - can only add to ACTIVE or PAUSED
    wf_status = workflow.get("status", "QUEUED")
    if wf_status not in ["ACTIVE", "PAUSED", "QUEUED", "BLOCKED"]:
        return {"status": "failure", "reason": f"cannot_add_to_{wf_status}_workflow"}

    # Ensure required fields
    if "id" not in step_data:
        return {"status": "failure", "reason": "missing_step_id"}

    # Set defaults for contract-required fields
    new_step = dict(step_data)
    new_step["type"] = new_step.get("type", "EXECUTE_API")
    new_step["purpose"] = new_step.get("purpose", "New step")
    new_step["tool_call"] = new_step.get("tool_call", "")
    new_step["expected_outcome"] = new_step.get("expected_outcome", "Execution completed")
    new_step["risk"] = new_step.get("risk", "LOW")
    new_step["importance"] = new_step.get("importance", "MEDIUM")
    new_step["resource_targets"] = new_step.get("resource_targets", [])
    new_step["status"] = "PENDING"
    new_step["retries"] = 0
    new_step["max_retries"] = new_step.get("max_retries", 3)

    # Add to workflow
    if "steps" not in workflow:
        workflow["steps"] = []
    workflow["steps"].append(new_step)

    # Validate dependency graph
    validation = validate_workflow(workflow)
    if validation["status"] == "failure":
        # Remove the step we just added
        workflow["steps"].pop()
        return {"status": "failure", "reason": f"validation_failed:{validation.get('reason')}"}

    # Save updated workflow
    save_workflow(workflow)

    return {
        "status": "success",
        "step": new_step,
        "workflow_id": workflow_id
    }


def remove_step(workflow_id: str, step_id: str) -> Dict[str, Any]:
    """
    Remove a step from the workflow plan.
    Per PLAN_CONTROL_CONTRACT_V1:
    - Reject if step is COMPLETED
    - Reject if step has dependents (other steps depend on it)

    Args:
        workflow_id: The workflow ID
        step_id: The step ID to remove

    Returns:
        {"status": "success", "removed_step_id": str}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}
    if not step_id:
        return {"status": "failure", "reason": "missing_step_id"}

    # Load workflow
    workflows = load_active_workflows()
    workflow = None
    for wf in workflows:
        if wf.get("id") == workflow_id:
            workflow = wf
            break

    if workflow is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    # Find step
    steps = workflow.get("steps", [])
    step_index = None
    step = None
    for i, s in enumerate(steps):
        if s.get("id") == step_id:
            step_index = i
            step = s
            break

    if step is None:
        return {"status": "failure", "reason": "step_not_found"}

    # Check step state - COMPLETED steps are locked
    if step.get("status") == "COMPLETED":
        return {"status": "failure", "reason": "completed_step_locked"}

    # Check for dependents
    for s in steps:
        depends_on = s.get("depends_on", [])
        if step_id in depends_on:
            return {
                "status": "failure",
                "reason": "step_has_dependents",
                "dependent_step_id": s.get("id")
            }

    # Remove step
    steps.pop(step_index)

    # Validate workflow still valid
    validation = validate_workflow(workflow)
    if validation["status"] == "failure":
        # Re-add the step (this shouldn't happen, but safety first)
        steps.insert(step_index, step)
        return {"status": "failure", "reason": f"validation_failed:{validation.get('reason')}"}

    # Save updated workflow
    save_workflow(workflow)

    return {
        "status": "success",
        "removed_step_id": step_id,
        "workflow_id": workflow_id
    }


def reorder_steps(workflow_id: str, new_order: List[str]) -> Dict[str, Any]:
    """
    Reorder steps in the workflow plan.
    Per PLAN_CONTROL_CONTRACT_V1: Validates dependency constraints.

    Args:
        workflow_id: The workflow ID
        new_order: List of step IDs in new order

    Returns:
        {"status": "success", "new_order": [...]}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}
    if not new_order:
        return {"status": "failure", "reason": "empty_new_order"}

    # Load workflow
    workflows = load_active_workflows()
    workflow = None
    for wf in workflows:
        if wf.get("id") == workflow_id:
            workflow = wf
            break

    if workflow is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    steps = workflow.get("steps", [])
    current_ids = {s.get("id") for s in steps}

    # Validate new_order contains all current steps
    new_ids = set(new_order)
    if new_ids != current_ids:
        return {"status": "failure", "reason": "order_must_include_all_steps"}

    # Create new step list in specified order
    step_map = {s.get("id"): s for s in steps}
    new_steps = [step_map[sid] for sid in new_order if sid in step_map]

    # Temporarily update workflow
    original_steps = steps.copy()
    workflow["steps"] = new_steps

    # Validate dependency constraints
    validation = validate_workflow(workflow)
    if validation["status"] == "failure":
        # Restore original order
        workflow["steps"] = original_steps
        return {"status": "failure", "reason": f"dependency_violation:{validation.get('reason')}"}

    # Save updated workflow
    save_workflow(workflow)

    return {
        "status": "success",
        "new_order": new_order,
        "workflow_id": workflow_id
    }


# ============================================================================
# SUB-PHASE 3D — CONTROL ACTIONS
# ============================================================================

def retry_step(workflow_id: str, step_id: str) -> Dict[str, Any]:
    """
    Retry a failed or blocked step.
    Per STATE_TRANSITIONS_CONTRACT_V1: FAILED|BLOCKED → PENDING → ACTIVE

    Args:
        workflow_id: The workflow ID
        step_id: The step ID to retry

    Returns:
        {"status": "success", "step": updated_step}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}
    if not step_id:
        return {"status": "failure", "reason": "missing_step_id"}

    # Load workflow
    workflows = load_active_workflows()
    workflow = None
    for wf in workflows:
        if wf.get("id") == workflow_id:
            workflow = wf
            break

    if workflow is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    # Find step
    step = None
    for s in workflow.get("steps", []):
        if s.get("id") == step_id:
            step = s
            break

    if step is None:
        return {"status": "failure", "reason": "step_not_found"}

    # Check current status
    current_status = step.get("status", "PENDING")
    if current_status not in ["FAILED", "BLOCKED"]:
        return {"status": "failure", "reason": f"cannot_retry_{current_status}_step"}

    # Reset step for retry per STATE_TRANSITIONS_CONTRACT_V1
    step["status"] = "PENDING"
    step["retries"] = 0
    step.pop("execution_result", None)
    step.pop("output", None)
    step.pop("blocked_reason", None)

    # Save workflow
    save_workflow(workflow)

    # Emit retry event
    try:
        event_emitter.emit_step_retry(
            workflow_id=workflow_id,
            step_id=step_id,
            retry_count=0,
            max_retries=step.get("max_retries", 3),
            reason="user_retry"
        )
    except Exception:
        pass

    return {
        "status": "success",
        "step": step,
        "workflow_id": workflow_id
    }


def stop_workflow(workflow_id: str) -> Dict[str, Any]:
    """
    Stop a running workflow.
    Per STATE_TRANSITIONS_CONTRACT_V1: ACTIVE|PAUSED|BLOCKED → FAILED

    Args:
        workflow_id: The workflow ID

    Returns:
        {"status": "success", "previous_state": str, "new_state": "FAILED"}
        or {"status": "failure", "reason": str}
    """
    if not workflow_id:
        return {"status": "failure", "reason": "missing_workflow_id"}

    current_state = _get_workflow_state(workflow_id)
    if current_state is None:
        return {"status": "failure", "reason": "workflow_not_found"}

    current = current_state.get("status", "QUEUED")

    # Per STATE_TRANSITIONS_CONTRACT_V1: Can stop from ACTIVE, PAUSED, or BLOCKED
    if current not in ["ACTIVE", "PAUSED", "BLOCKED"]:
        return {"status": "failure", "reason": f"cannot_stop_{current}_workflow"}

    # Perform transition to FAILED
    if not _update_workflow_state(workflow_id, "FAILED", "user_stop"):
        return {"status": "failure", "reason": "update_failed"}

    # Emit event
    try:
        event_emitter.emit_state_transition(
            workflow_id=workflow_id,
            step_id=None,
            previous_state=current,
            new_state="FAILED",
            reason="user_stop"
        )
        event_emitter.emit_event(
            event_type="PROJECT_FAILED",
            workflow_id=workflow_id,
            data={"timestamp": time.time(), "reason": "user_stop"}
        )
    except Exception:
        pass

    return {
        "status": "success",
        "previous_state": current,
        "new_state": "FAILED",
        "workflow_id": workflow_id
    }
