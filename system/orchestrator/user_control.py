"""
USER CONTROL — Pause / Resume

Responsibility:
- Provide user control capabilities over execution flow
- Pause execution before step processing
- Resume execution from paused state

Architecture Alignment:
- User control influences flow, NOT outcomes
- Governance remains sole decision authority
- Execution_result remains unchanged
- Escalation and retry logic unaffected

Rules:
- NO external I/O (Phase 5: simple in-memory)
- NO blocking input
- deterministic only
- minimal implementation
"""

from typing import Dict, Any


def get_control_state() -> Dict[str, Any]:
    """
    Get current control state (for debugging/observability).
    
    Returns:
        Empty dict — no active global control state.
    """
    return {}


# Per STATE_TRANSITIONS_CONTRACT_V1 & GUI_FUNCTIONALITY_CONTRACT_V1:
# Pause/resume are now workflow-scoped state transitions ONLY.
# Use workflow_control.pause_workflow(workflow_id) and resume_workflow(workflow_id)
# DO NOT use global pause/resume.
