"""
RETRY ANALYZER — READ-ONLY TRACE UTILITY

Analyzes TRACE data to extract retry behavior per step.

COMPLIANCE:
- Read-only: Never modifies trace data
- External: No import of orchestrator_runtime
- Safe: Handles malformed entries gracefully
"""

from typing import Any, Dict, List, Optional


def analyze_retries(trace_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Analyze retry behavior from trace data.
    
    For each step_id, extracts:
    - Total executions
    - Retry count
    - Failure events and reasons
    - Success detection
    - Final outcome
    - Retry efficiency classification
    
    Args:
        trace_data: Trace data from trace_collector.get_trace()
        
    Returns:
        Dict mapping step_id to retry analysis:
        {
            "step_1": {
                "executions": 2,
                "retries": 1,
                "failures": 1,
                "success": True,
                "final_status": "COMPLETED",
                "failure_reasons": ["test_failure"],
                "retry_efficiency": "resolved_after_retry"
            }
        }
    """
    analysis: Dict[str, Dict[str, Any]] = {}
    
    # Safety: handle None or invalid input
    if not trace_data or not isinstance(trace_data, dict):
        return analysis
    
    steps = trace_data.get("steps", [])
    if not isinstance(steps, list):
        return analysis
    
    # First pass: collect events per step
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
        
        # Parse entry based on type
        if event_type == "governance_decision":
            # Governance decision indicates execution attempt
            step_events[step_id].append({
                "type": "governance",
                "decision": entry.get("decision"),
                "execution_result_status": entry.get("execution_result_status"),
                "timestamp": entry.get("timestamp")
            })
        
        elif entry.get("governance_decision"):
            # Step execution record (final state)
            exec_result = entry.get("execution_result", {})
            if isinstance(exec_result, dict):
                exec_status = exec_result.get("status", "unknown")
                exec_reason = exec_result.get("reason")
            else:
                exec_status = "unknown"
                exec_reason = None
            
            step_events[step_id].append({
                "type": "execution",
                "status": entry.get("status", "unknown"),
                "governance_decision": entry.get("governance_decision"),
                "retries": entry.get("retries", 0),
                "execution_status": exec_status,
                "execution_reason": exec_reason,
                "timestamp": entry.get("timestamp")
            })
    
    # Second pass: analyze each step
    for step_id, events in step_events.items():
        # Sort by timestamp
        events.sort(key=lambda x: x.get("timestamp") or "")
        
        # Count governance decisions as execution attempts
        executions = sum(1 for e in events if e.get("type") == "governance")
        
        # Count retries
        retry_events = [e for e in events if e.get("decision") == "retry"]
        retries = len(retry_events)
        
        # Collect failure reasons
        failure_reasons = []
        for e in events:
            if e.get("execution_status") == "failure" and e.get("execution_reason"):
                failure_reasons.append(e["execution_reason"])
        
        # Determine final state
        final_execution = None
        for e in reversed(events):
            if e.get("type") == "execution":
                final_execution = e
                break
        
        if final_execution:
            final_status = final_execution.get("status", "unknown")
            final_decision = final_execution.get("governance_decision", "unknown")
            success = final_execution.get("execution_status") == "success"
        else:
            final_status = "unknown"
            final_decision = "unknown"
            success = False
        
        # Classify retry efficiency
        efficiency = classify_efficiency(executions, retries, success, final_status, final_decision)
        
        analysis[step_id] = {
            "executions": executions,
            "retries": retries,
            "failures": len(failure_reasons),
            "success": success,
            "final_status": final_status,
            "final_decision": final_decision,
            "failure_reasons": failure_reasons,
            "retry_efficiency": efficiency,
            "event_count": len(events)
        }
    
    return analysis


def classify_efficiency(executions: int, retries: int, success: bool, 
                        final_status: str, final_decision: str) -> str:
    """
    Classify retry efficiency based on outcome.
    
    Returns:
        - no_retry_needed: Single execution, success
        - resolved_after_retry: Failed first, succeeded after retry
        - failed_after_max_retries: Exhausted retries, still failed
        - unnecessary_retry: Multiple attempts but unclear why
    """
    if executions == 0:
        return "no_execution_recorded"
    
    if executions == 1 and success:
        return "no_retry_needed"
    
    if executions == 1 and not success:
        return "failed_no_retry"
    
    if executions > 1:
        if success:
            return "resolved_after_retry"
        elif final_decision == "fail" or final_status in ["FAILED", "BLOCKED"]:
            return "failed_after_max_retries"
        else:
            return "incomplete"
    
    return "unknown"


def print_retry_analysis(analysis: Dict[str, Dict[str, Any]]) -> None:
    """
    Print formatted retry analysis.
    
    Args:
        analysis: Analysis dict from analyze_retries()
    """
    if not analysis:
        print("No retry analysis data available.")
        return
    
    print("\n" + "=" * 60)
    print("RETRY ANALYSIS REPORT")
    print("=" * 60)
    
    for step_id in sorted(analysis.keys()):
        info = analysis[step_id]
        
        print(f"\nSTEP: {step_id}")
        print("-" * 40)
        print(f"  Executions: {info['executions']}")
        print(f"  Retries: {info['retries']}")
        print(f"  Failures: {info['failures']}")
        print(f"  Success: {info['success']}")
        print(f"  Final Status: {info['final_status']}")
        print(f"  Final Decision: {info['final_decision']}")
        
        if info['failure_reasons']:
            print(f"  Failure Reasons: {', '.join(info['failure_reasons'])}")
        
        print(f"  Efficiency: {info['retry_efficiency']}")
        
        # Efficiency interpretation
        efficiency_note = get_efficiency_note(info['retry_efficiency'])
        if efficiency_note:
            print(f"  Note: {efficiency_note}")
    
    print("\n" + "=" * 60)


def get_efficiency_note(efficiency: str) -> str:
    """Get human-readable note for efficiency classification."""
    notes = {
        "no_retry_needed": "Step succeeded on first attempt",
        "resolved_after_retry": "Retry resolved the issue",
        "failed_after_max_retries": "Max retries exhausted without resolution",
        "failed_no_retry": "Failed without retry attempt",
        "no_execution_recorded": "No execution data found",
        "incomplete": "Execution incomplete",
        "unknown": "Unable to classify"
    }
    return notes.get(efficiency, "")


def get_retry_statistics(analysis: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Get aggregate statistics across all steps.
    
    Args:
        analysis: Analysis dict from analyze_retries()
        
    Returns:
        Dict with aggregate statistics
    """
    if not analysis:
        return {}
    
    total_steps = len(analysis)
    total_executions = sum(s["executions"] for s in analysis.values())
    total_retries = sum(s["retries"] for s in analysis.values())
    total_failures = sum(s["failures"] for s in analysis.values())
    successful_steps = sum(1 for s in analysis.values() if s["success"])
    
    efficiency_counts = {}
    for s in analysis.values():
        eff = s["retry_efficiency"]
        efficiency_counts[eff] = efficiency_counts.get(eff, 0) + 1
    
    return {
        "total_steps": total_steps,
        "total_executions": total_executions,
        "total_retries": total_retries,
        "total_failures": total_failures,
        "successful_steps": successful_steps,
        "failed_steps": total_steps - successful_steps,
        "average_retries_per_step": total_retries / total_steps if total_steps > 0 else 0,
        "efficiency_breakdown": efficiency_counts
    }


def print_retry_statistics(stats: Dict[str, Any]) -> None:
    """
    Print aggregate retry statistics.
    
    Args:
        stats: Statistics dict from get_retry_statistics()
    """
    if not stats:
        print("No statistics available.")
        return
    
    print("\n" + "=" * 60)
    print("AGGREGATE RETRY STATISTICS")
    print("=" * 60)
    
    print(f"\n  Total Steps: {stats['total_steps']}")
    print(f"  Total Executions: {stats['total_executions']}")
    print(f"  Total Retries: {stats['total_retries']}")
    print(f"  Total Failures: {stats['total_failures']}")
    print(f"  Successful Steps: {stats['successful_steps']}")
    print(f"  Failed Steps: {stats['failed_steps']}")
    print(f"  Avg Retries/Step: {stats['average_retries_per_step']:.2f}")
    
    if stats.get('efficiency_breakdown'):
        print("\n  Efficiency Breakdown:")
        for eff, count in sorted(stats['efficiency_breakdown'].items()):
            print(f"    {eff}: {count}")
    
    print("\n" + "=" * 60)


# Example usage for testing
if __name__ == "__main__":
    # Example trace data for testing
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
                "event": "governance_decision",
                "decision": "complete",
                "execution_result_status": "success",
                "timestamp": "2026-04-28T12:00:03"
            },
            {
                "step_id": "step_1",
                "status": "COMPLETED",
                "governance_decision": "complete",
                "retries": 1,
                "execution_result": {"status": "success", "result": "done"},
                "timestamp": "2026-04-28T12:00:03"
            }
        ]
    }
    
    print("Example Retry Analysis:")
    analysis = analyze_retries(example_trace)
    print_retry_analysis(analysis)
    
    stats = get_retry_statistics(analysis)
    print_retry_statistics(stats)
