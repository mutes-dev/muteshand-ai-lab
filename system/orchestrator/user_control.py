"""
USER CONTROL — Pause / Resume / Override

Responsibility:
- Provide user control capabilities over execution flow
- Pause execution before step processing
- Resume execution from paused state
- Override workflow termination on BLOCKED

Architecture Alignment:
- User control influences flow, NOT outcomes
- Governance remains sole decision authority
- Execution_result remains unchanged
- Escalation and retry logic unaffected by default

Rules:
- NO external I/O (Phase 5: simple in-memory)
- NO blocking input
- deterministic only
- minimal implementation
- Override ONLY affects termination (when BLOCKED)
"""

from typing import Dict, Any


# Global control state (Phase 5: simple in-memory)
_control_state = {
    "paused": False,
    "override": False
}


def is_paused() -> bool:
    """
    Check if execution is currently paused.
    
    Returns:
        True if paused, False otherwise
    """
    return _control_state["paused"]


def pause():
    """
    Pause execution. Next step will return paused status.
    """
    _control_state["paused"] = True


def resume():
    """
    Resume execution from paused state.
    """
    _control_state["paused"] = False


def set_override(value: bool):
    """
    Set override flag. When True, BLOCKED steps will continue
    instead of stopping execution.
    
    Args:
        value: True to enable override, False to disable
    """
    _control_state["override"] = value


def get_override() -> bool:
    """
    Check if override is currently enabled.
    
    Returns:
        True if override enabled, False otherwise
    """
    return _control_state["override"]


def get_control_state() -> Dict[str, Any]:
    """
    Get current control state (for debugging/observability).
    
    Returns:
        Dict with current paused and override values
    """
    return _control_state.copy()
