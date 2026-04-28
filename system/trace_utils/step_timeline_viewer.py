"""
STEP TIMELINE VIEWER — READ-ONLY TRACE UTILITY

Consumes TRACE data and produces a clear, ordered timeline of step execution.

COMPLIANCE:
- Read-only: Never modifies trace data
- External: No import of orchestrator_runtime
- Safe: Handles malformed entries gracefully
"""

from typing import Any, Dict, List, Optional
from datetime import datetime


def build_step_timeline(trace_data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Build a timeline of step execution from trace data.
    
    Groups entries by step_id in chronological order.
    Extracts: status transitions, retry count, governance decisions.
    
    Args:
        trace_data: Trace data from trace_collector.get_trace()
        
    Returns:
        Dict mapping step_id to ordered list of timeline events
        {
            "step_1": [
                {"event": "governance_decision", "decision": "retry", "retries": 0, "timestamp": "..."},
                {"event": "RUNNING", "retries": 0, "timestamp": "..."},
                {"event": "COMPLETED", "decision": "complete", "retries": 0, "timestamp": "..."}
            ]
        }
    """
    timeline: Dict[str, List[Dict[str, Any]]] = {}
    
    # Safety: handle None or invalid input
    if not trace_data or not isinstance(trace_data, dict):
        return timeline
    
    steps = trace_data.get("steps", [])
    if not isinstance(steps, list):
        return timeline
    
    for entry in steps:
        # Safety: skip malformed entries
        if not isinstance(entry, dict):
            continue
        
        step_id = entry.get("step_id")
        if not step_id:
            continue
        
        # Initialize step timeline if needed
        if step_id not in timeline:
            timeline[step_id] = []
        
        # Parse entry based on type
        event_type = entry.get("event")
        
        if event_type == "governance_decision":
            # Governance decision record
            timeline[step_id].append({
                "event": "governance_decision",
                "decision": entry.get("decision"),
                "execution_result_status": entry.get("execution_result_status"),
                "context": entry.get("context"),
                "timestamp": entry.get("timestamp")
            })
        
        elif event_type == "state_transition":
            # State transition record
            timeline[step_id].append({
                "event": "state_transition",
                "previous_status": entry.get("previous_status"),
                "new_status": entry.get("new_status"),
                "reason": entry.get("reason"),
                "timestamp": entry.get("timestamp")
            })
        
        elif entry.get("governance_decision"):
            # Step execution record (final state)
            timeline[step_id].append({
                "event": entry.get("status", "unknown"),
                "decision": entry.get("governance_decision"),
                "retries": entry.get("retries", 0),
                "execution_result": entry.get("execution_result"),
                "validator_advisory": entry.get("validator_advisory"),
                "timestamp": entry.get("timestamp")
            })
    
    # Sort each step's timeline by timestamp
    for step_id in timeline:
        timeline[step_id].sort(key=lambda x: x.get("timestamp") or "")
    
    return timeline


def print_timeline(timeline: Dict[str, List[Dict[str, Any]]]) -> None:
    """
    Print a formatted timeline view.
    
    Args:
        timeline: Timeline dict from build_step_timeline()
    """
    if not timeline:
        print("No timeline data available.")
        return
    
    print("\n" + "=" * 60)
    print("STEP EXECUTION TIMELINE")
    print("=" * 60)
    
    for step_id in sorted(timeline.keys()):
        events = timeline[step_id]
        
        print(f"\nSTEP: {step_id}")
        print("-" * 40)
        
        for i, event in enumerate(events):
            event_type = event.get("event", "unknown")
            timestamp = event.get("timestamp", "")
            
            # Format based on event type
            if event_type == "governance_decision":
                decision = event.get("decision", "unknown")
                exec_status = event.get("execution_result_status", "unknown")
                print(f"  [{i+1}] GOVERNANCE: decision={decision}, exec_status={exec_status}")
            
            elif event_type == "state_transition":
                prev = event.get("previous_status", "?")
                new = event.get("new_status", "?")
                print(f"  [{i+1}] TRANSITION: {prev} -> {new}")
            
            else:
                # Status event (RUNNING, COMPLETED, FAILED, BLOCKED)
                retries = event.get("retries", 0)
                decision = event.get("decision", "")
                
                if decision:
                    print(f"  [{i+1}] {event_type} (retries={retries}) -> {decision}")
                else:
                    print(f"  [{i+1}] {event_type} (retries={retries})")
    
    print("\n" + "=" * 60)


def get_step_summary(timeline: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """
    Get a summary of each step's execution.
    
    Args:
        timeline: Timeline dict from build_step_timeline()
        
    Returns:
        Dict with step_id -> summary info
    """
    summary = {}
    
    for step_id, events in timeline.items():
        if not events:
            continue
        
        # Get final state
        final_event = events[-1]
        
        # Count retries
        retry_count = 0
        for e in events:
            if e.get("event") == "governance_decision" and e.get("decision") == "retry":
                retry_count += 1
        
        # Get execution status
        exec_result = final_event.get("execution_result", {})
        if isinstance(exec_result, dict):
            exec_status = exec_result.get("status", "unknown")
        else:
            exec_status = "unknown"
        
        summary[step_id] = {
            "final_status": final_event.get("event", "unknown"),
            "final_decision": final_event.get("decision", "unknown"),
            "retry_count": retry_count,
            "execution_status": exec_status,
            "event_count": len(events)
        }
    
    return summary


def print_summary(summary: Dict[str, Dict[str, Any]]) -> None:
    """
    Print a summary view of step execution.
    
    Args:
        summary: Summary dict from get_step_summary()
    """
    if not summary:
        print("No summary data available.")
        return
    
    print("\n" + "=" * 60)
    print("STEP EXECUTION SUMMARY")
    print("=" * 60)
    
    for step_id in sorted(summary.keys()):
        info = summary[step_id]
        print(f"\n  {step_id}:")
        print(f"    Final Status: {info['final_status']}")
        print(f"    Decision: {info['final_decision']}")
        print(f"    Retries: {info['retry_count']}")
        print(f"    Execution: {info['execution_status']}")
        print(f"    Events: {info['event_count']}")
    
    print("\n" + "=" * 60)


def analyze_trace(trace_data: Dict[str, Any]) -> None:
    """
    Convenience function to build and print timeline and summary.
    
    Args:
        trace_data: Trace data from trace_collector.get_trace()
    """
    timeline = build_step_timeline(trace_data)
    
    if not timeline:
        print("No trace data to analyze.")
        return
    
    print_timeline(timeline)
    
    summary = get_step_summary(timeline)
    print_summary(summary)


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
                "status": "COMPLETED",
                "governance_decision": "complete",
                "retries": 1,
                "execution_result": {"status": "success", "result": "done"},
                "timestamp": "2026-04-28T12:00:02"
            }
        ]
    }
    
    print("Example Trace Analysis:")
    analyze_trace(example_trace)
