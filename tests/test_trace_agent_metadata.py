#!/usr/bin/env python3
"""
ISSUE-073 Phase 2 — Trace Agent Metadata Enrichment Tests

Proves:
- TraceCollector.record_step_execution accepts and stores agent_metadata
- Module-level record_step passes agent_metadata through
- agent_metadata appears in trace entry data dict
- agent_metadata is absent-safe (None when not provided)
- Trace enrichment does not affect execution or governance
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from system.orchestrator.trace_collector import TraceCollector, record_step


def test_trace_collector_accepts_agent_metadata():
    """TraceCollector.record_step_execution must accept agent_metadata dict."""
    print("\n[TRACE METADATA] Collector Accepts agent_metadata")

    collector = TraceCollector(workflow_id="wf_test")
    meta = {
        "selected_agent": "tool_selection_agent",
        "selected_agent_type": "tool_selection",
        "agent_authority": "advisory_only"
    }
    collector.record_step_execution(
        step_id="s1",
        purpose="test",
        step_input="square 5",
        execution_result={"status": "success", "result": 25},
        governance_decision="complete",
        retries=0,
        status="COMPLETED",
        agent_metadata=meta
    )

    assert len(collector.steps) == 1, f"Expected 1 trace entry, got {len(collector.steps)}"
    entry = collector.steps[0]
    stored_meta = entry.get("data", {}).get("agent_metadata")
    print(f"  Stored metadata: {stored_meta}")
    assert stored_meta == meta, f"Metadata mismatch: {stored_meta}"
    print("  PASS: agent_metadata stored in trace")
    return True


def test_trace_collector_absent_safe():
    """TraceCollector must handle missing agent_metadata gracefully."""
    print("\n[TRACE METADATA] Collector Absent-Safe")

    collector = TraceCollector(workflow_id="wf_test")
    collector.record_step_execution(
        step_id="s1",
        purpose="test",
        step_input="square 5",
        execution_result={"status": "success", "result": 25},
        governance_decision="complete",
        retries=0,
        status="COMPLETED"
    )

    entry = collector.steps[0]
    stored_meta = entry.get("data", {}).get("agent_metadata")
    print(f"  Stored metadata: {stored_meta}")
    assert stored_meta is None, f"Expected None, got {stored_meta}"
    print("  PASS: absent agent_metadata is None")
    return True


def test_record_step_module_function_passes_metadata():
    """Module-level record_step must pass agent_metadata to collector."""
    print("\n[TRACE METADATA] Module record_step Passes Metadata")

    from system.orchestrator.trace_collector import create_collector
    collector = create_collector("wf_test")

    meta = {
        "selected_agent": "tool_selection_agent",
        "selected_tool": "square_number",
        "agent_authority": "advisory_only"
    }
    record_step(
        step_id="s1",
        purpose="test",
        step_input="square 5",
        execution_result={"status": "success", "result": 25},
        governance_decision="complete",
        retries=0,
        status="COMPLETED",
        agent_metadata=meta
    )

    assert len(collector.steps) == 1
    entry = collector.steps[0]
    stored_meta = entry.get("data", {}).get("agent_metadata")
    print(f"  Stored metadata: {stored_meta}")
    assert stored_meta == meta, f"Metadata mismatch via module function: {stored_meta}"
    print("  PASS: module record_step passes metadata")
    return True


def test_trace_does_not_modify_execution_result():
    """Trace recording must not modify execution_result dict."""
    print("\n[TRACE METADATA] Trace Does Not Modify execution_result")

    collector = TraceCollector(workflow_id="wf_test")
    exec_res = {"status": "success", "result": 25}
    collector.record_step_execution(
        step_id="s1",
        purpose="test",
        step_input="square 5",
        execution_result=exec_res,
        governance_decision="complete",
        retries=0,
        status="COMPLETED",
        agent_metadata={"selected_agent": "tool_selection_agent"}
    )

    assert "_agent_metadata" not in exec_res, "Trace recording mutated execution_result"
    assert len(exec_res) == 2, f"execution_result has {len(exec_res)} fields"
    print("  PASS: execution_result unchanged by trace recording")
    return True


def test_trace_does_not_modify_agent_metadata():
    """Trace recording must not mutate the provided agent_metadata dict."""
    print("\n[TRACE METADATA] Trace Does Not Mutate agent_metadata")

    collector = TraceCollector(workflow_id="wf_test")
    meta = {"selected_agent": "tool_selection_agent", "selected_tool": "square_number"}
    collector.record_step_execution(
        step_id="s1",
        purpose="test",
        step_input="square 5",
        execution_result={"status": "success", "result": 25},
        governance_decision="complete",
        retries=0,
        status="COMPLETED",
        agent_metadata=meta
    )

    assert len(meta) == 2, f"agent_metadata was mutated to {meta}"
    print("  PASS: agent_metadata dict unchanged")
    return True


def test_trace_failure_does_not_affect_execution():
    """Trace recording failure must be internally contained."""
    print("\n[TRACE METADATA] Trace Failure Isolation")

    # Pass invalid data to force validation failure
    collector = TraceCollector(workflow_id="wf_test")
    collector.record_step_execution(
        step_id=None,  # Invalid: None step_id
        purpose="test",
        step_input="square 5",
        execution_result={"status": "success", "result": 25},
        governance_decision="complete",
        retries=0,
        status="COMPLETED",
        agent_metadata={"selected_agent": "tool_selection_agent"}
    )

    # No exception raised, trace silently discarded
    assert len(collector.steps) == 0, "Invalid trace should be discarded"
    print("  PASS: trace validation failure contained")
    return True


# =============================================================================
# RUN ALL
# =============================================================================
TESTS = [
    test_trace_collector_accepts_agent_metadata,
    test_trace_collector_absent_safe,
    test_record_step_module_function_passes_metadata,
    test_trace_does_not_modify_execution_result,
    test_trace_does_not_modify_agent_metadata,
    test_trace_failure_does_not_affect_execution,
]

if __name__ == "__main__":
    passed = 0
    failed = 0
    for test in TESTS:
        try:
            ok = test()
            if ok:
                passed += 1
            else:
                failed += 1
                print(f"  FAIL: {test.__name__} — returned False")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  FAIL: {test.__name__} — {e}")
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"TRACE AGENT METADATA TEST RESULTS: {passed}/{len(TESTS)} passed, {failed}/{len(TESTS)} failed")
    print(f"{'='*60}")
    if failed > 0:
        sys.exit(1)
