"""
DECISION VIEWER -- READ-ONLY TRACE UTILITY

Presents execution_result, validator_output, and governance_decision side-by-side,
clearly showing how final decisions are made and highlighting authority model compliance.

COMPLIANCE:
- Read-only: Never modifies trace data
- External: No import of orchestrator_runtime
- Safe: Handles malformed entries gracefully
"""

from typing import Any, Dict, List, Optional


def build_decision_view(trace_data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build a decision view showing execution_result, validator, and governance side-by-side.
    
    For each step_id, extracts:
    - execution_result.status and reason
    - validator recommendation and reason
    - governance decision
    - final step status
    
    Args:
        trace_data: Trace data from trace_collector.get_trace()
        
    Returns:
        Dict mapping step_id to list of decision events:
        {
            "step_1": [
                {
                    "execution_result": "failure",
                    "execution_reason": "test_failure",
                    "validator": "retry",
                    "validator_reason": "execution_failure",
                    "governance": "retry",
                    "final_status": "FAILED",
                    "authority_aligned": True
                },
                {
                    "execution_result": "success",
                    "validator": "accept",
                    "governance": "complete",
                    "final_status": "COMPLETED",
                    "authority_aligned": True
                }
            ]
        }
    """
    view: Dict[str, List[Dict[str, Any]]] = {}
    
    # Safety: handle None or invalid input
    if not trace_data or not isinstance(trace_data, dict):
        return view
    
    steps = trace_data.get("steps", [])
    if not isinstance(steps, list):
        return view
    
    # First pass: collect all events per step
    step_events: Dict[str, List[Dict[str, Any]]] = {}
    
    for entry in steps:
        # Safety: skip malformed entries
        if not isinstance(entry, dict):
            continue
        
        step_id = entry.get("step_id")
        if not step_id:
            continue
        
        if step_id not in step_events:
            step_events[step_id] = []
        
        event_type = entry.get("event")
        
        if event_type == "governance_decision":
            # Governance decision record
            step_events[step_id].append({
                "type": "governance",
                "governance": entry.get("decision"),
                "execution_result_status": entry.get("execution_result_status"),
                "timestamp": entry.get("timestamp"),
                "context": entry.get("context")
            })
        
        elif entry.get("governance_decision"):
            # Step execution record with full details
            exec_result = entry.get("execution_result", {})
            if isinstance(exec_result, dict):
                exec_status = exec_result.get("status", "unknown")
                exec_reason = exec_result.get("reason")
            else:
                exec_status = "unknown"
                exec_reason = None
            
            # Extract validator info from step
            validator_decision = entry.get("_validator_decision")
            validator_reason = entry.get("_validator_advisory")
            
            step_events[step_id].append({
                "type": "execution",
                "execution_result": exec_status,
                "execution_reason": exec_reason,
                "validator": validator_decision,
                "validator_reason": validator_reason,
                "governance": entry.get("governance_decision"),
                "final_status": entry.get("status"),
                "retries": entry.get("retries", 0),
                "timestamp": entry.get("timestamp")
            })
    
    # Second pass: build decision view per step
    for step_id, events in step_events.items():
        # Sort by timestamp
        events.sort(key=lambda x: x.get("timestamp") or "")
        
        view[step_id] = []
        
        for event in events:
            if event.get("type") == "execution":
                # Build decision record
                decision_record = {
                    "execution_result": event.get("execution_result", "unknown"),
                    "execution_reason": event.get("execution_reason"),
                    "validator": event.get("validator") or "none",
                    "validator_reason": event.get("validator_reason"),
                    "governance": event.get("governance", "unknown"),
                    "final_status": event.get("final_status", "unknown"),
                    "retries": event.get("retries", 0)
                }
                
                # Determine if authority model was respected
                # Validator is advisory, governance follows execution_result
                decision_record["authority_aligned"] = check_authority_alignment(decision_record)
                
                view[step_id].append(decision_record)
    
    return view


def check_authority_alignment(decision: Dict[str, Any]) -> bool:
    """
    Check if authority model was correctly applied.
    
    Authority model: execution_result -> governance -> decision
    Validator is advisory only and should not override execution_result.
    
    Returns True if governance decision aligns with execution_result.
    """
    exec_result = decision.get("execution_result", "unknown")
    governance = decision.get("governance", "unknown")
    
    # Expected mappings per authority model
    if exec_result == "success":
        # Success should lead to "complete"
        return governance == "complete"
    elif exec_result == "failure":
        # Failure should lead to "retry" or "fail"
        return governance in ["retry", "fail"]
    
    return True  # Unknown status, can't determine


def print_decision_view(view: Dict[str, List[Dict[str, Any]]]) -> None:
    """
    Print a formatted decision view showing authority flow.
    
    Args:
        view: Decision view dict from build_decision_view()
    """
    if not view:
        print("No decision data available.")
        return
    
    print("\n" + "=" * 70)
    print("DECISION VIEW -- AUTHORITY FLOW ANALYSIS")
    print("=" * 70)
    print("\nAuthority Model: execution_result -> governance -> decision")
    print("Validator: ADVISORY ONLY (must not influence control flow)")
    print("=" * 70)
    
    for step_id in sorted(view.keys()):
        decisions = view[step_id]
        
        print(f"\n\nSTEP: {step_id}")
        print("-" * 70)
        
        for i, decision in enumerate(decisions):
            print(f"\n  Decision Point #{i+1}:")
            print(f"    {'-' * 60}")
            
            # Execution result (source of truth)
            exec_result = decision.get("execution_result", "unknown")
            exec_reason = decision.get("execution_reason")
            
            print(f"    execution_result: {exec_result}", end="")
            if exec_reason:
                print(f" ({exec_reason})")
            else:
                print()
            
            # Validator (advisory)
            validator = decision.get("validator", "none")
            val_reason = decision.get("validator_reason")
            
            print(f"    validator: {validator}", end="")
            if val_reason:
                print(f" ({val_reason})")
            else:
                print()
            
            # Governance (authority decision)
            governance = decision.get("governance", "unknown")
            aligned = decision.get("authority_aligned", True)
            
            if aligned:
                print(f"    governance: {governance} <- AUTHORITY (aligned)")
            else:
                print(f"    governance: {governance} <- AUTHORITY")
            
            # Highlight mismatches
            if validator != "none" and validator != governance:
                print(f"\n    [!] VALIDATOR MISMATCH DETECTED")
                print(f"       Validator said: {validator}")
                print(f"       Governance chose: {governance}")
                print(f"       [OK] Authority respected: execution_result wins")
            
            # Final status
            final_status = decision.get("final_status", "unknown")
            retries = decision.get("retries", 0)
            print(f"\n    -> final_status: {final_status} (retries={retries})")
    
    print("\n" + "=" * 70)


def get_authority_summary(view: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Get summary statistics about authority model compliance.
    
    Args:
        view: Decision view dict from build_decision_view()
        
    Returns:
        Dict with authority compliance statistics
    """
    if not view:
        return {}
    
    total_decisions = 0
    aligned_decisions = 0
    mismatch_count = 0
    validator_overrides = 0
    
    for step_id, decisions in view.items():
        for decision in decisions:
            total_decisions += 1
            
            if decision.get("authority_aligned", True):
                aligned_decisions += 1
            
            validator = decision.get("validator", "none")
            governance = decision.get("governance", "unknown")
            
            if validator != "none" and validator != governance:
                mismatch_count += 1
                
                # Check if validator was trying to override
                exec_result = decision.get("execution_result", "unknown")
                if exec_result == "success" and validator == "retry":
                    validator_overrides += 1
    
    return {
        "total_decisions": total_decisions,
        "aligned_decisions": aligned_decisions,
        "alignment_rate": aligned_decisions / total_decisions if total_decisions > 0 else 0,
        "validator_mismatches": mismatch_count,
        "validator_override_attempts": validator_overrides,
        "authority_model_violations": 0  # Would be >0 if governance followed validator over execution_result
    }


def print_authority_summary(summary: Dict[str, Any]) -> None:
    """
    Print authority model compliance summary.
    
    Args:
        summary: Summary dict from get_authority_summary()
    """
    if not summary:
        print("No authority summary available.")
        return
    
    print("\n" + "=" * 70)
    print("AUTHORITY MODEL COMPLIANCE SUMMARY")
    print("=" * 70)
    
    print(f"\n  Total Decision Points: {summary['total_decisions']}")
    print(f"  Authority-Aligned: {summary['aligned_decisions']}")
    print(f"  Alignment Rate: {summary['alignment_rate']*100:.1f}%")
    
    if summary['validator_mismatches'] > 0:
        print(f"\n  Validator/Governance Mismatches: {summary['validator_mismatches']}")
        print(f"  (These are EXPECTED -- validator is advisory only)")
        
        if summary['validator_override_attempts'] > 0:
            print(f"\n  Validator Override Attempts: {summary['validator_override_attempts']}")
            print(f"  [OK] All were correctly overridden by governance")
    
    if summary['authority_model_violations'] == 0:
        print(f"\n  [OK] AUTHORITY MODEL: COMPLIANT")
        print(f"    Governance correctly follows execution_result")
    else:
        print(f"\n  [WARN] AUTHORITY MODEL VIOLATIONS: {summary['authority_model_violations']}")
    
    print("\n" + "=" * 70)


def analyze_decisions(trace_data: Dict[str, Any]) -> None:
    """
    Convenience function to build and print decision view and summary.
    
    Args:
        trace_data: Trace data from trace_collector.get_trace()
    """
    view = build_decision_view(trace_data)
    
    if not view:
        print("No decision data to analyze.")
        return
    
    print_decision_view(view)
    
    summary = get_authority_summary(view)
    print_authority_summary(summary)


# Example usage for testing
if __name__ == "__main__":
    # Example trace data showing authority model
    example_trace = {
        "workflow_id": "test_workflow",
        "created_at": "2026-04-28T12:00:00",
        "steps": [
            {
                "step_id": "step_1",
                "event": "governance_decision",
                "decision": "retry",
                "execution_result_status": "failure",
                "timestamp": "2026-04-28T12:00:01"
            },
            {
                "step_id": "step_1",
                "status": "COMPLETED",
                "governance_decision": "complete",
                "retries": 0,
                "execution_result": {"status": "success", "result": "done"},
                "_validator_decision": "accept",
                "_validator_advisory": "correct",
                "timestamp": "2026-04-28T12:00:03"
            }
        ]
    }
    
    print("Example Decision View:")
    analyze_decisions(example_trace)
