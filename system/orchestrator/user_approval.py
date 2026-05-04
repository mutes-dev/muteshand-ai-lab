"""
USER APPROVAL — Execution Gate (Phase 1D — Governance-Aligned)

Responsibility:
- Execute user approval interaction ONLY when governance has decided BLOCK
- Governance is the SOLE authority for approval decisions
- This module ONLY handles the user interaction

Architecture Alignment:
- Governance decides BLOCK + sets blocked_reason = "approval_required"
- Runtime detects blocked_reason and calls request_approval()
- This module presents the prompt and returns the user's response
- NO decision logic — pure interaction

Rules:
- NO LLM usage
- NO decision making (governance decides)
- Minimal CLI interface (Phase 1D scope)
- Deterministic interaction only
"""

from typing import Dict, Any
from system.orchestrator import trace_collector


def requires_approval(step: Dict[str, Any], workflow: Dict[str, Any]) -> bool:
    """
    DEPRECATED (Phase 1D): Governance is the SOLE approval authority.

    This function is retained for backward compatibility but should NOT
    be called for approval decisions. Governance.decide_next_action()
    is the sole authority via _check_approval_required().

    Returns:
        False always — governance handles approval decisions.
    """
    # Governance is sole authority. This function no longer decides.
    return False


def request_approval(step: Dict[str, Any]) -> bool:
    """
    Request user approval for a governance-blocked step.

    Called ONLY when governance has decided BLOCK with
    blocked_reason = "approval_required".

    Presents step details to user and waits for explicit approval.

    Args:
        step: The step requiring approval (must have purpose, risk, tool_call)

    Returns:
        True if user approves, False if user denies
    """
    step_id = step.get("id", "unknown")

    # TRACE: APPROVAL_REQUESTED
    try:
        trace_collector.record_transition(
            step_id=step_id,
            previous_status="BLOCKED",
            new_status="BLOCKED",
            reason="APPROVAL_REQUESTED"
        )
    except Exception:
        pass

    print("\n" + "=" * 50)
    print("[APPROVAL REQUIRED]")
    print("=" * 50)
    print(f"  Step:    {step.get('purpose', 'Unknown purpose')}")
    print(f"  Type:    {step.get('type', 'Unknown')}")
    print(f"  Risk:    {step.get('risk', 'Unknown')}")
    print(f"  Tool:    {step.get('tool_call', 'Unknown')}")
    if step.get("resource_targets"):
        print(f"  Targets: {step.get('resource_targets')}")
    print("=" * 50)

    try:
        response = input("Approve execution? (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        # Non-interactive environment or user interrupt — deny
        response = "n"

    approved = response == "y"

    # TRACE: APPROVAL_RESULT
    try:
        trace_collector.record_transition(
            step_id=step_id,
            previous_status="BLOCKED",
            new_status="BLOCKED" if not approved else "ACTIVE",
            reason=f"APPROVAL_{'GRANTED' if approved else 'DENIED'}"
        )
    except Exception:
        pass

    return approved
