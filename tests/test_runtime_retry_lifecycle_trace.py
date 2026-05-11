"""
DETERMINISTIC RUNTIME TRACE TEST — Retry Lifecycle Investigation

Test Case:
- step_1: Add 2 and 3
- step_2: Divide result of step_1 by 0 (initially), then edit to divide by 5
- step_3: Multiply result of step_2 by 10

Flow:
1. Allow step_2 failure
2. Edit step_2 → divide by 5
3. Retry
4. Capture COMPLETE runtime trace

This test provides deterministic, replayable runtime evidence without GUI dependency.
"""

import json
import sys
import os
import pytest
from typing import Dict, Any, List

# Add parent to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from system.orchestrator.persistence import save_workflow, load_active_workflows
from system.orchestrator.workflow_control import retry_step, edit_step
from system.orchestrator.orchestrator_runtime import run_workflow


def create_test_workflow() -> Dict[str, Any]:
    """Create the test workflow with 3 steps."""
    workflow = {
        "id": "test_retry_lifecycle_001",
        "status": "ACTIVE",
        "steps": [
            {
                "id": "step_1",
                "type": "EXECUTE_API",
                "purpose": "Add 2 and 3",
                "input": "Add 2 and 3",
                "tool_call": "add_numbers 2 3",
                "status": "PENDING",
                "retries": 0,
                "max_retries": 3,
                "depends_on": [],
                "risk": "LOW",
                "importance": "MEDIUM"
            },
            {
                "id": "step_2",
                "type": "EXECUTE_API",
                "purpose": "Divide result of step_1 by 0",
                "input": "Divide result of step_1 by 0",
                "tool_call": None,  # Will be resolved by agent
                "status": "PENDING",
                "retries": 0,
                "max_retries": 3,
                "depends_on": ["step_1"],
                "risk": "LOW",
                "importance": "MEDIUM"
            },
            {
                "id": "step_3",
                "type": "EXECUTE_API",
                "purpose": "Multiply result of step_2 by 10",
                "input": "Multiply result of step_2 by 10",
                "tool_call": None,
                "status": "PENDING",
                "retries": 0,
                "max_retries": 3,
                "depends_on": ["step_2"],
                "risk": "LOW",
                "importance": "MEDIUM"
            }
        ],
        "output": None,
        "error": None
    }
    return workflow


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def extract_runtime_traces(output_lines: List[str]) -> List[Dict]:
    """Extract structured RUNTIME_TRACE logs from output."""
    traces = []
    for line in output_lines:
        if "[RUNTIME_TRACE]" in line:
            try:
                # Extract JSON after the prefix
                json_str = line.split("[RUNTIME_TRACE] ")[1]
                trace = json.loads(json_str)
                traces.append(trace)
            except (IndexError, json.JSONDecodeError):
                pass
    return traces


class TestRetryLifecycleTrace:
    """Full runtime trace test for retry lifecycle investigation."""

    def test_phase_1_initial_execution(self):
        """
        Phase 1: Execute workflow initially.
        Expected: step_1 completes, step_2 fails (divide by zero), step_3 blocked.
        """
        print_section("PHASE 1: INITIAL EXECUTION")

        # Setup: Create and save fresh workflow
        workflow = create_test_workflow()
        save_workflow(workflow)

        print(f"[TEST] Workflow created: {workflow['id']}")
        print(f"[TEST] Step 1 purpose: {workflow['steps'][0]['purpose']}")
        print(f"[TEST] Step 2 purpose: {workflow['steps'][1]['purpose']}")
        print(f"[TEST] Step 3 purpose: {workflow['steps'][2]['purpose']}")

        # Capture stdout during execution
        import io
        old_stdout = sys.stdout
        sys.stdout = captured_output = io.StringIO()

        try:
            # Run workflow
            result = run_workflow(workflow, return_trace=True)
        finally:
            sys.stdout = old_stdout

        # Get captured output
        output = captured_output.getvalue()
        output_lines = output.split('\n')

        # Restore stdout and print output for analysis
        print("\n--- CAPTURED RUNTIME OUTPUT ---")
        for line in output_lines:
            if "[RUNTIME_TRACE]" in line or "[RETRY" in line or "[DEBUG" in line:
                print(line)
        print("--- END CAPTURED OUTPUT ---\n")

        # Extract structured traces
        traces = extract_runtime_traces(output_lines)

        # Analyze results
        print("\n--- PHASE 1 ANALYSIS ---")
        print(f"Workflow result status: {result.get('status')}")

        # Load workflow to check final state
        workflows = load_active_workflows()
        updated_workflow = None
        for wf in workflows:
            if wf.get("id") == workflow["id"]:
                updated_workflow = wf
                break

        if updated_workflow:
            for step in updated_workflow.get("steps", []):
                print(f"Step {step['id']}: status={step.get('status')}, "
                      f"retries={step.get('retries', 0)}, "
                      f"execution_result={step.get('execution_result')}")

        # Assertions for Phase 1
        step_2 = updated_workflow["steps"][1] if updated_workflow else None
        if step_2:
            # Step 2 should have failed or be blocked
            assert step_2["status"] in ["FAILED", "BLOCKED"], \
                f"Step 2 should be FAILED or BLOCKED, got {step_2['status']}"
            print("\n[PHASE 1 COMPLETE] Step 2 is in failed/blocked state as expected")

        # Store workflow ID for next phase
        self.__class__._workflow_id = workflow["id"]
        self.__class__._traces_phase_1 = traces

    def test_phase_2_edit_step(self):
        """
        Phase 2: Edit step_2 to divide by 5 instead of 0.
        """
        print_section("PHASE 2: EDIT STEP")

        workflow_id = self.__class__._workflow_id

        # Edit step_2
        print(f"[TEST] Editing step_2 in workflow {workflow_id}")
        edit_result = edit_step(
            workflow_id=workflow_id,
            step_id="step_2",
            updates={
                "purpose": "Divide result of step_1 by 5",
                "input": "Divide result of step_1 by 5"
            }
        )

        print(f"[TEST] Edit result: {edit_result}")

        # Load workflow and verify edit
        workflows = load_active_workflows()
        updated_workflow = None
        for wf in workflows:
            if wf.get("id") == workflow_id:
                updated_workflow = wf
                break

        assert updated_workflow is not None, "Workflow not found after edit"

        step_2 = updated_workflow["steps"][1]
        print(f"[TEST] Step 2 after edit: purpose={step_2.get('purpose')}, "
              f"input={step_2.get('input')}")

        # Verify edit was applied
        assert step_2["purpose"] == "Divide result of step_1 by 5", \
            f"Purpose not updated: {step_2['purpose']}"
        assert step_2["input"] == "Divide result of step_1 by 5", \
            f"Input not updated: {step_2['input']}"

        print("\n[PHASE 2 COMPLETE] Step 2 edited successfully")

    def test_phase_3_retry_execution(self):
        """
        Phase 3: Retry step_2 and continue workflow.
        Capture complete runtime trace.
        """
        print_section("PHASE 3: RETRY EXECUTION")

        workflow_id = self.__class__._workflow_id

        # Trigger retry
        print(f"[TEST] Retrying step_2 in workflow {workflow_id}")
        retry_result = retry_step(workflow_id=workflow_id, step_id="step_2")
        print(f"[TEST] Retry result: {retry_result}")

        # Load workflow to check state after retry
        workflows = load_active_workflows()
        workflow = None
        for wf in workflows:
            if wf.get("id") == workflow_id:
                workflow = wf
                break

        print("\n[TEST] Workflow state after retry_step:")
        for step in workflow.get("steps", []):
            print(f"  {step['id']}: status={step.get('status')}, retries={step.get('retries', 0)}")

        # Capture stdout during execution
        import io
        old_stdout = sys.stdout
        sys.stdout = captured_output = io.StringIO()

        try:
            # Re-run workflow with the retried step
            print("\n[TEST] Re-running workflow after retry...")
            result = run_workflow(workflow, return_trace=True)
        finally:
            sys.stdout = old_stdout

        # Get captured output
        output = captured_output.getvalue()
        output_lines = output.split('\n')

        # Print output for analysis
        print("\n--- CAPTURED RUNTIME OUTPUT (RETRY PHASE) ---")
        for line in output_lines:
            if "[RUNTIME_TRACE]" in line or "[RETRY" in line or "[DEBUG" in line:
                print(line)
        print("--- END CAPTURED OUTPUT ---\n")

        # Extract structured traces
        traces = extract_runtime_traces(output_lines)
        self.__class__._traces_phase_3 = traces

        # Analyze results
        print("\n--- PHASE 3 ANALYSIS ---")
        print(f"Workflow result status: {result.get('status')}")

        # Load final workflow state
        workflows = load_active_workflows()
        final_workflow = None
        for wf in workflows:
            if wf.get("id") == workflow_id:
                final_workflow = wf
                break

        if final_workflow:
            print("\n[TEST] Final workflow state:")
            for step in final_workflow.get("steps", []):
                exec_res = step.get("execution_result")
                exec_status = exec_res.get('status') if isinstance(exec_res, dict) else None
                print(f"  {step['id']}: status={step.get('status')}, "
                      f"retries={step.get('retries', 0)}, "
                      f"execution_status={exec_status}")

        # Print trace analysis
        print("\n--- STRUCTURED TRACE ANALYSIS ---")
        self._analyze_traces(traces)

        return final_workflow, traces, result

    def _analyze_traces(self, traces: List[Dict]):
        """Analyze structured traces to determine retry causes."""
        print(f"\nTotal trace events: {len(traces)}")

        # Group by event type
        by_type = {}
        for trace in traces:
            event_type = trace.get("EVENT", "UNKNOWN")
            by_type.setdefault(event_type, []).append(trace)

        print("\nTrace events by type:")
        for event_type, events in sorted(by_type.items()):
            print(f"  {event_type}: {len(events)} events")

        # Analyze governance decisions
        gov_decisions = by_type.get("GOVERNANCE_DECISION", [])
        if gov_decisions:
            print("\n--- GOVERNANCE DECISIONS ---")
            for gd in gov_decisions:
                data = gd.get("data", {})
                print(f"  Step {gd.get('step_id')}: {data.get('decision')} "
                      f"(branch: {data.get('branch')}, reason: {data.get('reason')})")

        # Analyze retry handler
        retry_entries = by_type.get("RETRY_HANDLER_ENTRY", [])
        retry_exits = by_type.get("RETRY_HANDLER_EXIT", [])
        if retry_entries:
            print(f"\n--- RETRY HANDLER ---")
            print(f"  Entries: {len(retry_entries)}")
            print(f"  Exits: {len(retry_exits)}")

        # Analyze validator decisions
        validator_decisions = by_type.get("VALIDATOR_DECISION", [])
        if validator_decisions:
            print(f"\n--- VALIDATOR DECISIONS ---")
            for vd in validator_decisions:
                data = vd.get("data", {})
                print(f"  Step {vd.get('step_id')}: recommendation={data.get('validator_recommendation')}, "
                      f"reason={data.get('validator_reason')}")
                signals = data.get("validator_signals", {})
                if signals:
                    print(f"    constraint_ok={signals.get('constraint_ok')}, "
                          f"constraint_violation={signals.get('constraint_violation')}")

        # Analyze constraint extraction
        constraint_extractions = by_type.get("CONSTRAINT_EXTRACTION_SUCCESS", [])
        if constraint_extractions:
            print(f"\n--- CONSTRAINT EXTRACTIONS ---")
            for ce in constraint_extractions:
                data = ce.get("data", {})
                print(f"  Input: '{data.get('user_input', 'N/A')[:50]}...'")
                print(f"  Extracted: {data.get('extracted_constraints')}")

        # Analyze input mutations
        input_mutations = by_type.get("RETRY_INPUT_MUTATED", [])
        if input_mutations:
            print(f"\n--- RETRY INPUT MUTATIONS ---")
            for im in input_mutations:
                data = im.get("data", {})
                print(f"  Step {im.get('step_id')}:")
                print(f"    Before: {data.get('input_before', 'N/A')[:80]}...")
                print(f"    After: {data.get('input_after', 'N/A')[:80]}...")
                print(f"    Constraint format: {data.get('constraint_format')}")
                print(f"    Constraint violation: {data.get('constraint_violation')}")

    def test_full_lifecycle_report(self):
        """
        Generate comprehensive lifecycle report from all phases.
        """
        print_section("FULL LIFECYCLE REPORT")

        all_traces = []
        if hasattr(self.__class__, '_traces_phase_1'):
            all_traces.extend(self.__class__._traces_phase_1)
        if hasattr(self.__class__, '_traces_phase_3'):
            all_traces.extend(self.__class__._traces_phase_3)

        print(f"\nTotal traces collected: {len(all_traces)}")

        # Key questions answered from traces
        print("\n--- KEY FINDINGS ---")

        # 1. What triggers retry?
        gov_entries = [t for t in all_traces if t.get("EVENT") == "GOVERNANCE_ENTRY"]
        gov_decisions = [t for t in all_traces if t.get("EVENT") == "GOVERNANCE_DECISION"]

        print(f"\n1. GOVERNANCE DECISIONS ({len(gov_decisions)} total):")
        for gd in gov_decisions:
            data = gd.get("data", {})
            step_id = gd.get("step_id", "unknown")
            decision = data.get("decision")
            branch = data.get("branch")
            print(f"   {step_id}: {decision} (branch: {branch})")

        # 2. Validator influence
        validator_exits = [t for t in all_traces if t.get("EVENT") == "VALIDATOR_EXIT"]
        print(f"\n2. VALIDATOR OUTPUTS ({len(validator_exits)} total):")
        for ve in validator_exits:
            data = ve.get("data", {})
            step_id = ve.get("step_id", "unknown")
            rec = data.get("recommendation")
            reason = data.get("reason")
            signals = data.get("signals", {})
            print(f"   {step_id}: {rec} (reason: {reason})")
            if signals.get("constraint_violation"):
                print(f"      constraint_violation: {signals.get('constraint_violation')}")

        # 3. Retry mutations
        mutations = [t for t in all_traces if t.get("EVENT") == "RETRY_INPUT_MUTATED"]
        print(f"\n3. RETRY INPUT MUTATIONS ({len(mutations)} total):")
        for m in mutations:
            data = m.get("data", {})
            step_id = m.get("step_id", "unknown")
            print(f"   {step_id}: format={data.get('constraint_format')}, "
                  f"violation={data.get('constraint_violation')}")

        # 4. Execution results
        post_execs = [t for t in all_traces if t.get("EVENT") == "POST_AGENT_EXECUTION"]
        print(f"\n4. EXECUTION RESULTS ({len(post_execs)} total):")
        for pe in post_execs:
            data = pe.get("data", {})
            step_id = pe.get("step_id", "unknown")
            exec_res = data.get("execution_result", {})
            print(f"   {step_id}: status={exec_res.get('status')}, "
                  f"result={exec_res.get('result')}")

        # Final summary
        print("\n--- SUMMARY ---")
        print("Review the above data to determine:")
        print("- Whether governance returns 'complete' or 'retry'")
        print("- Whether validator signals influence retry")
        print("- Whether constraint violations trigger mutations")
        print("- Whether execution succeeds but is rejected")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
