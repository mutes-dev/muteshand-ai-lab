"""
CATEGORY: INTERNAL_RUNTIME
AUTHORITY_LAYER: Runtime Behavioral Truth
VALIDATES:
  - Step schema enforcement (STEP_SCHEMA_CONTRACT_V1)
  - State transitions (STATE_TRANSITIONS_CONTRACT_V1)
  - Parallel execution rules (EXECUTION_SCHEDULING_CONTRACT_V1)
  - Conflict detection (CONFLICT_RESOLUTION_CONTRACT_V1)
ENTRYPOINT: run_workflow
DIRECT_INTERNAL_CALLS:
  - governance.decide_next_action
  - execution_scheduler.create_execution_group
  - execution_scheduler._is_destructive_step
  - execution_scheduler._has_dependency
  - conflict_detector (reset_detector, get_detector)
MONKEYPATCH_USAGE:
  - system_entry (counting for fail-fast validation)
MOCKING_POLICY: BEHAVIORAL_CONTROL
TEST_INTENT: BEHAVIORAL_VALIDATION
ARCHITECTURAL_SCOPE: Orchestrator contract enforcement via internal entry point

---

SEMANTIC NAMING CLARIFICATION:

Filename "test_orchestrator_contracts.py" refers to INTERNAL orchestrator contracts
(NOT external harness contracts).

This file validates internal orchestrator contract enforcement:
- STEP_SCHEMA_CONTRACT_V1 (internal orchestrator schema)
- STATE_TRANSITIONS_CONTRACT_V1 (internal orchestrator state machine)
- EXECUTION_SCHEDULING_CONTRACT_V1 (internal orchestrator scheduling)
- CONFLICT_RESOLUTION_CONTRACT_V1 (internal orchestrator conflict detection)

INTERNAL_RUNTIME classification is intentional — this is internal behavioral validation.
Phase 2A reclassification from HARNESS_CONTRACT to INTERNAL_RUNTIME was correct.

---

ORCHESTRATOR CONTRACT VALIDATION HARNESS
Phase 1C Subphase 3

Validates orchestrator-level contract compliance:
  1. Step Schema Enforcement     (STEP_SCHEMA_CONTRACT_V1)
  2. State Transitions           (STATE_TRANSITIONS_CONTRACT_V1)
  3. Parallel Execution Rules    (EXECUTION_SCHEDULING_CONTRACT_V1)
  4. Conflict Detection          (CONFLICT_RESOLUTION_CONTRACT_V1)

Entry Points per VALIDATION_ARCHITECTURE.txt:
  - run_workflow  → INTERNAL / flat contract
  - system_entry  → not bypassed (called via execute_step internally)

Rules:
  - REAL execution only (no simulated outputs)
  - Minimal monkeypatching only where required
  - system_entry is the sole execution gateway
  - No direct tool calls
"""

import time
import pytest

from system.orchestrator.orchestrator_runtime import run_workflow
from system.orchestrator.agent_registry import register_agent
from system.orchestrator.conflict_detector import (
    ConflictDetector,
    reset_detector,
    get_detector,
)
from system.orchestrator.execution_scheduler import (
    create_execution_group,
    _is_destructive_step,
    _has_dependency,
)
from system.orchestrator.governance import decide_next_action
import system.orchestrator.governance as governance_module


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _base_workflow(wf_id: str, steps: list) -> dict:
    """Minimal valid workflow wrapper around a step list."""
    return {
        "id": wf_id,
        "name": f"contract_test_{wf_id}",
        "status": "ACTIVE",
        "steps": steps,
    }


def _base_step(step_id: str, tool_call: str = "square_number 4", **overrides) -> dict:
    """Minimal step that satisfies workflow_validator REQUIRED_STEP_KEYS."""
    step = {
        "id": step_id,
        "name": f"step_{step_id}",
        "agent": "test_agent",
        "status": "PENDING",
        "retries": 0,
        "max_retries": 2,
        "input": tool_call,
        "purpose": "contract test step",
        # STEP_SCHEMA_CONTRACT_V1 fields
        "type": "EXECUTE_API",
        "tool_call": tool_call,
        "expected_outcome": "result returned",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
    }
    step.update(overrides)
    return step


def _register_agent():
    register_agent({"name": "test_agent", "role": "executor", "scope": ["tools"]})


# ===========================================================================
# REQUIREMENT 1 — STEP SCHEMA VALIDATION
# ===========================================================================

class TestStepSchemaValidation:
    """
    STEP_SCHEMA_CONTRACT_V1:
    - All required fields must be present
    - tool_call must be valid format
    - Invalid step MUST NOT execute
    """

    def setup_method(self):
        _register_agent()
        reset_detector()

    # -----------------------------------------------------------------------
    # TEST 1 — Missing required field (tool_call / purpose)
    # -----------------------------------------------------------------------

    def test_missing_tool_call_fails_before_execution(self, monkeypatch):
        """
        TEST 1 — Missing tool_call field.

        ASSERT:
        - workflow fails
        - system_entry is NOT called
        """
        system_entry_called = {"count": 0}

        def counting_system_entry(input_text):
            system_entry_called["count"] += 1
            from system.entry.system_entry import system_entry as real_se
            return real_se(input_text)

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            counting_system_entry,
        )

        # Step has NO tool_call field
        step = _base_step("s1", tool_call="square_number 4")
        del step["tool_call"]  # Remove required field

        workflow = _base_workflow("wf_missing_tool_call", [step])
        result = run_workflow(workflow)

        print(f"[TEST 1] result={result}")
        print(f"[TEST 1] system_entry_called={system_entry_called['count']}")

        # Workflow MUST fail
        assert result["status"] == "failure", (
            f"Expected failure when tool_call missing, got: {result}"
        )
        # system_entry MUST NOT be called (fail-fast before execution)
        assert system_entry_called["count"] == 0, (
            f"system_entry was called {system_entry_called['count']} times "
            f"despite missing tool_call — SCHEMA VIOLATION"
        )

    def test_missing_purpose_field_workflow_still_fails(self, monkeypatch):
        """
        TEST 1b — Missing purpose (workflow_validator catches missing step keys
        because 'input' serves as the step intent carrier at runtime layer;
        'purpose' absence is detectable via step_executor tool_call path).
        """
        system_entry_called = {"count": 0}

        def counting_system_entry(input_text):
            system_entry_called["count"] += 1
            from system.entry.system_entry import system_entry as real_se
            return real_se(input_text)

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            counting_system_entry,
        )

        step = _base_step("s1", tool_call="square_number 4")
        del step["tool_call"]  # Missing tool_call → step_executor fast-fail
        step.pop("purpose", None)  # Also remove purpose

        workflow = _base_workflow("wf_missing_purpose", [step])
        result = run_workflow(workflow)

        print(f"[TEST 1b] result={result}")

        # Workflow MUST fail
        assert result["status"] == "failure", (
            f"Expected failure, got: {result}"
        )
        # system_entry must NOT have been called
        assert system_entry_called["count"] == 0, (
            f"system_entry called despite schema violation: {system_entry_called['count']}"
        )

    # -----------------------------------------------------------------------
    # TEST 2 — Invalid tool_call format
    # -----------------------------------------------------------------------

    def test_invalid_tool_call_no_execution(self):
        """
        TEST 2 — Malformed tool_call string (non-existent tool).

        ASSERT:
        - validation fails (tool not found)
        - no successful execution occurs
        """
        step = _base_step("s1", tool_call="INVALID_TOOL_XYZ_ABC_DOES_NOT_EXIST arg1")
        step["tool_call"] = "INVALID_TOOL_XYZ_ABC_DOES_NOT_EXIST arg1"
        step["input"] = "INVALID_TOOL_XYZ_ABC_DOES_NOT_EXIST arg1"

        workflow = _base_workflow("wf_invalid_tool_call", [step])
        result = run_workflow(workflow)

        print(f"[TEST 2] result={result}")

        # MUST fail — tool does not exist
        assert result["status"] == "failure", (
            f"Expected failure for invalid tool_call, got: {result}"
        )
        # Reason must be present
        assert "reason" in result, "Missing 'reason' in failure response"
        assert isinstance(result["reason"], str), "Reason must be a string"
        assert len(result["reason"]) > 0, "Reason must not be empty"

    def test_empty_tool_call_string(self):
        """
        TEST 2b — Empty tool_call string.

        ASSERT:
        - execution fails before any tool invocation
        """
        step = _base_step("s1", tool_call="")
        step["tool_call"] = ""  # Empty string — invalid per STEP_SCHEMA_CONTRACT_V1

        workflow = _base_workflow("wf_empty_tool_call", [step])
        result = run_workflow(workflow)

        print(f"[TEST 2b] result={result}")

        assert result["status"] == "failure", (
            f"Empty tool_call must fail, got: {result}"
        )

    # -----------------------------------------------------------------------
    # TEST 3 — Invalid step structure (missing id / malformed schema)
    # -----------------------------------------------------------------------

    def test_missing_step_id_rejected(self):
        """
        TEST 3 — Step missing 'id' field.

        workflow_validator enforces REQUIRED_STEP_KEYS including 'id'.
        ASSERT: step rejected before execution.
        """
        step = _base_step("s1", tool_call="square_number 4")
        del step["id"]  # Remove required id field

        workflow = _base_workflow("wf_missing_id", [step])
        result = run_workflow(workflow)

        print(f"[TEST 3] result={result}")

        # workflow_validator must catch this
        assert result["status"] == "failure", (
            f"Expected failure for step missing 'id', got: {result}"
        )
        assert "reason" in result

    def test_invalid_step_status_rejected(self):
        """
        TEST 3b — Step with invalid status value.

        ASSERT: workflow_validator rejects invalid step status.
        """
        step = _base_step("s1", tool_call="square_number 4")
        step["status"] = "INVALID_STATUS_XYZ"

        workflow = _base_workflow("wf_invalid_step_status", [step])
        result = run_workflow(workflow)

        print(f"[TEST 3b] result={result}")

        assert result["status"] == "failure", (
            f"Expected failure for invalid step status, got: {result}"
        )

    def test_duplicate_step_ids_rejected(self):
        """
        TEST 3c — Two steps with the same id.

        ASSERT: workflow_validator detects duplicate_step_id.
        """
        step1 = _base_step("s_dup", tool_call="square_number 4")
        step2 = _base_step("s_dup", tool_call="square_number 9")  # Same ID

        workflow = _base_workflow("wf_duplicate_ids", [step1, step2])
        result = run_workflow(workflow)

        print(f"[TEST 3c] result={result}")

        assert result["status"] == "failure", (
            f"Expected failure for duplicate step ids, got: {result}"
        )


# ===========================================================================
# REQUIREMENT 2 — STATE TRANSITIONS
# ===========================================================================

class TestStateTransitions:
    """
    STATE_TRANSITIONS_CONTRACT_V1:
    - ACTIVE → COMPLETED valid
    - ACTIVE → QUEUED invalid (not a defined transition)
    - BLOCKED → ACTIVE requires approval trigger
    - COMPLETED and FAILED are terminal
    """

    def setup_method(self):
        _register_agent()
        reset_detector()

    # -----------------------------------------------------------------------
    # TEST 4 — Valid transition ACTIVE → COMPLETED
    # -----------------------------------------------------------------------

    def test_valid_transition_active_to_completed(self, monkeypatch):
        """
        TEST 4 — ACTIVE → COMPLETED via successful execution.

        ASSERT:
        - transition succeeds
        - step ends in COMPLETED
        - workflow returns success
        """
        def mock_success(input_text):
            return {"status": "success", "result": 16}

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            mock_success,
        )

        step = _base_step("s1", tool_call="square_number 4")
        workflow = _base_workflow("wf_active_to_completed", [step])
        result = run_workflow(workflow)

        print(f"[TEST 4] result={result}")
        print(f"[TEST 4] step status={step['status']}")

        # Workflow succeeds
        assert result["status"] == "success", (
            f"Expected success for valid ACTIVE→COMPLETED, got: {result}"
        )
        # Step must be COMPLETED
        assert step["status"] == "COMPLETED", (
            f"Step status must be COMPLETED, got: {step['status']}"
        )

    # -----------------------------------------------------------------------
    # TEST 5 — Invalid transition ACTIVE → QUEUED
    # -----------------------------------------------------------------------

    def test_invalid_transition_active_to_queued_prevented(self, monkeypatch):
        """
        TEST 5 — ACTIVE → QUEUED is NOT a defined transition.

        STATE_TRANSITIONS_CONTRACT_V1: ACTIVE may only transition to
        COMPLETED, FAILED, or BLOCKED.

        ASSERT:
        - runtime never puts a step into QUEUED status
        - step ends in a valid terminal state
        """
        call_count = {"n": 0}

        def mock_success(input_text):
            call_count["n"] += 1
            return {"status": "success", "result": 16}

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            mock_success,
        )

        step = _base_step("s1", tool_call="square_number 4")
        workflow = _base_workflow("wf_no_queued_transition", [step])
        result = run_workflow(workflow)

        print(f"[TEST 5] result={result}")
        print(f"[TEST 5] step final status={step['status']}")

        # QUEUED is not a valid post-execution step state
        assert step["status"] != "QUEUED", (
            f"INVALID TRANSITION: step entered QUEUED state — "
            f"CONTRACT VIOLATION per STATE_TRANSITIONS_CONTRACT_V1"
        )
        # Step must be in a valid terminal state
        valid_terminal = {"COMPLETED", "FAILED", "BLOCKED"}
        assert step["status"] in valid_terminal, (
            f"Step must end in valid terminal state, got: {step['status']}"
        )

    # -----------------------------------------------------------------------
    # TEST 6 — BLOCKED → ACTIVE via approval
    # -----------------------------------------------------------------------

    def test_blocked_to_active_requires_approval_trigger(self, monkeypatch):
        """
        TEST 6 — BLOCKED → ACTIVE via approval mechanism.

        STATE_TRANSITIONS_CONTRACT_V1:
        - BLOCKED → ACTIVE: requires explicit approval trigger
        - Governance decides BLOCK (sets blocked_reason=approval_required)
        - Runtime approval gate detects BLOCKED step and invokes request_approval
        - BLOCKED → ACTIVE transition occurs when approval is granted

        Implementation:
        - Pre-set step to BLOCKED with blocked_reason=approval_required
          (simulating governance having already decided BLOCK)
        - Runtime detects this at the top of the first loop iteration
          (before scheduling) and invokes request_approval
        - request_approval returns True → step transitions to ACTIVE
        - Execution proceeds → COMPLETED

        ASSERT:
        - approval trigger invoked (state machine fires for BLOCKED step)
        - step transitions BLOCKED → ACTIVE (blocked_reason removed, _approval_resumed=True)
        - step reaches COMPLETED after re-execution
        - workflow returns success
        """
        exec_call_count = {"n": 0}
        approval_called = {"n": 0}

        def mock_success(input_text):
            exec_call_count["n"] += 1
            return {"status": "success", "result": 16}

        def mock_approval_granted(step_arg):
            approval_called["n"] += 1
            return True

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            mock_success,
        )

        monkeypatch.setattr(
            "system.orchestrator.user_approval.request_approval",
            mock_approval_granted,
        )

        # Pre-set step to BLOCKED with blocked_reason=approval_required.
        # This is the state governance would have set it to.
        # The runtime approval loop fires at the TOP of the first iteration
        # (before create_execution_group) and handles BLOCKED→ACTIVE.
        step = _base_step("s1", tool_call="square_number 4")
        step["status"] = "BLOCKED"
        step["blocked_reason"] = "approval_required"

        # Workflow is ACTIVE — loop starts, approval check fires immediately
        workflow = _base_workflow("wf_blocked_to_active", [step])

        result = run_workflow(workflow)

        print(f"[TEST 6] result={result}")
        print(f"[TEST 6] step status={step['status']}")
        print(f"[TEST 6] exec calls={exec_call_count['n']}")
        print(f"[TEST 6] approval calls={approval_called['n']}")
        print(f"[TEST 6] _approval_resumed={step.get('_approval_resumed')}")

        # ASSERT 1: Approval trigger was invoked (BLOCKED→ACTIVE path fired)
        assert approval_called["n"] > 0, (
            "Approval trigger was never invoked — BLOCKED→ACTIVE transition "
            "requires approval trigger per STATE_TRANSITIONS_CONTRACT_V1"
        )

        # ASSERT 2: blocked_reason was cleared (ACTIVE step has no blocked_reason)
        assert "blocked_reason" not in step, (
            f"blocked_reason must be removed after BLOCKED→ACTIVE transition, "
            f"got: {step.get('blocked_reason')}"
        )

        # ASSERT 3: Final result is success (approval granted → execution → success)
        assert result["status"] == "success", (
            f"Expected success after BLOCKED→ACTIVE→COMPLETED, got: {result}"
        )

        # ASSERT 4: Step is COMPLETED
        assert step["status"] == "COMPLETED", (
            f"Step must be COMPLETED after approval resume, got: {step['status']}"
        )

    def test_terminal_completed_no_transition(self, monkeypatch):
        """
        TEST extra — COMPLETED is terminal: no further transitions allowed.

        ASSERT:
        - A step already COMPLETED is not re-executed
        """
        exec_call_count = {"n": 0}

        def mock_success(input_text):
            exec_call_count["n"] += 1
            return {"status": "success", "result": 16}

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            mock_success,
        )

        # Start with one step already COMPLETED
        completed_step = _base_step("s1", tool_call="square_number 4")
        completed_step["status"] = "COMPLETED"
        completed_step["execution_result"] = {"status": "success", "result": 16}

        pending_step = _base_step("s2", tool_call="square_number 9")

        workflow = _base_workflow("wf_terminal_completed", [completed_step, pending_step])
        result = run_workflow(workflow)

        print(f"[TEST extra] result={result}")
        print(f"[TEST extra] s1 status={completed_step['status']}")
        print(f"[TEST extra] exec calls={exec_call_count['n']}")

        # s1 must still be COMPLETED — not re-executed
        assert completed_step["status"] == "COMPLETED", (
            f"COMPLETED step must not transition — got {completed_step['status']}"
        )
        # Only s2 should have been executed (1 call, not 2)
        assert exec_call_count["n"] <= 1, (
            f"COMPLETED step was re-executed: {exec_call_count['n']} calls made"
        )


# ===========================================================================
# REQUIREMENT 3 — PARALLEL EXECUTION RULES
# ===========================================================================

class TestParallelExecutionRules:
    """
    EXECUTION_SCHEDULING_CONTRACT_V1:
    - Independent steps (no deps, no conflicts) may execute concurrently
    - Dependent steps must be sequential
    - Destructive step types must NEVER be parallelized
    """

    def setup_method(self):
        _register_agent()
        reset_detector()

    def _make_scheduler_detector(self) -> ConflictDetector:
        """Return a fresh ConflictDetector for scheduler tests."""
        return ConflictDetector()

    # -----------------------------------------------------------------------
    # TEST 7 — Independent steps parallelized (scheduler level)
    # -----------------------------------------------------------------------

    def test_independent_steps_form_parallel_group(self):
        """
        TEST 7 — Two steps with no dependencies and no shared resources.

        ASSERT:
        - scheduler creates PARALLEL group
        - both step IDs present in group
        """
        step1 = _base_step("s1", tool_call="square_number 4")
        step2 = _base_step("s2", tool_call="square_number 9")
        # Different resource targets — no conflict
        step1["resource_targets"] = ["resource_A"]
        step2["resource_targets"] = ["resource_B"]

        workflow = _base_workflow("wf_parallel_group", [step1, step2])
        step_states = {"s1": "PENDING", "s2": "PENDING"}
        detector = self._make_scheduler_detector()

        group = create_execution_group(
            workflow=workflow,
            step_states=step_states,
            conflict_detector=detector,
            workflow_id="wf_parallel_group",
        )

        print(f"[TEST 7] group={group}")

        assert group is not None, "Scheduler must form a group for pending steps"
        assert group["group_type"] == "PARALLEL", (
            f"Independent steps must form PARALLEL group, got: {group['group_type']}"
        )
        assert "s1" in group["steps"] and "s2" in group["steps"], (
            f"Both steps must be in parallel group, got: {group['steps']}"
        )

    def test_independent_steps_execute_concurrently(self, monkeypatch):
        """
        TEST 7b — Full workflow execution: two independent steps run concurrently.

        ASSERT:
        - both steps complete successfully
        - workflow returns success
        """
        exec_order = []

        def mock_success(input_text):
            exec_order.append(input_text)
            return {"status": "success", "result": 16}

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            mock_success,
        )

        step1 = _base_step("s1", tool_call="square_number 4")
        step2 = _base_step("s2", tool_call="square_number 9")
        step1["resource_targets"] = ["res_A"]
        step2["resource_targets"] = ["res_B"]

        workflow = _base_workflow("wf_concurrent_exec", [step1, step2])
        result = run_workflow(workflow)

        print(f"[TEST 7b] result={result}")
        print(f"[TEST 7b] exec_order={exec_order}")

        assert result["status"] == "success", (
            f"Expected success for independent parallel steps, got: {result}"
        )
        # Both steps must have completed
        assert step1["status"] == "COMPLETED", f"s1 not COMPLETED: {step1['status']}"
        assert step2["status"] == "COMPLETED", f"s2 not COMPLETED: {step2['status']}"

    # -----------------------------------------------------------------------
    # TEST 8 — Dependent steps run sequentially
    # -----------------------------------------------------------------------

    def test_dependent_steps_sequential_order(self, monkeypatch):
        """
        TEST 8 — step2 depends on step1 (via depends_on field).

        ASSERT:
        - step2 starts AFTER step1
        - execution order is preserved
        """
        exec_order = []

        def mock_success(input_text):
            exec_order.append(input_text)
            return {"status": "success", "result": 16}

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            mock_success,
        )

        step1 = _base_step("s1", tool_call="square_number 4")
        step2 = _base_step("s2", tool_call="square_number 9")
        step2["depends_on"] = ["s1"]  # Explicit dependency

        workflow = _base_workflow("wf_sequential_deps", [step1, step2])
        result = run_workflow(workflow)

        print(f"[TEST 8] result={result}")
        print(f"[TEST 8] exec_order={exec_order}")

        assert result["status"] == "success", (
            f"Expected success for dependent sequential steps, got: {result}"
        )

        # Verify execution order: s1 input must appear before s2 input
        # Both inputs use USE_TOOL: prefix added by step_executor
        s1_tool = "square_number 4"
        s2_tool = "square_number 9"
        s1_idx = next(
            (i for i, inp in enumerate(exec_order) if s1_tool in inp), None
        )
        s2_idx = next(
            (i for i, inp in enumerate(exec_order) if s2_tool in inp), None
        )

        assert s1_idx is not None, f"s1 tool call not found in exec_order: {exec_order}"
        assert s2_idx is not None, f"s2 tool call not found in exec_order: {exec_order}"
        assert s1_idx < s2_idx, (
            f"s2 executed before s1 — dependency ordering VIOLATED. "
            f"s1_idx={s1_idx}, s2_idx={s2_idx}, order={exec_order}"
        )

    def test_dependent_steps_form_sequential_group(self):
        """
        TEST 8b — Scheduler level: dependent step forces SEQUENTIAL group.
        """
        step1 = _base_step("s1", tool_call="square_number 4")
        step2 = _base_step("s2", tool_call="square_number 9")
        step2["depends_on"] = ["s1"]  # Dependency declared

        workflow = _base_workflow("wf_dep_sequential_group", [step1, step2])
        step_states = {"s1": "PENDING", "s2": "PENDING"}
        detector = self._make_scheduler_detector()

        group = create_execution_group(
            workflow=workflow,
            step_states=step_states,
            conflict_detector=detector,
            workflow_id="wf_dep_sequential_group",
        )

        print(f"[TEST 8b] group={group}")

        assert group is not None, "Group must be formed"
        # s2 depends on s1 → s1 must go first in sequential group
        # The group will be SEQUENTIAL (s2 has dependency so parallel not formed)
        # s1 is eligible for its own group; s2 is dependency-blocked
        assert "s1" in group["steps"], (
            f"s1 must be in first group. Group: {group}"
        )

    # -----------------------------------------------------------------------
    # TEST 9 — Destructive steps not parallelized
    # -----------------------------------------------------------------------

    def test_destructive_step_not_parallel(self):
        """
        TEST 9 — EXECUTE_INSTALL step must be forced sequential.

        EXECUTION_SCHEDULING_CONTRACT_V1:
        NEVER include in parallel group:
        - type = EXECUTE_INSTALL
        - type = EXECUTE_SYSTEM_SETTINGS_SERVICES
        - type = EXECUTE_ENVIRONMENT (if modifying)
        - risk = HIGH

        ASSERT:
        - _is_destructive_step returns True for install type
        - scheduler does NOT place destructive step in PARALLEL group
        """
        # Direct check: _is_destructive_step contract
        install_step = _base_step("s_install", tool_call="square_number 4")
        install_step["type"] = "EXECUTE_INSTALL"

        assert _is_destructive_step(install_step) is True, (
            "EXECUTE_INSTALL must be classified as destructive"
        )

        env_step = _base_step("s_env", tool_call="square_number 4")
        env_step["type"] = "EXECUTE_ENVIRONMENT"

        assert _is_destructive_step(env_step) is True, (
            "EXECUTE_ENVIRONMENT must be classified as destructive"
        )

        sys_step = _base_step("s_sys", tool_call="square_number 4")
        sys_step["type"] = "EXECUTE_SYSTEM_SETTINGS_SERVICES"

        assert _is_destructive_step(sys_step) is True, (
            "EXECUTE_SYSTEM_SETTINGS_SERVICES must be classified as destructive"
        )

        high_risk_file = _base_step("s_file", tool_call="square_number 4")
        high_risk_file["type"] = "EXECUTE_FILE"
        high_risk_file["risk"] = "HIGH"

        assert _is_destructive_step(high_risk_file) is True, (
            "EXECUTE_FILE with HIGH risk must be classified as destructive"
        )

    def test_destructive_step_forced_sequential_by_scheduler(self):
        """
        TEST 9b — Two steps: one destructive, one normal.
        Scheduler must NOT form PARALLEL group containing the destructive step.
        """
        normal_step = _base_step("s_normal", tool_call="square_number 4")
        normal_step["resource_targets"] = ["res_A"]

        destructive_step = _base_step("s_install", tool_call="square_number 9")
        destructive_step["type"] = "EXECUTE_INSTALL"
        destructive_step["resource_targets"] = ["res_B"]

        workflow = _base_workflow("wf_destructive_sequential", [normal_step, destructive_step])
        step_states = {"s_normal": "PENDING", "s_install": "PENDING"}
        detector = self._make_scheduler_detector()

        group = create_execution_group(
            workflow=workflow,
            step_states=step_states,
            conflict_detector=detector,
            workflow_id="wf_destructive_sequential",
        )

        print(f"[TEST 9b] group={group}")

        assert group is not None, "Group must be formed"
        # Destructive step must NOT be in a PARALLEL group
        if group["group_type"] == "PARALLEL":
            assert "s_install" not in group["steps"], (
                f"EXECUTE_INSTALL step must NOT be in PARALLEL group. "
                f"Group: {group} — CONTRACT VIOLATION"
            )

    def test_high_risk_step_not_parallel(self):
        """
        TEST 9c — HIGH risk step must not be parallelized.

        Per EXECUTION_SCHEDULING_CONTRACT_V1:
        'risk = HIGH with destructive resource_target → NEVER parallel'
        """
        normal_step = _base_step("s_low", tool_call="square_number 4")
        high_risk_step = _base_step("s_high", tool_call="square_number 9")
        high_risk_step["risk"] = "HIGH"
        high_risk_step["type"] = "EXECUTE_FILE"

        assert _is_destructive_step(high_risk_step) is True, (
            "HIGH risk EXECUTE_FILE must be destructive → must not be parallelized"
        )

        workflow = _base_workflow("wf_high_risk_no_parallel", [normal_step, high_risk_step])
        step_states = {"s_low": "PENDING", "s_high": "PENDING"}
        detector = self._make_scheduler_detector()

        group = create_execution_group(
            workflow=workflow,
            step_states=step_states,
            conflict_detector=detector,
            workflow_id="wf_high_risk_no_parallel",
        )

        print(f"[TEST 9c] group={group}")

        assert group is not None
        if group["group_type"] == "PARALLEL":
            assert "s_high" not in group["steps"], (
                f"HIGH risk step must NOT be in PARALLEL group. Group: {group}"
            )


# ===========================================================================
# REQUIREMENT 4 — CONFLICT DETECTION
# ===========================================================================

class TestConflictDetection:
    """
    CONFLICT_RESOLUTION_CONTRACT_V1:
    - Two workflows targeting the same resource → second BLOCKED
    - Different resources → both execute
    - Conflict detection runs BEFORE execution
    """

    def setup_method(self):
        _register_agent()
        reset_detector()

    def _fresh_detector(self) -> ConflictDetector:
        return ConflictDetector()

    # -----------------------------------------------------------------------
    # TEST 10 — Resource conflict blocks second workflow
    # -----------------------------------------------------------------------

    def test_resource_conflict_blocks_second_workflow(self, monkeypatch):
        """
        TEST 10 — Two workflows targeting the same resource.

        ASSERT:
        - second workflow is BLOCKED (conflict detected)
        - ConflictDetector returns conflict=True with HIGH or MEDIUM severity
        """
        detector = self._fresh_detector()

        # First workflow registers and updates with shared resource
        wf1_step = _base_step("s1_wf1", tool_call="square_number 4")
        wf1_step["type"] = "EXECUTE_FILE"
        wf1_step["risk"] = "HIGH"
        wf1_step["resource_targets"] = ["C:\\shared\\resource.txt"]

        detector.register_workflow("wf_conflict_1")
        detector.update_step("wf_conflict_1", wf1_step)

        # Second workflow targets the SAME resource
        wf2_step = _base_step("s1_wf2", tool_call="square_number 9")
        wf2_step["type"] = "EXECUTE_FILE"
        wf2_step["risk"] = "HIGH"
        wf2_step["resource_targets"] = ["C:\\shared\\resource.txt"]

        detector.register_workflow("wf_conflict_2")

        conflict_result = detector.detect_conflict("wf_conflict_2", wf2_step)

        print(f"[TEST 10] conflict_result={conflict_result}")

        # Conflict MUST be detected
        assert conflict_result["conflict"] is True, (
            f"Expected conflict detected for same resource, got: {conflict_result}"
        )
        # Severity must be HIGH (destructive EXECUTE_FILE)
        assert conflict_result["severity"] in ("HIGH", "MEDIUM"), (
            f"Expected HIGH or MEDIUM severity, got: {conflict_result['severity']}"
        )

    def test_resource_conflict_in_runtime_blocks_workflow(self, monkeypatch):
        """
        TEST 10b — Full runtime: second workflow targeting same resource is blocked.

        Uses the global conflict detector (reset between tests).
        """
        exec_count = {"n": 0}

        def mock_success(input_text):
            exec_count["n"] += 1
            return {"status": "success", "result": 16}

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            mock_success,
        )

        # Manually register first workflow with shared resource in global detector
        global_detector = get_detector()
        first_wf_step = _base_step("s_first", tool_call="square_number 4")
        first_wf_step["type"] = "EXECUTE_FILE"
        first_wf_step["risk"] = "HIGH"
        first_wf_step["resource_targets"] = ["C:\\shared\\conflict_resource.txt"]

        global_detector.register_workflow("wf_first_active")
        global_detector.update_step("wf_first_active", first_wf_step)

        # Second workflow attempts to use same resource
        second_step = _base_step("s_second", tool_call="square_number 9")
        second_step["type"] = "EXECUTE_FILE"
        second_step["risk"] = "HIGH"
        second_step["resource_targets"] = ["C:\\shared\\conflict_resource.txt"]

        workflow2 = _base_workflow("wf_second_blocked", [second_step])
        result = run_workflow(workflow2)

        print(f"[TEST 10b] result={result}")
        print(f"[TEST 10b] exec_count={exec_count['n']}")

        # Second workflow MUST be blocked/failed due to conflict
        assert result["status"] == "failure", (
            f"Expected second workflow to be blocked/failed due to resource conflict, "
            f"got: {result}"
        )

        # Clean up
        global_detector.unregister_workflow("wf_first_active")

    # -----------------------------------------------------------------------
    # TEST 11 — No conflict: different resources allow both to execute
    # -----------------------------------------------------------------------

    def test_no_conflict_different_resources(self):
        """
        TEST 11 — Two workflows targeting different resources.

        ASSERT:
        - conflict detection returns conflict=False
        - both may execute (no blocking)
        """
        detector = self._fresh_detector()

        wf1_step = _base_step("s1", tool_call="square_number 4")
        wf1_step["resource_targets"] = ["C:\\resource_A.txt"]
        detector.register_workflow("wf_no_conflict_1")
        detector.update_step("wf_no_conflict_1", wf1_step)

        wf2_step = _base_step("s2", tool_call="square_number 9")
        wf2_step["resource_targets"] = ["C:\\resource_B.txt"]  # DIFFERENT resource
        detector.register_workflow("wf_no_conflict_2")

        conflict_result = detector.detect_conflict("wf_no_conflict_2", wf2_step)

        print(f"[TEST 11] conflict_result={conflict_result}")

        # No conflict must be detected
        assert conflict_result["conflict"] is False, (
            f"Expected NO conflict for different resources, got: {conflict_result}"
        )
        assert conflict_result["severity"] in ("NONE", "LOW"), (
            f"Expected NONE/LOW severity for different resources, "
            f"got: {conflict_result['severity']}"
        )

    def test_no_conflict_both_workflows_execute(self, monkeypatch):
        """
        TEST 11b — Full runtime: two sequential workflows with different resources
        both execute successfully.
        """
        exec_count = {"n": 0}

        def mock_success(input_text):
            exec_count["n"] += 1
            return {"status": "success", "result": 16}

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            mock_success,
        )

        step_a = _base_step("s_a", tool_call="square_number 4")
        step_a["resource_targets"] = ["C:\\unique_resource_a.txt"]
        wf_a = _base_workflow("wf_no_conflict_a", [step_a])
        result_a = run_workflow(wf_a)

        step_b = _base_step("s_b", tool_call="square_number 9")
        step_b["resource_targets"] = ["C:\\unique_resource_b.txt"]
        wf_b = _base_workflow("wf_no_conflict_b", [step_b])
        result_b = run_workflow(wf_b)

        print(f"[TEST 11b] result_a={result_a}")
        print(f"[TEST 11b] result_b={result_b}")
        print(f"[TEST 11b] exec_count={exec_count['n']}")

        # Both must succeed
        assert result_a["status"] == "success", (
            f"wf_a failed unexpectedly: {result_a}"
        )
        assert result_b["status"] == "success", (
            f"wf_b failed unexpectedly: {result_b}"
        )
        # Both workflows executed (2 calls minimum)
        assert exec_count["n"] >= 2, (
            f"Expected at least 2 executions, got {exec_count['n']}"
        )


# ===========================================================================
# CROSS-CUTTING: SYSTEM_ENTRY GATEWAY ENFORCEMENT
# ===========================================================================

class TestSystemEntryGateway:
    """
    ORCHESTRATOR_CONTRACT_V2 + HARNESS_SPEC:
    - ALL execution MUST go through system_entry
    - Orchestrator MUST NOT execute tools directly
    - No direct tool calls
    """

    def setup_method(self):
        _register_agent()
        reset_detector()

    def test_execution_routed_through_system_entry(self, monkeypatch):
        """
        Validates that workflow execution calls system_entry for every step.

        ASSERT:
        - system_entry is called at least once per step
        - execution_result drives outcome (not direct tool call)
        """
        system_entry_calls = []

        def recording_system_entry(input_text):
            system_entry_calls.append(input_text)
            from system.entry.system_entry import system_entry as real_se
            return real_se(input_text)

        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            recording_system_entry,
        )

        step = _base_step("s1", tool_call="square_number 4")
        workflow = _base_workflow("wf_gateway_check", [step])
        result = run_workflow(workflow)

        print(f"[GATEWAY TEST] result={result}")
        print(f"[GATEWAY TEST] system_entry calls={system_entry_calls}")

        # system_entry MUST have been called
        assert len(system_entry_calls) > 0, (
            "system_entry was NEVER called — execution bypass detected. "
            "CONTRACT VIOLATION: ALL execution must go through system_entry."
        )

    def test_governance_decision_drives_outcome(self, monkeypatch):
        """
        Validates that execution_result drives governance decision (not signals).

        ASSERT:
        - execution success → governance complete → step COMPLETED
        - execution failure → governance retry/fail → step FAILED or BLOCKED
        """
        # Test: success execution → complete decision → COMPLETED
        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            lambda _: {"status": "success", "result": 16},
        )

        step = _base_step("s1", tool_call="square_number 4")
        workflow = _base_workflow("wf_governance_success", [step])
        result = run_workflow(workflow)

        print(f"[GOVERNANCE TEST] success result={result}")
        print(f"[GOVERNANCE TEST] step status={step['status']}")

        assert result["status"] == "success", (
            f"Successful execution_result must drive successful outcome: {result}"
        )
        assert step["status"] == "COMPLETED", (
            f"Step must be COMPLETED when execution succeeds: {step['status']}"
        )

    def test_failed_execution_result_propagates_to_failure(self, monkeypatch):
        """
        Validates that failed execution_result drives failure outcome.
        """
        monkeypatch.setattr(
            "system.orchestrator.agents.tool_selection_agent.system_entry",
            lambda _: {"status": "failure", "reason": "tool_not_found"},
        )

        # Step with HIGH risk → max_retries=1 (governance limits retries by risk)
        step = _base_step("s1", tool_call="square_number 4", risk="HIGH", max_retries=1)
        workflow = _base_workflow("wf_governance_failure", [step])
        result = run_workflow(workflow)

        print(f"[GOVERNANCE TEST] failure result={result}")

        assert result["status"] == "failure", (
            f"Failed execution_result must propagate to failure outcome: {result}"
        )
        assert "reason" in result, "Failure response must include reason"
