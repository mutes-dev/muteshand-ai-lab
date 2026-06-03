"""
HARNESS — Execution Path Integrity + Authority Model Enforcement (Phase 1C Subphase 2)

PROVES:
1. ALL execution goes through system_entry (no bypass)
2. Tools are ONLY reachable via system_entry path
3. Validator signals CANNOT force retry (advisory only)
4. Governance is sole decision authority for retry
5. execution_result is final output truth

CONTRACTS ENFORCED:
- ARCHITECTURE_LAW #18: ALL tool execution MUST go through system_entry
- ARCHITECTURE_LAW #19: Orchestrator MUST NOT bypass core pipeline
- ARCHITECTURE_LAW #2A: Validator MUST NOT influence retry decisions
- ARCHITECTURE_LAW #2B: Governance decisions based solely on execution_result
- AUTHORITY_MODEL: execution_result = sole truth, governance = sole decision authority
- CONTROL_MODEL: Signals MUST NOT override execution_result

APPROACH:
- Minimal monkeypatching of system_entry to track calls
- Real execution via execute_from_input and execute_step
- No mocking of full system — only targeted instrumentation
"""

import sys
import os
import json
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest
from unittest.mock import patch, MagicMock

from system.entry.system_entry import system_entry
from system.orchestrator.step_executor import execute_step
from system.orchestrator.governance import decide_next_action, resolve_decision
from system.orchestrator import trace_collector


# ============================================================
# HELPERS
# ============================================================

def _make_step(step_id, tool_call=None, risk="LOW", importance="MEDIUM", status="PENDING"):
    """Create a minimal contract-compliant step."""
    return {
        "id": step_id,
        "name": f"test_step_{step_id}",
        "type": "EXECUTE_API",
        "purpose": f"Test step {step_id}",
        "tool_call": tool_call or f"add_numbers 1 2",
        "expected_outcome": "Execution completed",
        "risk": risk,
        "importance": importance,
        "resource_targets": [],
        "agent": "default_agent",
        "status": status,
        "retries": 0,
        "max_retries": 2,
        "input": f"test input {step_id}",
    }


def _make_workflow(steps):
    """Create a minimal contract-compliant workflow."""
    return {
        "id": "harness_test_wf",
        "name": "harness_test",
        "status": "ACTIVE",
        "steps": steps,
    }


# ============================================================
# TEST 1 — ORCHESTRATOR MUST USE system_entry
# ============================================================

class TestOrchestratorUsesSystemEntry:
    """
    ARCHITECTURE_LAW #18: ALL tool execution MUST go through system_entry.
    ARCHITECTURE_LAW #19: Orchestrator MUST NOT bypass core pipeline.

    Approach:
    - Monkeypatch system_entry to track calls
    - Execute a step via execute_step (orchestrator path)
    - Assert system_entry WAS called
    - Assert execution_result originates from system_entry
    """

    def test_execute_step_calls_system_entry(self):
        """Prove: execute_step → agent_executor → system_entry."""
        call_log = []
        original_system_entry = system_entry

        def tracking_system_entry(input_text):
            call_log.append({"input": input_text})
            return original_system_entry(input_text)

        step = _make_step("s1", tool_call="add_numbers 1 2")
        workflow = _make_workflow([step])

        # Initialize trace collector (required by execution path)
        trace_collector.create_collector("harness_test")

        with patch("system.entry.system_entry.system_entry", tracking_system_entry):
            with patch("system.orchestrator.agents.tool_selection_agent.system_entry", tracking_system_entry):
                result = execute_step(step, workflow)

        execution_result = result.get("execution_result")

        print("\n=== TEST 1 — ORCHESTRATOR USES system_entry ===")
        print(f"  system_entry calls: {len(call_log)}")
        print(f"  execution_result: {execution_result}")

        assert len(call_log) >= 1, (
            "FAIL: system_entry was NOT called during step execution. "
            "This is an ARCHITECTURE_LAW #18 violation — execution bypassed system_entry."
        )

        # Verify execution_result came from system_entry
        assert execution_result is not None, "FAIL: No execution_result returned"
        assert isinstance(execution_result, dict), "FAIL: execution_result is not a dict"
        assert "status" in execution_result, "FAIL: execution_result missing 'status'"

        # Verify the call log shows a valid tool call was passed
        assert any("add_numbers" in c["input"] for c in call_log), (
            "FAIL: system_entry not called with expected tool — execution may have bypassed pipeline"
        )

        print(f"  call_log[0]: {call_log[0]}")
        print("  ✓ system_entry called during step execution — PASS")
        print("  ✓ execution_result originates from system_entry — PASS")

    def test_execute_step_result_matches_system_entry_output(self):
        """Prove: execution_result IS the system_entry output (not fabricated)."""
        system_entry_outputs = []
        original_system_entry = system_entry

        def capturing_system_entry(input_text):
            result = original_system_entry(input_text)
            system_entry_outputs.append(result)
            return result

        step = _make_step("s1", tool_call="add_numbers 3 4")
        workflow = _make_workflow([step])

        trace_collector.create_collector("harness_test")

        with patch("system.orchestrator.agents.tool_selection_agent.system_entry", capturing_system_entry):
            result = execute_step(step, workflow)

        execution_result = result.get("execution_result")

        print("\n=== TEST 1B — RESULT MATCHES system_entry OUTPUT ===")
        print(f"  system_entry output: {system_entry_outputs}")
        print(f"  execution_result:    {execution_result}")

        assert len(system_entry_outputs) >= 1, "FAIL: system_entry not called"

        # The execution_result should match what system_entry returned
        matched = any(
            se_out == execution_result
            for se_out in system_entry_outputs
        )
        assert matched, (
            f"FAIL: execution_result does not match any system_entry output. "
            f"system_entry returned: {system_entry_outputs}, "
            f"but execution_result is: {execution_result}"
        )

        print("  ✓ execution_result matches system_entry output — PASS")


# ============================================================
# TEST 2 — NO DIRECT TOOL EXECUTION
# ============================================================

class TestNoDirectToolExecution:
    """
    ARCHITECTURE_LAW #18: ALL tool execution MUST go through system_entry.
    ARCHITECTURE_LAW #20: Agents MUST NOT call tool functions directly.

    Approach:
    - Monkeypatch the execution layer (executor.execute) to track calls
    - Also monkeypatch system_entry to track its calls
    - Run step execution
    - Assert execution layer is ONLY reached via system_entry
    """

    def test_tool_only_reached_via_system_entry(self):
        """Prove: execute() is only called when system_entry is in the call stack."""
        execution_calls = []
        system_entry_active = threading.local()
        system_entry_active.in_call = False
        original_execute = None

        # Import the real execute function
        from system.execution.executor import execute as real_execute
        original_execute = real_execute

        def tracking_execute(plan, registry):
            execution_calls.append({
                "via_system_entry": getattr(system_entry_active, 'in_call', False),
                "plan": plan,
            })
            return original_execute(plan, registry)

        original_system_entry = system_entry

        def tracking_system_entry(input_text):
            system_entry_active.in_call = True
            try:
                return original_system_entry(input_text)
            finally:
                system_entry_active.in_call = False

        step = _make_step("s1", tool_call="add_numbers 5 6")
        workflow = _make_workflow([step])

        trace_collector.create_collector("harness_test")

        with patch("system.execution.executor.execute", tracking_execute):
            with patch("system.entry.system_entry.execute", tracking_execute):
                with patch("system.orchestrator.agents.tool_selection_agent.system_entry", tracking_system_entry):
                    result = execute_step(step, workflow)

        print("\n=== TEST 2 — NO DIRECT TOOL EXECUTION ===")
        print(f"  execution layer calls: {len(execution_calls)}")

        assert len(execution_calls) >= 1, "FAIL: Execution layer was never called"

        for i, call in enumerate(execution_calls):
            print(f"  call[{i}]: via_system_entry={call['via_system_entry']}")
            assert call["via_system_entry"] is True, (
                f"FAIL: Execution layer call #{i} was NOT via system_entry. "
                f"This is an ARCHITECTURE_LAW #18 violation — direct tool execution detected."
            )

        print("  ✓ All tool execution routed via system_entry — PASS")


# ============================================================
# TEST 3 — VALIDATOR CANNOT FORCE RETRY
# ============================================================

class TestValidatorCannotForceRetry:
    """
    ARCHITECTURE_LAW #2A: Validator MUST NOT influence retry decisions.
    CONTROL_MODEL RULE 3: Validator MUST NOT directly trigger retry.

    Approach:
    - Simulate a successful execution_result
    - Provide a validator signal saying "retry"
    - Assert governance does NOT retry (completes instead)
    """

    def test_validator_retry_signal_ignored_on_success(self):
        """Prove: validator saying 'retry' does NOT cause retry when execution succeeded."""
        step = _make_step("s1")
        workflow = _make_workflow([step])

        # Successful execution result
        execution_result = {"status": "success", "result": 42}

        # Validator says retry (advisory only)
        validator_output = {
            "recommendation": "retry",
            "reason": "output_mismatch",
            "signals": {"semantic_match": False},
        }

        # Governance decision should be based on execution_result ONLY
        decision = decide_next_action(
            validator_output=validator_output,
            execution_result=execution_result,
            step=step,
            context={"workflow": workflow},
        )

        print("\n=== TEST 3 — VALIDATOR CANNOT FORCE RETRY ===")
        print(f"  execution_result: {execution_result['status']}")
        print(f"  validator_output: {validator_output['recommendation']}")
        print(f"  governance decision: {decision}")

        assert decision == "complete", (
            f"FAIL: Governance decision is '{decision}' but should be 'complete'. "
            f"Validator signal 'retry' overrode execution_result success. "
            f"This violates ARCHITECTURE_LAW #2A — validator influenced retry."
        )

        print("  ✓ Validator 'retry' signal ignored — governance completed — PASS")

    def test_validator_retry_signal_ignored_repeatedly(self):
        """Prove: validator 'retry' is ignored across multiple calls."""
        for i in range(3):
            step = _make_step(f"s{i}")
            step["purpose_met"] = True

            execution_result = {"status": "success", "result": f"result_{i}"}
            validator_output = {"recommendation": "retry", "reason": f"mismatch_{i}"}

            decision = decide_next_action(
                validator_output=validator_output,
                execution_result=execution_result,
                step=step,
                context={},
            )

            assert decision == "complete", (
                f"FAIL: Round {i} — governance returned '{decision}' instead of 'complete'"
            )

        print("\n=== TEST 3B — VALIDATOR RETRY IGNORED REPEATEDLY ===")
        print("  ✓ 3/3 rounds — validator retry ignored — PASS")


# ============================================================
# TEST 4 — GOVERNANCE CONTROLS RETRY
# ============================================================

class TestGovernanceControlsRetry:
    """
    ARCHITECTURE_LAW #2B: Governance decisions based solely on execution_result.
    CONTROL_MODEL RULE 1: execution failure → governance decides retry.

    Approach:
    - Simulate a FAILED execution_result
    - Assert governance returns 'retry' (retries remaining)
    - Simulate exhausted retries → governance returns 'escalate'
    """

    def test_governance_retries_on_failure(self):
        """Prove: governance returns 'retry' on execution failure with retries remaining."""
        step = _make_step("s1", risk="MEDIUM")
        step["retries"] = 0

        execution_result = {"status": "failure", "reason": "tool_error"}

        decision = decide_next_action(
            validator_output={},
            execution_result=execution_result,
            step=step,
            context={},
        )

        print("\n=== TEST 4A — GOVERNANCE RETRIES ON FAILURE ===")
        print(f"  execution_result: failure")
        print(f"  retries: 0")
        print(f"  decision: {decision}")

        assert decision == "retry", (
            f"FAIL: Governance returned '{decision}' instead of 'retry'. "
            f"Governance MUST retry on failure with retries remaining."
        )

        print("  ✓ Governance retries on execution failure — PASS")

    def test_governance_escalates_on_max_retries(self):
        """Prove: governance escalates when max retries reached."""
        step = _make_step("s1", risk="HIGH")
        step["retries"] = 10  # Well above any risk-based limit

        execution_result = {"status": "failure", "reason": "persistent_error"}

        decision = decide_next_action(
            validator_output={},
            execution_result=execution_result,
            step=step,
            context={},
        )

        print("\n=== TEST 4B — GOVERNANCE ESCALATES ON MAX RETRIES ===")
        print(f"  retries: 10")
        print(f"  decision: {decision}")

        assert decision == "escalate", (
            f"FAIL: Governance returned '{decision}' instead of 'escalate'. "
            f"Max retries exceeded — MUST escalate per CONTROL_MODEL RULE 7."
        )

        print("  ✓ Governance escalates when max retries exhausted — PASS")

    def test_no_retry_without_governance(self):
        """Prove: retry ONLY happens via governance, not via validator alone."""
        step = _make_step("s1")
        step["purpose_met"] = True

        # Execution succeeded
        execution_result = {"status": "success", "result": "ok"}

        # Validator says retry — but governance should override
        validator_output = {"recommendation": "retry", "reason": "mismatch"}

        decision = decide_next_action(
            validator_output=validator_output,
            execution_result=execution_result,
            step=step,
            context={},
        )

        assert decision != "retry", (
            f"FAIL: Governance returned 'retry' despite successful execution. "
            f"Retry MUST only originate from governance on execution failure."
        )

        print("\n=== TEST 4C — NO RETRY WITHOUT GOVERNANCE ===")
        print(f"  execution=success, validator=retry, governance={decision}")
        print("  ✓ No retry without governance decision — PASS")


# ============================================================
# TEST 5 — EXECUTION RESULT IS FINAL OUTPUT
# ============================================================

class TestExecutionResultIsFinalOutput:
    """
    AUTHORITY_MODEL: execution_result is sole truth.
    ARCHITECTURE_LAW: Final output MUST originate from execution_result.

    Approach:
    - Call resolve_decision with execution_result and validator signals
    - Assert output == execution_result (not validator or formatted)
    """

    def test_resolve_decision_returns_execution_result(self):
        """Prove: resolve_decision returns execution_result unchanged."""
        execution_result = {"status": "success", "result": 42}
        validator_output = {"recommendation": "retry", "reason": "mismatch"}

        output = resolve_decision(
            validator_output=validator_output,
            execution_result=execution_result,
            context={"last_step": None},
        )

        print("\n=== TEST 5A — EXECUTION RESULT IS FINAL OUTPUT ===")
        print(f"  execution_result: {execution_result}")
        print(f"  validator_output: {validator_output}")
        print(f"  resolve_decision output: {output}")

        assert output == execution_result, (
            f"FAIL: resolve_decision returned {output} instead of {execution_result}. "
            f"execution_result MUST be the sole truth — AUTHORITY_MODEL violation."
        )

        print("  ✓ resolve_decision returns execution_result — PASS")

    def test_validator_signal_does_not_alter_output(self):
        """Prove: validator signals have zero effect on final output."""
        execution_result = {"status": "success", "result": "correct_value"}

        # Test with various validator signals — none should change output
        validator_variants = [
            {"recommendation": "retry", "reason": "mismatch"},
            {"recommendation": "escalate", "reason": "critical"},
            {"recommendation": "accept", "reason": "ok"},
            {},
            None,
        ]

        print("\n=== TEST 5B — VALIDATOR DOES NOT ALTER OUTPUT ===")
        for i, val in enumerate(validator_variants):
            output = resolve_decision(
                validator_output=val or {},
                execution_result=execution_result,
                context={"last_step": None},
            )

            assert output == execution_result, (
                f"FAIL: Variant {i} — validator {val} altered output to {output}"
            )
            print(f"  variant {i}: validator={val} → output unchanged ✓")

        print("  ✓ No validator variant alters final output — PASS")

    def test_execution_result_failure_preserved(self):
        """Prove: failure execution_result is returned as-is (no correction)."""
        execution_result = {"status": "failure", "reason": "tool_broken"}

        output = resolve_decision(
            validator_output={},
            execution_result=execution_result,
            context={},
        )

        print("\n=== TEST 5C — FAILURE EXECUTION_RESULT PRESERVED ===")
        print(f"  execution_result: {execution_result}")
        print(f"  resolve_decision: {output}")

        assert output == execution_result, (
            f"FAIL: Failure result was altered. Got {output} instead of {execution_result}."
        )

        print("  ✓ Failure execution_result preserved — PASS")

    def test_execution_result_with_real_tool(self):
        """Prove: end-to-end — real tool execution_result is final output."""
        step = _make_step("s1", tool_call="add_numbers 10 20")
        workflow = _make_workflow([step])

        trace_collector.create_collector("harness_test")

        result = execute_step(step, workflow)
        execution_result = result.get("execution_result")

        print("\n=== TEST 5D — REAL TOOL EXECUTION RESULT ===")
        print(f"  execution_result: {execution_result}")

        assert execution_result is not None, "FAIL: No execution_result"
        assert execution_result.get("status") == "success", (
            f"FAIL: Expected success, got {execution_result}"
        )
        assert execution_result.get("result") == 30, (
            f"FAIL: Expected 30, got {execution_result.get('result')}"
        )

        # Now verify resolve_decision preserves this
        final = resolve_decision(
            validator_output={},
            execution_result=execution_result,
            context={},
        )
        assert final == execution_result, "FAIL: resolve_decision altered real execution_result"

        print("  ✓ Real tool result (add 10 20 = 30) preserved as final output — PASS")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
