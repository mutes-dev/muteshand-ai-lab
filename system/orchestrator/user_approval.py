"""
USER APPROVAL — Execution Gate

Responsibility:
- Pause execution BEFORE sensitive steps
- Gate execution based on explicit approval_required flag
- Return execution control cleanly on denial

Architecture Alignment:
- Approval is a GATE, not a decision-maker
- Governance remains sole decision authority
- Escalation and retry logic unaffected

Rules:
- NO LLM usage
- NO dynamic logic
- NO blocking I/O (Phase 4 = placeholder/auto-approve)
- deterministic only
- explicit approval_required flag only
"""

from typing import Dict, Any


def requires_approval(step: Dict[str, Any], workflow: Dict[str, Any]) -> bool:
    """
    Determines if a step requires user approval.
    
    MUST be deterministic and simple.
    
    Phase 4 rule (minimal):
    - Only require approval if explicitly flagged
    
    Args:
        step: The step being processed
        workflow: The parent workflow
        
    Returns:
        True if approval required, False otherwise
    """
    # Approval triggered ONLY by explicit flag
    return step.get("approval_required", False)


def request_approval(step: Dict[str, Any]) -> bool:
    """
    Simulated approval (Phase 4 = placeholder).
    
    ALWAYS returns True (auto-approve).
    
    Later phases will replace this with real user input.
    
    Args:
        step: The step being processed
        
    Returns:
        True if approved, False if denied
    """
    # Phase 4: Auto-approve (placeholder)
    # Future: Replace with actual user input
    return True
