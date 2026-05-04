"""
Phase 1B — Parallel Execution Validation (STRICT CONTRACT VALIDATION)

Tests run REAL execution paths with controlled mocks for:
- execute_step_fn (simulates system_entry results)
- governance_fn (simulates per-step decisions)
- propagate_fn (simulates result propagation)

All other layers (scheduler, parallel executor, trace, conflict) run UNMODIFIED.

Contract coverage:
- GOVERNANCE_CONTRACT: per-step decisions, no batching, BLOCK behavior
- EXECUTION_SCHEDULING_CONTRACT_V1: group formation, parallel rules, synchronization
- STATE_TRANSITIONS_CONTRACT_V1: step transitions, project transitions
- CONFLICT_RESOLUTION_CONTRACT_V1: pre-execution detection, enforcement
- TRACE_LOGGING_CONTRACT_V1: event completeness, structure correctness
"""

import sys
import os
import time
import threading
import copy

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from system.orchestrator.execution_scheduler import create_execution_group
from system.orchestrator.parallel_executor import (
    execute_parallel_group,
    execute_sequential_group,
    _execute_single_step,
)
from system.orchestrator.conflict_detector import ConflictDetector, reset_detector
from system.orchestrator import trace_collector


# ============================================================
# HELPERS
# ============================================================

@pytest.fixture(autouse=True)
def clean_state():
    """Reset trace collector and conflict detector for every test."""
    trace_collector.create_collector("validation_workflow")
    yield
    reset_detector()


def _make_step(step_id, step_type="EXECUTE_API", risk="LOW",
               resource_targets=None, depends_on=None, status="PENDING"):
    return {
        "id": step_id,
        "type": step_type,
        "purpose": f"Test step {step_id}",
        "tool_call": f"USE_TOOL: test_tool {step_id}",
        "expected_outcome": "Test completed",
        "risk": risk,
        "importance": "MEDIUM",
        "resource_targets": resource_targets or [],
        "status": status,
        "retries": 0,
        "max_retries": 3,
        "input": f"test input {step_id}",
        "attempt_history": [],
    }


def _make_workflow(steps, workflow_id="val_wf"):
    return {
        "id": workflow_id,
        "name": "validation_workflow",
        "status": "ACTIVE",
        "steps": steps,
        "step_history": [],
        "last_result": None,
    }


class MockEscalationHandler:
    """Mock that mimics escalation_controller interface."""

    def handle_retry(self, step, workflow, next_decision):
        step["retries"] += 1
        if step["retries"] >= step.get("max_retries", 3):
            step["status"] = "FAILED"
            workflow["status"] = "BLOCKED"
            return {"action": "BLOCKED"}
        step["status"] = "PENDING"
        return {"action": "RETRY"}

    def handle_escalation(self, step, workflow, next_decision, exec_res):
        step["status"] = "BLOCKED"
        workflow["status"] = "BLOCKED"
        return {"action": "BLOCKED", "result": None}


MOCK_ESCALATION = MockEscalationHandler()


def _get_trace_events():
    """Extract all trace events from the active collector."""
    trace_data = trace_collector.get_trace()
    if trace_data is None:
        return []
    return trace_data.get("steps", [])


def _filter_trace_reasons(events, prefix):
    """Filter trace events whose reason starts with a given prefix."""
    return [
        e for e in events
        if e.get("data", {}).get("reason", "").startswith(prefix)
    ]


# ============================================================
# TEST 1 — GOVERNANCE ISOLATION
# ============================================================

class TestGovernanceIsolation:
    """
    Scenario: Step A → success, Step B → failure → retry
    Run in PARALLEL group.

    VERIFY:
    - Step A remains COMPLETED
    - Step B enters retry path (FAILED or PENDING via escalation)
    - NO cross-step influence
    - Step A status NOT affected by Step B failure
    """

    def test_governance_isolation_parallel(self):
        steps = [
            _make_step("step_a", resource_targets=["file_a.txt"]),
            _make_step("step_b", resource_targets=["file_b.txt"]),
        ]
        workflow = _make_workflow(steps)

        # Track which steps were executed and in which thread
        execution_log = []
        log_lock = threading.Lock()

        def mock_execute_step(step, workflow, retry_guidance=None, debug_verbose=False):
            step_id = step["id"]
            with log_lock:
                execution_log.append({
                    "step_id": step_id,
                    "thread": threading.current_thread().name
                })
            if step_id == "step_a":
                return {
                    "execution_result": {"status": "success", "result": "a_done"},
                    "step_result": {"status": "success", "result": {"execution_result": {"status": "success", "result": "a_done"}}},
                    "validator_output": {},
                }
            else:
                return {
                    "execution_result": {"status": "failure", "reason": "tool_error"},
                    "step_result": {"status": "failure", "result": {"execution_result": {"status": "failure", "reason": "tool_error"}}},
                    "validator_output": {},
                }

        def mock_governance(validator_output, execution_result, step, context):
            if execution_result and execution_result.get("status") == "success":
                return "complete"
            return "fail"

        def mock_propagate(step, execution_result, step_result, debug_verbose=False):
            if execution_result:
                step["execution_result"] = execution_result

        group = {
            "group_id": "test_gov_iso",
            "group_type": "PARALLEL",
            "steps": ["step_a", "step_b"],
            "boundary_rules": {"wait_for_all": True, "allow_partial_completion": False},
        }

        results = execute_parallel_group(
            group=group,
            workflow=workflow,
            execute_step_fn=mock_execute_step,
            governance_fn=mock_governance,
            propagate_fn=mock_propagate,
            escalation_handler=MOCK_ESCALATION,
            debug_verbose=False,
        )

        # === RAW OUTPUT ===
        print("\n=== TEST 1 — GOVERNANCE ISOLATION RAW OUTPUT ===")
        for r in results:
            print(f"  step={r['step_id']} status={r['status']} gov={r['governance_decision']}")
        print(f"  execution_log={execution_log}")

        # === TRACE ===
        events = _get_trace_events()
        print(f"  trace_event_count={len(events)}")

        # === VALIDATION ===
        result_map = {r["step_id"]: r for r in results}

        # Condition 1: Step A remains COMPLETED
        assert result_map["step_a"]["status"] == "COMPLETED", \
            f"FAIL: Step A status={result_map['step_a']['status']}, expected COMPLETED"
        assert result_map["step_a"]["governance_decision"] == "complete"

        # Condition 2: Step B enters failure/escalation path
        assert result_map["step_b"]["status"] in ("FAILED", "BLOCKED"), \
            f"FAIL: Step B status={result_map['step_b']['status']}, expected FAILED or BLOCKED"

        # Condition 3: NO cross-step influence — Step A not affected by B
        step_a_obj = next(s for s in workflow["steps"] if s["id"] == "step_a")
        assert step_a_obj["status"] == "COMPLETED", \
            f"FAIL: Step A workflow object status contaminated: {step_a_obj['status']}"

        # Condition 4: Both steps executed (both threads ran)
        assert len(execution_log) == 2, f"FAIL: Expected 2 executions, got {len(execution_log)}"

        print("  ✓ Condition 1: Step A COMPLETED — PASS")
        print("  ✓ Condition 2: Step B FAILED/BLOCKED — PASS")
        print("  ✓ Condition 3: No cross-step influence — PASS")
        print("  ✓ Condition 4: Both steps executed — PASS")


# ============================================================
# TEST 2 — BLOCK PROPAGATION
# ============================================================

class TestBlockPropagation:
    """
    Scenario: Step A triggers BLOCK, Step B still running.

    VERIFY:
    - Step A becomes BLOCKED
    - Step B completes independently (per-step governance)
    - Post-group: workflow detects BLOCKED step
    """

    def test_block_propagation_parallel(self):
        steps = [
            _make_step("step_a", resource_targets=["file_a.txt"]),
            _make_step("step_b", resource_targets=["file_b.txt"]),
        ]
        workflow = _make_workflow(steps)

        def mock_execute_step(step, workflow, retry_guidance=None, debug_verbose=False):
            return {
                "execution_result": {"status": "success", "result": f"{step['id']}_done"},
                "step_result": {"status": "success", "result": {"execution_result": {"status": "success", "result": f"{step['id']}_done"}}},
                "validator_output": {},
            }

        def mock_governance(validator_output, execution_result, step, context):
            if step["id"] == "step_a":
                return "block"  # Step A triggers BLOCK
            return "complete"   # Step B completes normally

        def mock_propagate(step, execution_result, step_result, debug_verbose=False):
            if execution_result:
                step["execution_result"] = execution_result

        group = {
            "group_id": "test_block_prop",
            "group_type": "PARALLEL",
            "steps": ["step_a", "step_b"],
            "boundary_rules": {"wait_for_all": True, "allow_partial_completion": False},
        }

        results = execute_parallel_group(
            group=group,
            workflow=workflow,
            execute_step_fn=mock_execute_step,
            governance_fn=mock_governance,
            propagate_fn=mock_propagate,
            escalation_handler=MOCK_ESCALATION,
            debug_verbose=False,
        )

        # === RAW OUTPUT ===
        print("\n=== TEST 2 — BLOCK PROPAGATION RAW OUTPUT ===")
        result_map = {r["step_id"]: r for r in results}
        for r in results:
            print(f"  step={r['step_id']} status={r['status']} gov={r['governance_decision']}")

        # Post-group: check workflow state (simulating orchestrator_runtime post-group logic)
        any_blocked = any(s["status"] == "BLOCKED" for s in workflow["steps"])
        if any_blocked:
            workflow["status"] = "BLOCKED"

        print(f"  workflow_status={workflow['status']}")

        # === VALIDATION ===
        # Condition 1: Step A becomes BLOCKED
        assert result_map["step_a"]["status"] == "BLOCKED"
        assert result_map["step_a"]["governance_decision"] == "block"

        # Condition 2: Step B remains COMPLETED (not affected)
        assert result_map["step_b"]["status"] == "COMPLETED"
        assert result_map["step_b"]["governance_decision"] == "complete"

        # Condition 3: Workflow transitions to BLOCKED
        assert workflow["status"] == "BLOCKED", \
            f"FAIL: Workflow status={workflow['status']}, expected BLOCKED"

        # Condition 4: No further groups should execute (verified by scheduler)
        step_states = {s["id"]: s["status"] for s in workflow["steps"]}
        detector = ConflictDetector()
        next_group = create_execution_group(workflow, step_states, detector, "val_wf")
        # BLOCKED step blocks new group formation
        assert next_group is None, \
            f"FAIL: Next group should be None due to BLOCKED step, got {next_group}"

        print("  ✓ Condition 1: Step A BLOCKED — PASS")
        print("  ✓ Condition 2: Step B COMPLETED independently — PASS")
        print("  ✓ Condition 3: Workflow BLOCKED — PASS")
        print("  ✓ Condition 4: No further groups execute — PASS")


# ============================================================
# TEST 3 — STATE TRANSITIONS
# ============================================================

class TestStateTransitions:
    """
    Scenario: Multiple steps ACTIVE in parallel.

    VERIFY:
    - Each step transitions independently
    - Project state transitions correctly
    """

    def test_parallel_state_transitions(self):
        steps = [
            _make_step("s1", resource_targets=["r1"]),
            _make_step("s2", resource_targets=["r2"]),
            _make_step("s3", resource_targets=["r3"]),
        ]
        workflow = _make_workflow(steps)
        state_snapshots = []
        snap_lock = threading.Lock()

        def mock_execute_step(step, workflow, retry_guidance=None, debug_verbose=False):
            # Capture state DURING execution (step should be ACTIVE)
            with snap_lock:
                state_snapshots.append({
                    "step_id": step["id"],
                    "step_status": step["status"],
                    "all_statuses": {s["id"]: s["status"] for s in workflow["steps"]},
                })
            return {
                "execution_result": {"status": "success", "result": f"{step['id']}_ok"},
                "step_result": {"status": "success", "result": {"execution_result": {"status": "success", "result": f"{step['id']}_ok"}}},
                "validator_output": {},
            }

        def mock_governance(validator_output, execution_result, step, context):
            return "complete"

        def mock_propagate(step, execution_result, step_result, debug_verbose=False):
            if execution_result:
                step["execution_result"] = execution_result

        group = {
            "group_id": "test_state_trans",
            "group_type": "PARALLEL",
            "steps": ["s1", "s2", "s3"],
            "boundary_rules": {"wait_for_all": True, "allow_partial_completion": False},
        }

        results = execute_parallel_group(
            group=group,
            workflow=workflow,
            execute_step_fn=mock_execute_step,
            governance_fn=mock_governance,
            propagate_fn=mock_propagate,
            escalation_handler=MOCK_ESCALATION,
        )

        # === RAW OUTPUT ===
        print("\n=== TEST 3 — STATE TRANSITIONS RAW OUTPUT ===")
        for r in results:
            print(f"  step={r['step_id']} final_status={r['status']}")
        print(f"  state_snapshots:")
        for snap in state_snapshots:
            print(f"    {snap}")

        # === VALIDATION ===
        # Condition 1: Each step was ACTIVE during execution
        for snap in state_snapshots:
            assert snap["step_status"] == "ACTIVE", \
                f"FAIL: Step {snap['step_id']} was {snap['step_status']} during execution, expected ACTIVE"

        # Condition 2: All steps independently reached COMPLETED
        for r in results:
            assert r["status"] == "COMPLETED", \
                f"FAIL: Step {r['step_id']} final status={r['status']}, expected COMPLETED"

        # Condition 3: Post-group — all COMPLETED → workflow should be COMPLETED
        all_completed = all(s["status"] == "COMPLETED" for s in workflow["steps"])
        assert all_completed, "FAIL: Not all steps COMPLETED after group"

        # Condition 4: No inconsistent states (no step should be PENDING after group)
        for s in workflow["steps"]:
            assert s["status"] != "PENDING", \
                f"FAIL: Step {s['id']} still PENDING after group execution"

        print("  ✓ Condition 1: Each step ACTIVE during execution — PASS")
        print("  ✓ Condition 2: Each step independently COMPLETED — PASS")
        print("  ✓ Condition 3: All COMPLETED post-group — PASS")
        print("  ✓ Condition 4: No inconsistent states — PASS")


# ============================================================
# TEST 4 — RUNTIME CONFLICT ENFORCEMENT
# ============================================================

class TestRuntimeConflictEnforcement:
    """
    Scenario: Two steps with SAME resource_targets.

    VERIFY:
    - Conflict detected BEFORE execution
    - Parallel group does NOT contain both conflicting steps
    """

    def test_same_resource_conflict(self):
        steps = [
            _make_step("s1", step_type="EXECUTE_API", resource_targets=["shared_db"]),
            _make_step("s2", step_type="EXECUTE_API", resource_targets=["shared_db"]),
            _make_step("s3", step_type="ANALYZE", resource_targets=["other_file"]),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "val_wf")

        # === RAW OUTPUT ===
        print("\n=== TEST 4 — RUNTIME CONFLICT ENFORCEMENT RAW OUTPUT ===")
        print(f"  group_type={group['group_type']}")
        print(f"  group_steps={group['steps']}")

        # === TRACE ===
        events = _get_trace_events()
        conflict_events = _filter_trace_reasons(events, "CONFLICT_EXCLUSION")
        eligibility_events = _filter_trace_reasons(events, "PARALLEL_ELIGIBILITY_CHECK")
        print(f"  conflict_exclusion_events={len(conflict_events)}")
        print(f"  eligibility_check_events={len(eligibility_events)}")

        # === VALIDATION ===
        # Condition 1: Both s1 and s2 must NOT be in same parallel group
        if group["group_type"] == "PARALLEL":
            assert not ("s1" in group["steps"] and "s2" in group["steps"]), \
                "FAIL: Both conflicting steps in same parallel group"
        else:
            # Sequential is also valid — conflict forces sequentialization
            assert group["group_type"] == "SEQUENTIAL"

        # Condition 2: Conflict detection happened BEFORE execution
        # (verified by the fact that group formation excluded conflicting steps)
        assert group is not None, "FAIL: No group formed"

        # Condition 3: Trace shows conflict exclusion or dependency detection
        dep_events = _filter_trace_reasons(events, "PARALLEL_ELIGIBILITY_CHECK:eligible=false:reason=DEPENDENCY_DETECTED")
        assert len(dep_events) > 0 or len(conflict_events) > 0, \
            "FAIL: No conflict/dependency trace events found"

        print("  ✓ Condition 1: Conflicting steps not in same parallel group — PASS")
        print("  ✓ Condition 2: Conflict detected before execution — PASS")
        print("  ✓ Condition 3: Trace events present — PASS")


# ============================================================
# TEST 5 — STEP ATOMICITY
# ============================================================

class TestStepAtomicity:
    """
    Scenario: Steps modify internal data.

    VERIFY:
    - No shared mutation between steps
    - No context leakage
    """

    def test_no_shared_mutation(self):
        steps = [
            _make_step("s1", resource_targets=["r1"]),
            _make_step("s2", resource_targets=["r2"]),
        ]
        # Give each step its own data dict to track contamination
        steps[0]["_test_data"] = {"value": "s1_original"}
        steps[1]["_test_data"] = {"value": "s2_original"}

        workflow = _make_workflow(steps)
        contamination_detected = []
        contam_lock = threading.Lock()

        def mock_execute_step(step, workflow, retry_guidance=None, debug_verbose=False):
            step_id = step["id"]
            # Each step mutates its own _test_data
            step["_test_data"]["value"] = f"{step_id}_modified"

            # Check if the OTHER step's data was contaminated
            other_id = "s2" if step_id == "s1" else "s1"
            other_step = next(s for s in workflow["steps"] if s["id"] == other_id)

            with contam_lock:
                if other_step["_test_data"]["value"] != f"{other_id}_original" and \
                   other_step["_test_data"]["value"] != f"{other_id}_modified":
                    contamination_detected.append({
                        "checker": step_id,
                        "other": other_id,
                        "other_value": other_step["_test_data"]["value"],
                    })

            return {
                "execution_result": {"status": "success", "result": f"{step_id}_ok"},
                "step_result": {"status": "success", "result": {"execution_result": {"status": "success", "result": f"{step_id}_ok"}}},
                "validator_output": {},
            }

        def mock_governance(validator_output, execution_result, step, context):
            return "complete"

        def mock_propagate(step, execution_result, step_result, debug_verbose=False):
            if execution_result:
                step["execution_result"] = execution_result

        group = {
            "group_id": "test_atomicity",
            "group_type": "PARALLEL",
            "steps": ["s1", "s2"],
            "boundary_rules": {"wait_for_all": True, "allow_partial_completion": False},
        }

        results = execute_parallel_group(
            group=group,
            workflow=workflow,
            execute_step_fn=mock_execute_step,
            governance_fn=mock_governance,
            propagate_fn=mock_propagate,
            escalation_handler=MOCK_ESCALATION,
        )

        # === RAW OUTPUT ===
        print("\n=== TEST 5 — STEP ATOMICITY RAW OUTPUT ===")
        for r in results:
            print(f"  step={r['step_id']} status={r['status']}")
        print(f"  contamination_detected={contamination_detected}")

        # === VALIDATION ===
        # Condition 1: No contamination detected
        assert len(contamination_detected) == 0, \
            f"FAIL: Data contamination detected: {contamination_detected}"

        # Condition 2: Each step's data was modified only by itself
        for s in workflow["steps"]:
            assert s["_test_data"]["value"] == f"{s['id']}_modified", \
                f"FAIL: Step {s['id']} data={s['_test_data']['value']}"

        # Condition 3: Each step has its own execution_result (no leakage)
        for s in workflow["steps"]:
            exec_res = s.get("execution_result", {})
            expected_result = f"{s['id']}_ok"
            assert exec_res.get("result") == expected_result, \
                f"FAIL: Step {s['id']} execution_result leaked: {exec_res}"

        print("  ✓ Condition 1: No data contamination — PASS")
        print("  ✓ Condition 2: Each step's own data only — PASS")
        print("  ✓ Condition 3: No execution_result leakage — PASS")


# ============================================================
# TEST 6 — TRACE INTEGRITY
# ============================================================

class TestTraceIntegrity:
    """
    VERIFY required trace events exist with correct structure.

    Required per EXECUTION_SCHEDULING_CONTRACT_V1 Section 8:
    - GROUP_FORMED
    - GROUP_STARTED
    - GROUP_COMPLETED
    - GROUP_STEP_STARTED (per step)
    - GROUP_STEP_COMPLETED (per step)
    - PARALLEL_ELIGIBILITY_CHECK
    - PARALLEL_GROUP_SYNCHRONIZE (for parallel groups)
    """

    def test_trace_completeness_parallel(self):
        steps = [
            _make_step("s1", resource_targets=["r1"]),
            _make_step("s2", resource_targets=["r2"]),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        # Phase 1: Create group (generates PARALLEL_ELIGIBILITY_CHECK + GROUP_FORMED)
        group = create_execution_group(workflow, step_states, detector, "val_wf")
        assert group is not None
        assert group["group_type"] == "PARALLEL"

        # Phase 2: Execute group (generates GROUP_STARTED, STEP events, GROUP_COMPLETED)
        def mock_execute_step(step, workflow, retry_guidance=None, debug_verbose=False):
            return {
                "execution_result": {"status": "success", "result": f"{step['id']}_ok"},
                "step_result": {"status": "success", "result": {"execution_result": {"status": "success", "result": f"{step['id']}_ok"}}},
                "validator_output": {},
            }

        def mock_governance(validator_output, execution_result, step, context):
            return "complete"

        def mock_propagate(step, execution_result, step_result, debug_verbose=False):
            if execution_result:
                step["execution_result"] = execution_result

        results = execute_parallel_group(
            group=group,
            workflow=workflow,
            execute_step_fn=mock_execute_step,
            governance_fn=mock_governance,
            propagate_fn=mock_propagate,
            escalation_handler=MOCK_ESCALATION,
        )

        # === RAW OUTPUT ===
        events = _get_trace_events()
        print("\n=== TEST 6 — TRACE INTEGRITY RAW OUTPUT ===")
        print(f"  total_events={len(events)}")
        for i, e in enumerate(events):
            reason = e.get("data", {}).get("reason", "N/A")
            step_id = e.get("data", {}).get("step_id", "N/A")
            print(f"  [{i}] step_id={step_id} reason={reason[:80]}")

        # === VALIDATION ===
        reasons = [e.get("data", {}).get("reason", "") for e in events]

        # Condition 1: PARALLEL_ELIGIBILITY_CHECK events exist
        eligibility = [r for r in reasons if "PARALLEL_ELIGIBILITY_CHECK" in r]
        assert len(eligibility) >= 2, \
            f"FAIL: Expected ≥2 PARALLEL_ELIGIBILITY_CHECK events, got {len(eligibility)}"

        # Condition 2: GROUP_FORMED event exists
        formed = [r for r in reasons if "GROUP_FORMED" in r]
        assert len(formed) >= 1, \
            f"FAIL: Expected GROUP_FORMED event, found {len(formed)}"

        # Condition 3: GROUP_STARTED event exists
        started = [r for r in reasons if "GROUP_STARTED" in r]
        assert len(started) >= 1, \
            f"FAIL: Expected GROUP_STARTED event, found {len(started)}"

        # Condition 4: GROUP_STEP_STARTED events (one per step)
        step_started = [r for r in reasons if "GROUP_STEP_STARTED" in r]
        assert len(step_started) >= 2, \
            f"FAIL: Expected ≥2 GROUP_STEP_STARTED events, got {len(step_started)}"

        # Condition 5: GROUP_STEP_COMPLETED events (one per step)
        step_completed = [r for r in reasons if "GROUP_STEP_COMPLETED" in r]
        assert len(step_completed) >= 2, \
            f"FAIL: Expected ≥2 GROUP_STEP_COMPLETED events, got {len(step_completed)}"

        # Condition 6: PARALLEL_GROUP_SYNCHRONIZE event
        sync = [r for r in reasons if "PARALLEL_GROUP_SYNCHRONIZE" in r]
        assert len(sync) >= 1, \
            f"FAIL: Expected PARALLEL_GROUP_SYNCHRONIZE event, got {len(sync)}"

        # Condition 7: GROUP_COMPLETED event exists
        completed = [r for r in reasons if "GROUP_COMPLETED" in r]
        assert len(completed) >= 1, \
            f"FAIL: Expected GROUP_COMPLETED event, found {len(completed)}"

        # Condition 8: Each event has required structure (timestamp, project_id, data)
        for e in events:
            assert "timestamp" in e, "FAIL: Missing timestamp in trace event"
            assert "project_id" in e, "FAIL: Missing project_id in trace event"
            assert "data" in e, "FAIL: Missing data in trace event"

        # Condition 9: GROUP_COMPLETED is AFTER all STEP_COMPLETED (logical ordering)
        # Find indices
        step_completed_indices = [i for i, r in enumerate(reasons) if "GROUP_STEP_COMPLETED" in r]
        group_completed_indices = [i for i, r in enumerate(reasons) if "GROUP_COMPLETED" in r]
        if step_completed_indices and group_completed_indices:
            last_step_completed = max(step_completed_indices)
            first_group_completed = min(group_completed_indices)
            assert first_group_completed > last_step_completed, \
                "FAIL: GROUP_COMPLETED before last GROUP_STEP_COMPLETED"

        print("  ✓ Condition 1: PARALLEL_ELIGIBILITY_CHECK events — PASS")
        print("  ✓ Condition 2: GROUP_FORMED event — PASS")
        print("  ✓ Condition 3: GROUP_STARTED event — PASS")
        print("  ✓ Condition 4: GROUP_STEP_STARTED events — PASS")
        print("  ✓ Condition 5: GROUP_STEP_COMPLETED events — PASS")
        print("  ✓ Condition 6: PARALLEL_GROUP_SYNCHRONIZE — PASS")
        print("  ✓ Condition 7: GROUP_COMPLETED event — PASS")
        print("  ✓ Condition 8: Trace event structure — PASS")
        print("  ✓ Condition 9: Logical event ordering — PASS")


# ============================================================
# TEST 7 — PARALLEL SYNCHRONIZATION
# ============================================================

class TestParallelSynchronization:
    """
    Scenario: One fast step, one slow step.

    VERIFY:
    - Group completes ONLY after both finish
    - Next group starts ONLY after first completes
    """

    def test_fast_slow_synchronization(self):
        steps = [
            _make_step("fast", resource_targets=["r_fast"]),
            _make_step("slow", resource_targets=["r_slow"]),
        ]
        workflow = _make_workflow(steps)

        completion_order = []
        order_lock = threading.Lock()

        def mock_execute_step(step, workflow, retry_guidance=None, debug_verbose=False):
            step_id = step["id"]
            if step_id == "slow":
                time.sleep(0.3)  # Slow step
            else:
                time.sleep(0.05)  # Fast step

            with order_lock:
                completion_order.append(step_id)

            return {
                "execution_result": {"status": "success", "result": f"{step_id}_ok"},
                "step_result": {"status": "success", "result": {"execution_result": {"status": "success", "result": f"{step_id}_ok"}}},
                "validator_output": {},
            }

        def mock_governance(validator_output, execution_result, step, context):
            return "complete"

        def mock_propagate(step, execution_result, step_result, debug_verbose=False):
            if execution_result:
                step["execution_result"] = execution_result

        group = {
            "group_id": "test_sync",
            "group_type": "PARALLEL",
            "steps": ["fast", "slow"],
            "boundary_rules": {"wait_for_all": True, "allow_partial_completion": False},
        }

        # Time the group execution
        start_time = time.time()
        results = execute_parallel_group(
            group=group,
            workflow=workflow,
            execute_step_fn=mock_execute_step,
            governance_fn=mock_governance,
            propagate_fn=mock_propagate,
            escalation_handler=MOCK_ESCALATION,
        )
        elapsed = time.time() - start_time

        # === RAW OUTPUT ===
        print("\n=== TEST 7 — PARALLEL SYNCHRONIZATION RAW OUTPUT ===")
        print(f"  completion_order={completion_order}")
        print(f"  elapsed={elapsed:.3f}s")
        for r in results:
            print(f"  step={r['step_id']} status={r['status']}")

        # === VALIDATION ===
        # Condition 1: Both steps completed
        assert len(results) == 2, f"FAIL: Expected 2 results, got {len(results)}"

        # Condition 2: Fast finished before slow
        assert completion_order[0] == "fast", \
            f"FAIL: Expected fast to finish first, got {completion_order}"

        # Condition 3: Group waited for slow step (elapsed >= 0.3s)
        assert elapsed >= 0.25, \
            f"FAIL: Group returned too early ({elapsed:.3f}s), slow step not waited for"

        # Condition 4: Both results present (barrier synchronization)
        result_ids = {r["step_id"] for r in results}
        assert result_ids == {"fast", "slow"}, \
            f"FAIL: Missing results, got {result_ids}"

        # Condition 5: Verify no next group starts during parallel execution
        # After group completes, all steps should be terminal
        for s in workflow["steps"]:
            assert s["status"] in ("COMPLETED", "FAILED", "BLOCKED"), \
                f"FAIL: Step {s['id']} not terminal after group: {s['status']}"

        # Condition 6: TRACE shows synchronization event
        events = _get_trace_events()
        sync_events = _filter_trace_reasons(events, "PARALLEL_GROUP_SYNCHRONIZE")
        assert len(sync_events) >= 1, \
            "FAIL: No PARALLEL_GROUP_SYNCHRONIZE trace event"

        print("  ✓ Condition 1: Both steps completed — PASS")
        print("  ✓ Condition 2: Fast finished first — PASS")
        print("  ✓ Condition 3: Group waited for slow step — PASS")
        print("  ✓ Condition 4: Barrier synchronization — PASS")
        print("  ✓ Condition 5: All steps terminal after group — PASS")
        print("  ✓ Condition 6: Synchronization trace event — PASS")


# ============================================================
# SUPPLEMENTARY: SEQUENTIAL GROUP GOVERNANCE
# ============================================================

class TestSequentialGroupGovernance:
    """Verify sequential groups also maintain per-step governance."""

    def test_sequential_per_step_governance(self):
        steps = [
            _make_step("s1", step_type="EXECUTE_INSTALL"),  # Destructive → sequential
        ]
        workflow = _make_workflow(steps)

        governance_calls = []

        def mock_execute_step(step, workflow, retry_guidance=None, debug_verbose=False):
            return {
                "execution_result": {"status": "success", "result": "installed"},
                "step_result": {"status": "success", "result": {"execution_result": {"status": "success", "result": "installed"}}},
                "validator_output": {},
            }

        def mock_governance(validator_output, execution_result, step, context):
            governance_calls.append(step["id"])
            return "complete"

        def mock_propagate(step, execution_result, step_result, debug_verbose=False):
            if execution_result:
                step["execution_result"] = execution_result

        group = {
            "group_id": "test_seq_gov",
            "group_type": "SEQUENTIAL",
            "steps": ["s1"],
            "boundary_rules": {"wait_for_all": True, "allow_partial_completion": False},
        }

        results = execute_sequential_group(
            group=group,
            workflow=workflow,
            execute_step_fn=mock_execute_step,
            governance_fn=mock_governance,
            propagate_fn=mock_propagate,
            escalation_handler=MOCK_ESCALATION,
        )

        # === VALIDATION ===
        assert len(governance_calls) == 1, \
            f"FAIL: Expected 1 governance call, got {len(governance_calls)}"
        assert governance_calls[0] == "s1"
        assert results[0]["status"] == "COMPLETED"

        print("\n=== SUPPLEMENTARY: SEQUENTIAL GOVERNANCE ===")
        print("  ✓ Per-step governance in sequential group — PASS")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
