"""
MEMORY CONTROLLER — Runtime State Extraction

Responsibility:
- Own ALL execution memory access
- Provide controlled read/write methods for workflow context
- Centralize memory mutations to single module

Architecture Alignment:
- Runtime orchestrates ONLY
- Memory controller owns ALL workflow["context"] access
- NO other layer may read/write workflow["context"] directly

Rules:
- NO logic inside (no decisions)
- NO transformation of values
- PURE read/write layer
- Single source of truth for execution memory
"""

from typing import Dict, Any, Optional, List


def get_context(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get workflow context dictionary.
    
    Args:
        workflow: The parent workflow
        
    Returns:
        Context dictionary (creates if missing)
    """
    if "context" not in workflow:
        workflow["context"] = {}
    return workflow["context"]


def get_last_result(workflow: Dict[str, Any]) -> Any:
    """
    Get last execution result from context.
    
    Args:
        workflow: The parent workflow
        
    Returns:
        Last result value or None
    """
    context = get_context(workflow)
    return context.get("last_result")


def set_last_result(workflow: Dict[str, Any], value: Any) -> None:
    """
    Set last execution result in context.
    
    Args:
        workflow: The parent workflow
        value: Result value to store
    """
    context = get_context(workflow)
    context["last_result"] = value


def append_step_history(workflow: Dict[str, Any], step_data: Dict[str, Any]) -> None:
    """
    Append step data to execution history.
    
    Args:
        workflow: The parent workflow
        step_data: Step execution data to record
    """
    context = get_context(workflow)
    
    if "step_history" not in context:
        context["step_history"] = []
    
    context["step_history"].append(step_data)


def get_step_history(workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Get step execution history.
    
    Args:
        workflow: The parent workflow
        
    Returns:
        List of step history entries
    """
    context = get_context(workflow)
    return context.get("step_history", [])


def clear_step_history(workflow: Dict[str, Any]) -> None:
    """
    Clear step execution history.
    
    Args:
        workflow: The parent workflow
    """
    context = get_context(workflow)
    if "step_history" in context:
        context["step_history"] = []


# === STEP IO CONTRACT — Per-Step Output Store (STEP_IO_CONTRACT_V1) ===
# Outputs are stored per step_id, scoped to this execution context.
# Access is dependency-gated: only declared dependents may read an output.
# No global result state. No implicit sharing.

def set_step_output(workflow: Dict[str, Any], step_id: str, execution_result: Dict[str, Any]) -> None:
    """
    Store a step's output in the per-step output store.

    Per STEP_IO_CONTRACT_V1 Section 2: outputs stored per step_id,
    scoped to execution context. Overwrites any prior value for that
    step_id (expected on retry after invalidation).
    """
    context = get_context(workflow)
    if "step_outputs" not in context:
        context["step_outputs"] = {}
    context["step_outputs"][step_id] = {
        "status": execution_result.get("status"),
        "data": execution_result.get("result"),
        "metadata": {
            "step_id": step_id,
            "execution_id": workflow.get("id", "unknown")
        }
    }


def get_step_output(workflow: Dict[str, Any], step_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a single step's stored output.

    Returns None if no output exists for that step_id.
    """
    context = get_context(workflow)
    return context.get("step_outputs", {}).get(step_id)


def get_dependency_outputs(workflow: Dict[str, Any], depends_on: List[str]) -> Dict[str, Any]:
    """
    Return outputs ONLY for declared dependency step_ids.

    Per STEP_IO_CONTRACT_V1 Section 3: a step may only access output
    from steps it has explicitly declared in depends_on.
    Any undeclared step_id is excluded — no implicit access.

    Args:
        workflow: The parent workflow
        depends_on: List of step_ids declared as dependencies

    Returns:
        Dict mapping dep_id -> step_output for each declared dependency
        that has a stored output. Empty dict if depends_on is empty.
    """
    if not depends_on:
        return {}
    context = get_context(workflow)
    store = context.get("step_outputs", {})
    return {dep_id: store[dep_id] for dep_id in depends_on if dep_id in store}


def invalidate_step_outputs(workflow: Dict[str, Any], step_id: str) -> None:
    """
    Invalidate output for step_id and all steps that depend on it.

    Per STEP_IO_CONTRACT_V1 Section 6: on retry or re-execution,
    the step's output AND all dependent step outputs MUST be deleted.
    System MUST NOT serve stale outputs to dependents after invalidation.
    """
    context = get_context(workflow)
    store = context.get("step_outputs", {})

    # Delete the retried step's output
    store.pop(step_id, None)

    # Delete outputs of all steps that declared this step as a dependency
    for step in workflow.get("steps", []):
        if isinstance(step, dict):
            if step_id in step.get("depends_on", []):
                store.pop(step.get("id"), None)
