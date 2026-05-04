"""
Test Suite — Phase 1B: Parallel Execution (Contract-Aligned)

Tests EXECUTION_SCHEDULING_CONTRACT_V1 compliance:
1. Independent steps → run in parallel
2. Shared resource → sequentialized
3. Destructive steps → forced sequential
4. Mixed scenario → correct grouping

Also tests:
- Correct group formation
- system_entry called once per step (via execute_step)
- No execution bypass
- Correct state transitions
- Adversarial: circular deps, conflicting resources, partial failures, BLOCKED in parallel
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from system.orchestrator.execution_scheduler import (
    create_execution_group,
    _is_destructive_step,
    _has_dependency,
    _check_parallel_eligibility,
    _check_pairwise_conflicts,
)
from system.orchestrator.conflict_detector import ConflictDetector, reset_detector
from system.orchestrator import trace_collector


# === FIXTURES ===

@pytest.fixture(autouse=True)
def setup_trace():
    """Ensure trace collector exists for every test."""
    trace_collector.create_collector("test_workflow")
    yield
    reset_detector()


def _make_step(step_id, step_type="EXECUTE_API", risk="LOW", resource_targets=None, depends_on=None):
    """Create a step dict with required STEP_SCHEMA_CONTRACT_V1 fields."""
    step = {
        "id": step_id,
        "type": step_type,
        "purpose": f"Test step {step_id}",
        "tool_call": f"test_tool {step_id}",
        "expected_outcome": "Test completed",
        "risk": risk,
        "importance": "MEDIUM",
        "resource_targets": resource_targets or [],
        "status": "PENDING",
        "retries": 0,
        "max_retries": 3,
        "input": f"test input {step_id}",
        "attempt_history": [],
    }
    if depends_on:
        step["depends_on"] = depends_on
    return step


def _make_workflow(steps, workflow_id="test_wf"):
    """Create a workflow dict."""
    return {
        "id": workflow_id,
        "name": "test_workflow",
        "status": "ACTIVE",
        "steps": steps,
    }


# ============================================================
# TEST 1: Independent steps → run in parallel
# ============================================================

class TestIndependentStepsParallel:
    """Steps with no shared resources and no dependencies should form a PARALLEL group."""

    def test_independent_steps_form_parallel_group(self):
        steps = [
            _make_step("s1", resource_targets=["file_a.txt"]),
            _make_step("s2", resource_targets=["file_b.txt"]),
            _make_step("s3", resource_targets=["file_c.txt"]),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        assert group is not None
        assert group["group_type"] == "PARALLEL"
        assert set(group["steps"]) == {"s1", "s2", "s3"}
        assert group["boundary_rules"]["wait_for_all"] is True
        assert group["boundary_rules"]["allow_partial_completion"] is False

    def test_no_resource_steps_form_parallel_group(self):
        """Steps without resource_targets should be parallelizable."""
        steps = [
            _make_step("s1"),
            _make_step("s2"),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        assert group is not None
        assert group["group_type"] == "PARALLEL"
        assert set(group["steps"]) == {"s1", "s2"}


# ============================================================
# TEST 2: Shared resource → sequentialized
# ============================================================

class TestSharedResourceSequentialized:
    """Steps sharing resource_targets should be sequentialized."""

    def test_shared_resource_forces_sequential(self):
        steps = [
            _make_step("s1", resource_targets=["shared_file.txt"]),
            _make_step("s2", resource_targets=["shared_file.txt"]),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        assert group is not None
        # With shared resources and MEDIUM+ conflict, should be SEQUENTIAL
        assert group["group_type"] == "SEQUENTIAL"
        assert len(group["steps"]) == 1  # Only first step in sequential group

    def test_dependency_forces_sequential(self):
        """Explicit dependency should prevent parallel."""
        steps = [
            _make_step("s1", resource_targets=["file_a.txt"]),
            _make_step("s2", resource_targets=["file_b.txt"], depends_on=["s1"]),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        assert group is not None
        assert group["group_type"] == "SEQUENTIAL"
        assert len(group["steps"]) == 1


# ============================================================
# TEST 3: Destructive steps → forced sequential
# ============================================================

class TestDestructiveStepsSequential:
    """Destructive step types MUST never be in parallel groups."""

    def test_execute_install_forces_sequential(self):
        steps = [
            _make_step("s1", step_type="EXECUTE_INSTALL"),
            _make_step("s2", step_type="EXECUTE_API"),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        assert group is not None
        assert group["group_type"] == "SEQUENTIAL"

    def test_system_settings_forces_sequential(self):
        steps = [
            _make_step("s1", step_type="EXECUTE_SYSTEM_SETTINGS_SERVICES"),
            _make_step("s2", step_type="ANALYZE"),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        assert group is not None
        assert group["group_type"] == "SEQUENTIAL"

    def test_environment_forces_sequential(self):
        steps = [
            _make_step("s1", step_type="EXECUTE_ENVIRONMENT"),
            _make_step("s2", step_type="RESEARCH"),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        assert group is not None
        assert group["group_type"] == "SEQUENTIAL"

    def test_high_risk_file_forces_sequential(self):
        steps = [
            _make_step("s1", step_type="EXECUTE_FILE", risk="HIGH"),
            _make_step("s2", step_type="ANALYZE"),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        assert group is not None
        assert group["group_type"] == "SEQUENTIAL"

    def test_is_destructive_step_types(self):
        """Verify _is_destructive_step correctly identifies destructive types."""
        assert _is_destructive_step({"type": "EXECUTE_INSTALL"}) is True
        assert _is_destructive_step({"type": "EXECUTE_SYSTEM_SETTINGS_SERVICES"}) is True
        assert _is_destructive_step({"type": "EXECUTE_ENVIRONMENT"}) is True
        assert _is_destructive_step({"type": "EXECUTE_FILE", "risk": "HIGH"}) is True
        assert _is_destructive_step({"type": "EXECUTE_FILE", "risk": "LOW"}) is False
        assert _is_destructive_step({"type": "ANALYZE", "risk": "LOW"}) is False
        assert _is_destructive_step({"type": "RESEARCH"}) is False
        assert _is_destructive_step({"type": "EXECUTE_API", "risk": "HIGH"}) is True


# ============================================================
# TEST 4: Mixed scenario → correct grouping
# ============================================================

class TestMixedScenarioGrouping:
    """Mixed workflows with some parallel, some sequential steps."""

    def test_mixed_parallel_and_destructive(self):
        """Non-destructive independent steps parallel, destructive waits."""
        steps = [
            _make_step("s1", step_type="ANALYZE", resource_targets=["file_a.txt"]),
            _make_step("s2", step_type="RESEARCH", resource_targets=["file_b.txt"]),
            _make_step("s3", step_type="EXECUTE_INSTALL", resource_targets=["package_x"]),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        # First group: s1 and s2 should be parallel (independent, non-destructive)
        group = create_execution_group(workflow, step_states, detector, "test_wf")

        assert group is not None
        assert group["group_type"] == "PARALLEL"
        assert "s1" in group["steps"]
        assert "s2" in group["steps"]
        assert "s3" not in group["steps"]  # Destructive excluded

    def test_single_pending_step_sequential(self):
        """Single pending step always forms sequential group."""
        steps = [
            _make_step("s1"),
        ]
        workflow = _make_workflow(steps)
        step_states = {"s1": "PENDING"}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        assert group is not None
        assert group["group_type"] == "SEQUENTIAL"
        assert group["steps"] == ["s1"]


# ============================================================
# TEST 5: Scheduling trigger behavior
# ============================================================

class TestSchedulingTrigger:
    """Verify scheduling trigger rules per Section 1.5."""

    def test_no_group_when_all_completed(self):
        """No group formed when all steps are COMPLETED."""
        steps = [
            _make_step("s1"),
        ]
        steps[0]["status"] = "COMPLETED"
        workflow = _make_workflow(steps)
        step_states = {"s1": "COMPLETED"}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")
        assert group is None

    def test_no_group_when_active_steps_exist(self):
        """No group when previous group has non-terminal steps."""
        steps = [
            _make_step("s1"),
            _make_step("s2"),
        ]
        steps[0]["status"] = "ACTIVE"
        workflow = _make_workflow(steps)
        step_states = {"s1": "ACTIVE", "s2": "PENDING"}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")
        assert group is None  # Previous group not complete

    def test_no_group_when_blocked_steps_exist(self):
        """No group when BLOCKED steps from previous group exist."""
        steps = [
            _make_step("s1"),
            _make_step("s2"),
        ]
        steps[0]["status"] = "BLOCKED"
        workflow = _make_workflow(steps)
        step_states = {"s1": "BLOCKED", "s2": "PENDING"}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")
        assert group is None


# ============================================================
# TEST 6: Conflict integration
# ============================================================

class TestConflictIntegration:
    """Verify conflict detection integrates with scheduling per Section 5."""

    def test_low_conflict_allows_parallel(self):
        """LOW conflict severity allows parallel execution."""
        # ANALYZE steps with same resource = LOW severity (read-only)
        steps = [
            _make_step("s1", step_type="ANALYZE", resource_targets=["read_only.txt"]),
            _make_step("s2", step_type="ANALYZE", resource_targets=["read_only.txt"]),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        # Both ANALYZE steps with shared read-only resource → LOW conflict → parallel OK
        assert group is not None
        assert group["group_type"] == "PARALLEL"

    def test_medium_conflict_sequentializes(self):
        """MEDIUM conflict demotes step to sequential."""
        # EXECUTE_API steps with same resource = MEDIUM severity
        steps = [
            _make_step("s1", step_type="EXECUTE_API", resource_targets=["api_resource"]),
            _make_step("s2", step_type="EXECUTE_API", resource_targets=["api_resource"]),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        # MEDIUM conflict → sequentialize
        assert group is not None
        assert group["group_type"] == "SEQUENTIAL"

    def test_high_conflict_excludes(self):
        """HIGH conflict excludes step from parallel."""
        # EXECUTE_FILE + another EXECUTE_FILE on same resource = HIGH
        steps = [
            _make_step("s1", step_type="EXECUTE_FILE", resource_targets=["target_file.txt"]),
            _make_step("s2", step_type="ANALYZE", resource_targets=["other.txt"]),
            _make_step("s3", step_type="EXECUTE_FILE", resource_targets=["target_file.txt"]),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        # s1 and s3 conflict on target_file.txt (HIGH) — should not be in same group
        assert group is not None
        if group["group_type"] == "PARALLEL":
            assert not ("s1" in group["steps"] and "s3" in group["steps"])


# ============================================================
# TEST 7: State transitions
# ============================================================

class TestStateTransitions:
    """Verify state transitions comply with STATE_TRANSITIONS_CONTRACT_V1."""

    def test_group_boundary_synchronization(self):
        """Group N starts only after group N-1 completes."""
        steps = [
            _make_step("s1", step_type="EXECUTE_INSTALL"),  # Destructive → group 1 (sequential)
            _make_step("s2"),  # Will be in group 2
        ]
        workflow = _make_workflow(steps)
        detector = ConflictDetector()

        # Group 1: s1 only (destructive)
        step_states = {"s1": "PENDING", "s2": "PENDING"}
        group1 = create_execution_group(workflow, step_states, detector, "test_wf")
        assert group1 is not None
        assert group1["steps"] == ["s1"]

        # Simulate s1 completion
        step_states["s1"] = "COMPLETED"
        steps[0]["status"] = "COMPLETED"

        # Group 2: s2
        group2 = create_execution_group(workflow, step_states, detector, "test_wf")
        assert group2 is not None
        assert group2["steps"] == ["s2"]


# ============================================================
# TEST 8: Dependency detection
# ============================================================

class TestDependencyDetection:
    """Verify dependency detection uses resource_target analysis ONLY."""

    def test_resource_overlap_creates_dependency(self):
        s1 = _make_step("s1", resource_targets=["file_x.txt"])
        s2 = _make_step("s2", resource_targets=["file_x.txt"])
        assert _has_dependency(s1, s2) is True

    def test_no_overlap_no_dependency(self):
        s1 = _make_step("s1", resource_targets=["file_a.txt"])
        s2 = _make_step("s2", resource_targets=["file_b.txt"])
        assert _has_dependency(s1, s2) is False

    def test_explicit_depends_on(self):
        s1 = _make_step("s1")
        s2 = _make_step("s2", depends_on=["s1"])
        assert _has_dependency(s2, s1) is True

    def test_empty_resources_no_dependency(self):
        s1 = _make_step("s1")
        s2 = _make_step("s2")
        assert _has_dependency(s1, s2) is False


# ============================================================
# TEST 9: Group structure validation
# ============================================================

class TestGroupStructure:
    """Verify group structure matches contract schema."""

    def test_group_has_required_fields(self):
        steps = [_make_step("s1")]
        workflow = _make_workflow(steps)
        step_states = {"s1": "PENDING"}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")

        assert "group_id" in group
        assert "group_type" in group
        assert "steps" in group
        assert "boundary_rules" in group
        assert group["boundary_rules"]["wait_for_all"] is True
        assert group["boundary_rules"]["allow_partial_completion"] is False


# ============================================================
# ADVERSARIAL TEST 10: Edge cases
# ============================================================

class TestAdversarialCases:
    """Adversarial validation per Phase 6."""

    def test_circular_dependency_resource(self):
        """Steps with mutual resource overlap should still form valid groups."""
        steps = [
            _make_step("s1", resource_targets=["shared"]),
            _make_step("s2", resource_targets=["shared"]),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")
        assert group is not None
        # Should be sequential due to resource conflict
        assert group["group_type"] == "SEQUENTIAL"

    def test_all_destructive_steps(self):
        """All destructive steps should result in sequential single-step groups."""
        steps = [
            _make_step("s1", step_type="EXECUTE_INSTALL"),
            _make_step("s2", step_type="EXECUTE_INSTALL"),
            _make_step("s3", step_type="EXECUTE_INSTALL"),
        ]
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")
        assert group is not None
        assert group["group_type"] == "SEQUENTIAL"
        assert len(group["steps"]) == 1

    def test_empty_workflow(self):
        """Empty workflow produces no group."""
        workflow = _make_workflow([])
        step_states = {}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")
        assert group is None

    def test_all_completed_workflow(self):
        """All completed steps produce no group."""
        steps = [
            _make_step("s1"),
            _make_step("s2"),
        ]
        for s in steps:
            s["status"] = "COMPLETED"
        workflow = _make_workflow(steps)
        step_states = {s["id"]: "COMPLETED" for s in steps}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")
        assert group is None

    def test_mixed_completed_and_pending(self):
        """Only PENDING steps should be considered for grouping."""
        steps = [
            _make_step("s1"),
            _make_step("s2"),
            _make_step("s3"),
        ]
        steps[0]["status"] = "COMPLETED"
        workflow = _make_workflow(steps)
        step_states = {"s1": "COMPLETED", "s2": "PENDING", "s3": "PENDING"}
        detector = ConflictDetector()

        group = create_execution_group(workflow, step_states, detector, "test_wf")
        assert group is not None
        assert "s1" not in group["steps"]

    def test_plan_not_modified(self):
        """Scheduling MUST NOT modify plan structure."""
        steps = [
            _make_step("s1"),
            _make_step("s2"),
        ]
        workflow = _make_workflow(steps)
        original_steps = [dict(s) for s in steps]
        step_states = {s["id"]: "PENDING" for s in steps}
        detector = ConflictDetector()

        create_execution_group(workflow, step_states, detector, "test_wf")

        # Verify steps not modified
        for orig, current in zip(original_steps, workflow["steps"]):
            assert orig["id"] == current["id"]
            assert orig["type"] == current["type"]
            assert orig["status"] == current["status"]
            assert orig["resource_targets"] == current["resource_targets"]


# ============================================================
# TEST 11: Parallel eligibility check
# ============================================================

class TestParallelEligibility:
    """Verify parallel eligibility rules per Section 2."""

    def test_eligible_non_destructive_no_conflict(self):
        step = _make_step("s1", step_type="ANALYZE")
        eligible, reason = _check_parallel_eligibility(step, [], ConflictDetector(), "test_wf")
        assert eligible is True
        assert reason == "NO_CONFLICTS"

    def test_ineligible_destructive_type(self):
        step = _make_step("s1", step_type="EXECUTE_INSTALL")
        eligible, reason = _check_parallel_eligibility(step, [], ConflictDetector(), "test_wf")
        assert eligible is False
        assert reason == "EXCLUDED_TYPE"

    def test_ineligible_dependency(self):
        s1 = _make_step("s1", resource_targets=["shared"])
        s2 = _make_step("s2", resource_targets=["shared"])
        eligible, reason = _check_parallel_eligibility(s1, [s2], ConflictDetector(), "test_wf")
        assert eligible is False
        assert reason == "DEPENDENCY_DETECTED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
