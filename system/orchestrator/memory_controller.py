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
