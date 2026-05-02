#!/usr/bin/env python3
"""
TRACE UTILITIES AUDIT - Phase 4: Live Execution Test
Run controlled workflows and attempt to use trace utilities
"""

import json
import sys

# Test 1: Execute via orchestrator_runtime to generate trace data
print("=" * 70)
print("PHASE 4: LIVE EXECUTION TEST")
print("=" * 70)

# Import and run workflow
from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator import trace_collector

# Test inputs
test_inputs = [
    "add 2 and 3",
    "divide 5 by 0", 
    "repeat hello 3 times",
    "what is 2+2"
]

workflow_ids = []

for i, test_input in enumerate(test_inputs, 1):
    print(f"\n--- Test {i}: '{test_input}' ---")
    try:
        # Create workflow with ALL required fields per workflow_validator.py
        workflow = {
            "id": f"audit_test_{i}",
            "name": f"audit_test_{i}",  # REQUIRED
            "status": "ACTIVE",
            "steps": [
                {
                    "id": f"step_{i}",
                    "name": f"step_{i}",  # REQUIRED
                    "agent": "system",     # REQUIRED
                    "purpose": test_input,
                    "input": test_input,    # REQUIRED (was input_text)
                    "status": "PENDING",
                    "retries": 0,
                    "max_retries": 2
                }
            ]
        }
        
        # Run workflow
        result = run_workflow(workflow)
        workflow_ids.append(f"audit_test_{i}")
        
        print(f"Workflow result: {result}")
        
        # Try to get trace immediately after
        trace = trace_collector.get_trace()
        print(f"Trace available immediately: {trace is not None}")
        if trace:
            print(f"Trace steps count: {len(trace.get('steps', []))}")
        
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")

print("\n" + "=" * 70)
print("PHASE 4 COMPLETE - Now testing trace utilities")
print("=" * 70)

# Test 2: Try to use trace utilities
print("\n--- Testing trace_collector.get_trace() ---")
trace = trace_collector.get_trace()
print(f"Trace data type: {type(trace)}")
if trace:
    print(f"Trace keys: {trace.keys() if isinstance(trace, dict) else 'N/A'}")
    print(f"Workflow ID: {trace.get('workflow_id', 'N/A')}")
    print(f"Step count: {len(trace.get('steps', []))}")
else:
    print("No trace data available")

# Test 3: Try trace utilities if trace exists
if trace:
    print("\n--- Testing decision_viewer ---")
    try:
        from system.trace_utils.decision_viewer import build_decision_view, print_decision_view
        decision_view = build_decision_view(trace)
        print(f"Decision view created: {type(decision_view)}")
        if decision_view:
            print_decision_view(decision_view)
    except Exception as e:
        print(f"decision_viewer error: {e}")
    
    print("\n--- Testing retry_analyzer ---")
    try:
        from system.trace_utils.retry_analyzer import analyze_retries, print_retry_analysis
        retry_analysis = analyze_retries(trace)
        print(f"Retry analysis created: {type(retry_analysis)}")
        if retry_analysis:
            print_retry_analysis(retry_analysis)
    except Exception as e:
        print(f"retry_analyzer error: {e}")
    
    print("\n--- Testing step_timeline_viewer ---")
    try:
        from system.trace_utils.step_timeline_viewer import build_step_timeline, print_timeline
        timeline = build_step_timeline(trace)
        print(f"Timeline created: {type(timeline)}")
        if timeline:
            print_timeline(timeline)
    except Exception as e:
        print(f"step_timeline_viewer error: {e}")
else:
    print("\nSkipping utility tests - no trace data available")

print("\n" + "=" * 70)
print("LIVE EXECUTION TEST COMPLETE")
print("=" * 70)
