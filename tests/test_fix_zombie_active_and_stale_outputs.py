"""
CATEGORY: STABILIZATION
AUTHORITY_LAYER: Temporary Architectural Hardening
VALIDATES:
  - Zombie ACTIVE fix
  - Stale outputs fix
  - invalidate_step_outputs ordering
  - RETRY → PENDING transition
  - No zombie ACTIVE on resurrection
ENTRYPOINT: run_workflow, direct
DIRECT_INTERNAL_CALLS:
  - workflow_control internals
  - orchestrator_runtime internals
MONKEYPATCH_USAGE:
  - Various for zombie/stale testing
MOCKING_POLICY: STATE_MANIPULATION
TEST_INTENT: TEMPORARY_HARDENING
ARCHITECTURAL_SCOPE: Zombie ACTIVE and stale outputs

CREATED: 2026-04-20
STABILIZATION_REASON: Fix zombie ACTIVE and stale outputs on resurrection
GRADUATION_CRITERIA: No zombie ACTIVE steps, no stale outputs, resurrection clean

---

test_fix_zombie_active_and_stale_outputs.py

Targeted regression tests for the two minimal fixes applied to the
retry/edit resurrection deadlock.

FIX 1 — workflow_control.py:retry_step
  invalidate_step_outputs called before _invalidate_dependents / save_workflow.
  Guarantees stale context["step_outputs"] is removed before serialization.

FIX 2 — orchestrator_runtime.py PERSISTENCE RESTORE
  RETRY → PENDING (was RETRY → ACTIVE).
  Guarantees no zombie ACTIVE steps on resurrection entry to the scheduler.

CONTRACT REFERENCES
  STEP_IO_CONTRACT_V1 §6: on retry, step output AND all dependent outputs MUST be deleted.
  DEPENDENCY_MODEL_CONTRACT_V1 §10: dep-blocked steps must be re-evaluated after retry.
  STATE_TRANSITIONS_CONTRACT_V1: scheduler ACTIVE exclusion is correct and unchanged.
  LIFECYCLE_AUTHORITY_CONTRACT_V1: only _update_workflow_state writes registry.
  ORCHESTRATOR_EXECUTION_CONTRACT: run_workflow is sole executor.
"""

import time
import copy
import threading
from unittest.mock import patch, MagicMock

import pytest


# =============================================================================
# FIX 1: invalidate_step_outputs called from retry_step
# =============================================================================

class TestFix1InvaliateStepOutputs:

    def _make_workflow(self, wf_id="wf-fix1"):
        return {
            "id": wf_id,
            "name": "test",
            "status": "FAILED",
            "steps": [
                {"id": "s1", "status": "FAILED", "retries": 0, "max_retries": 3,
                 "depends_on": [], "type": "EXECUTE_API",
                 "purpose": "p", "expected_outcome": "e", "risk": "LOW",
                 "importance": "MEDIUM", "resource_targets": []},
                {"id": "s2", "status": "PENDING", "retries": 0, "max_retries": 3,
                 "depends_on": ["s1"], "type": "EXECUTE_API",
                 "purpose": "p2", "expected_outcome": "e2", "risk": "LOW",
                 "importance": "MEDIUM", "resource_targets": []},
            ],
            "context": {
                "step_outputs": {
                    "s1": {"status": "success", "data": "stale-result-divide-by-zero"},
                    "s2": {"status": "success", "data": "stale-dependent-result"},
                }
            }
        }

    def test_retry_step_clears_step_output_from_context(self):
        """
        After retry_step(wf_id, "s1"), context["step_outputs"]["s1"] MUST be absent.
        Per STEP_IO_CONTRACT_V1 §6.
        """
        from system.orchestrator.workflow_control import retry_step
        from system.orchestrator.workflow_control import (
            _workflow_state_registry, _workflow_state_lock,
        )
        wf = self._make_workflow("wf-fix1-clears")
        wf_id = wf["id"]

        # Pre-condition: stale output exists
        assert wf["context"]["step_outputs"].get("s1") is not None

        with _workflow_state_lock:
            _workflow_state_registry[wf_id] = {"status": "FAILED", "last_updated": time.time()}

        try:
            with patch("system.orchestrator.workflow_control.load_active_workflows",
                       return_value=[wf]), \
                 patch("system.orchestrator.workflow_control.save_workflow"):
                result = retry_step(wf_id, "s1")

            assert result["status"] == "success"
            # FIX 1: stale output MUST be gone
            step_outputs = wf.get("context", {}).get("step_outputs", {})
            assert "s1" not in step_outputs, (
                f"FIX 1: context['step_outputs']['s1'] must be cleared after retry_step, "
                f"got: {step_outputs}"
            )
        finally:
            with _workflow_state_lock:
                _workflow_state_registry.pop(wf_id, None)

    def test_retry_step_clears_dependent_step_outputs(self):
        """
        After retry_step(wf_id, "s1"), context["step_outputs"]["s2"] (which depends on s1)
        MUST also be absent. Per STEP_IO_CONTRACT_V1 §6.
        """
        from system.orchestrator.workflow_control import retry_step
        from system.orchestrator.workflow_control import (
            _workflow_state_registry, _workflow_state_lock,
        )
        wf = self._make_workflow("wf-fix1-deps")
        wf_id = wf["id"]

        with _workflow_state_lock:
            _workflow_state_registry[wf_id] = {"status": "FAILED", "last_updated": time.time()}

        try:
            with patch("system.orchestrator.workflow_control.load_active_workflows",
                       return_value=[wf]), \
                 patch("system.orchestrator.workflow_control.save_workflow"):
                result = retry_step(wf_id, "s1")

            assert result["status"] == "success"
            step_outputs = wf.get("context", {}).get("step_outputs", {})
            assert "s2" not in step_outputs, (
                f"FIX 1: context['step_outputs']['s2'] (dep of s1) must be cleared, "
                f"got: {step_outputs}"
            )
        finally:
            with _workflow_state_lock:
                _workflow_state_registry.pop(wf_id, None)

    def test_invalidation_order_before_save_workflow(self):
        """
        invalidate_step_outputs MUST be called before save_workflow.
        If save_workflow is called first, the stale data is already serialized.
        Verified by checking that save_workflow sees a dict without the stale entry.
        """
        from system.orchestrator.workflow_control import retry_step
        from system.orchestrator.workflow_control import (
            _workflow_state_registry, _workflow_state_lock,
        )
        wf = self._make_workflow("wf-fix1-order")
        wf_id = wf["id"]

        saved_contexts = []

        def capturing_save(w):
            saved_contexts.append(
                copy.deepcopy(w.get("context", {}).get("step_outputs", {}))
            )
            return {"status": "success"}

        with _workflow_state_lock:
            _workflow_state_registry[wf_id] = {"status": "FAILED", "last_updated": time.time()}

        try:
            with patch("system.orchestrator.workflow_control.load_active_workflows",
                       return_value=[wf]), \
                 patch("system.orchestrator.workflow_control.save_workflow",
                       side_effect=capturing_save):
                retry_step(wf_id, "s1")

            assert saved_contexts, "save_workflow must have been called"
            # The context at save time must NOT contain the stale s1 output
            assert "s1" not in saved_contexts[0], (
                f"FIX 1: stale output must be gone BEFORE save_workflow is called, "
                f"but save saw: {saved_contexts[0]}"
            )
        finally:
            with _workflow_state_lock:
                _workflow_state_registry.pop(wf_id, None)

    def test_step_level_fields_also_cleared(self):
        """
        Existing behavior must be preserved: step['execution_result'] and step['output']
        are still cleared (these are NOT removed by Fix 1, Fix 1 adds context clearing).
        """
        from system.orchestrator.workflow_control import retry_step
        from system.orchestrator.workflow_control import (
            _workflow_state_registry, _workflow_state_lock,
        )
        wf = self._make_workflow("wf-fix1-stepfields")
        wf_id = wf["id"]
        wf["steps"][0]["execution_result"] = {"status": "failure", "reason": "division_by_zero"}
        wf["steps"][0]["output"] = "error"

        with _workflow_state_lock:
            _workflow_state_registry[wf_id] = {"status": "FAILED", "last_updated": time.time()}

        try:
            with patch("system.orchestrator.workflow_control.load_active_workflows",
                       return_value=[wf]), \
                 patch("system.orchestrator.workflow_control.save_workflow"):
                retry_step(wf_id, "s1")

            s1 = next(s for s in wf["steps"] if s["id"] == "s1")
            assert "execution_result" not in s1, "step['execution_result'] must be cleared"
            assert "output" not in s1, "step['output'] must be cleared"
        finally:
            with _workflow_state_lock:
                _workflow_state_registry.pop(wf_id, None)


# =============================================================================
# FIX 2: PERSISTENCE RESTORE — RETRY → PENDING (not ACTIVE)
# =============================================================================

class TestFix2PersistenceRestoreRetryToPending:

    def _make_wf(self, wf_id, s1_status="RETRY", s2_status="PENDING"):
        base = {
            "type": "EXECUTE_API", "purpose": "test", "expected_outcome": "done",
            "risk": "LOW", "importance": "MEDIUM", "resource_targets": [],
            "retries": 0, "max_retries": 3, "depends_on": [],
        }
        return {
            "id": wf_id,
            "name": "test",
            "status": "ACTIVE",
            "steps": [
                {**base, "id": "s1", "status": s1_status},
                {**base, "id": "s2", "status": s2_status, "depends_on": ["s1"]},
            ]
        }

    def test_retry_step_becomes_pending_after_persistence_restore(self):
        """
        FIX 2: PERSISTENCE RESTORE must convert RETRY → PENDING.
        A RETRY step in the persisted file represents a pending re-execution request,
        not an actively running step. ACTIVE was a zombie state.
        """
        import json
        from unittest.mock import mock_open
        from system.orchestrator.orchestrator_runtime import run_workflow
        from system.orchestrator.workflow_control import (
            _workflow_state_registry, _workflow_state_lock,
        )
        wf_id = "wf-fix2-pending"
        wf = self._make_wf(wf_id, s1_status="RETRY")
        persisted_wf = copy.deepcopy(wf)

        with _workflow_state_lock:
            _workflow_state_registry[wf_id] = {"status": "ACTIVE", "last_updated": time.time()}

        captured = {}

        def fake_group(workflow, step_states, conflict_detector, workflow_id):
            for s in workflow.get("steps", []):
                captured[s["id"]] = s["status"]
            return None

        try:
            # Persistence restore reads from file via builtins.open.
            # Use side_effect to intercept only the workflow JSON path.
            _real_open = open
            wf_json = json.dumps(persisted_wf)

            def _open_side_effect(path, *args, **kwargs):
                if isinstance(path, str) and wf_id in path and path.endswith(".json"):
                    return mock_open(read_data=wf_json)()
                return _real_open(path, *args, **kwargs)

            with patch("system.orchestrator.orchestrator_runtime.create_execution_group",
                       side_effect=fake_group), \
                 patch("system.orchestrator.orchestrator_runtime.save_workflow"), \
                 patch("builtins.open", side_effect=_open_side_effect), \
                 patch("system.orchestrator.workflow_control.save_workflow"):
                run_workflow(wf)

            assert captured.get("s1") == "PENDING", (
                f"FIX 2: RETRY must become PENDING after PERSISTENCE RESTORE, "
                f"got {captured.get('s1')!r}"
            )
        finally:
            with _workflow_state_lock:
                _workflow_state_registry.pop(wf_id, None)

    def test_no_zombie_active_state_after_persistence_restore(self):
        """
        FIX 2: After PERSISTENCE RESTORE, no step that was RETRY should be ACTIVE.
        ACTIVE without executor ownership is a zombie that deadlocks the scheduler.
        """
        import json
        from unittest.mock import mock_open
        from system.orchestrator.orchestrator_runtime import run_workflow
        from system.orchestrator.workflow_control import (
            _workflow_state_registry, _workflow_state_lock,
        )
        wf_id = "wf-fix2-nozombie"
        wf = self._make_wf(wf_id, s1_status="RETRY")
        persisted_wf = copy.deepcopy(wf)

        with _workflow_state_lock:
            _workflow_state_registry[wf_id] = {"status": "ACTIVE", "last_updated": time.time()}

        captured = {}

        def fake_group(workflow, step_states, conflict_detector, workflow_id):
            for s in workflow.get("steps", []):
                captured[s["id"]] = s["status"]
            return None

        try:
            # Persistence restore reads from file via builtins.open.
            _real_open = open
            wf_json = json.dumps(persisted_wf)

            def _open_side_effect(path, *args, **kwargs):
                if isinstance(path, str) and wf_id in path and path.endswith(".json"):
                    return mock_open(read_data=wf_json)()
                return _real_open(path, *args, **kwargs)

            with patch("system.orchestrator.orchestrator_runtime.create_execution_group",
                       side_effect=fake_group), \
                 patch("system.orchestrator.orchestrator_runtime.save_workflow"), \
                 patch("builtins.open", side_effect=_open_side_effect), \
                 patch("system.orchestrator.workflow_control.save_workflow"):
                run_workflow(wf)

            zombie_active = [
                sid for sid, st in captured.items()
                if st == "ACTIVE"
                and not any(s.get("_approval_resumed") or s.get("_retry_pending")
                            for s in wf["steps"] if s.get("id") == sid)
            ]
            assert zombie_active == [], (
                f"FIX 2: No zombie ACTIVE steps allowed after PERSISTENCE RESTORE. "
                f"Zombie steps: {zombie_active}, all statuses: {captured}"
            )
        finally:
            with _workflow_state_lock:
                _workflow_state_registry.pop(wf_id, None)

    def test_pending_retry_step_accepted_as_scheduler_candidate(self):
        """
        After Fix 2, RETRY step enters scheduler as PENDING.
        PENDING is in the scheduler's candidate set → group forms → no deadlock.
        """
        from system.orchestrator.execution_scheduler import create_execution_group
        from system.orchestrator.conflict_detector import ConflictDetector

        wf = {
            "id": "wf-fix2-sched",
            "status": "ACTIVE",
            "steps": [
                {"id": "s1", "status": "PENDING",   # RETRY→PENDING after PERSISTENCE RESTORE
                 "depends_on": [], "resource_targets": [],
                 "type": "EXECUTE_API", "risk": "LOW", "retries": 0, "max_retries": 3},
            ]
        }
        step_states = {"s1": "PENDING"}
        cd = ConflictDetector()
        cd.register_workflow("wf-fix2-sched")

        group = create_execution_group(wf, step_states, cd, "wf-fix2-sched")

        assert group is not None, (
            "Scheduler must form a group for PENDING step (post-Fix2 RETRY→PENDING)"
        )
        assert "s1" in group["steps"]

    def test_scheduler_active_exclusion_unchanged(self):
        """
        CONTRACT INVARIANT: scheduler's ACTIVE exclusion is correct and must NOT change.
        A plain ACTIVE step (no _approval_resumed, no _retry_pending) must still be
        excluded from candidates — Fix 2 does NOT change this behavior.
        """
        from system.orchestrator.execution_scheduler import create_execution_group
        from system.orchestrator.conflict_detector import ConflictDetector

        wf = {
            "id": "wf-fix2-active-excl",
            "status": "ACTIVE",
            "steps": [
                {"id": "s1", "status": "ACTIVE",    # running — must NOT be re-dispatched
                 "depends_on": [], "resource_targets": [],
                 "type": "EXECUTE_API", "risk": "LOW", "retries": 0, "max_retries": 3},
            ]
        }
        step_states = {"s1": "ACTIVE"}
        cd = ConflictDetector()
        cd.register_workflow("wf-fix2-active-excl")

        group = create_execution_group(wf, step_states, cd, "wf-fix2-active-excl")

        # ACTIVE step running + no other candidates → no group formed (active_steps guard)
        # Actually: s1 is not in candidate_steps (ACTIVE not in "PENDING","RETRY","BLOCKED")
        # AND s1 is in active_steps list → even if something else was pending, no new group.
        # Result: None because no candidates AND active_steps exist.
        assert group is None, (
            "ACTIVE step without _approval_resumed/_retry_pending must NOT form a group "
            "(scheduler ACTIVE exclusion must be preserved)"
        )

    def test_dependency_unblocks_after_pending_retry_step_completes(self):
        """
        Integration: after Fix 2, s1 (RETRY→PENDING) is dispatched, completes.
        s2 (depends_on=[s1]) must then be schedulable.
        """
        from system.orchestrator.execution_scheduler import create_execution_group
        from system.orchestrator.conflict_detector import ConflictDetector

        # Simulate state AFTER s1 has completed (post-execution)
        wf = {
            "id": "wf-fix2-depunblock",
            "status": "ACTIVE",
            "steps": [
                {"id": "s1", "status": "COMPLETED",
                 "depends_on": [], "resource_targets": [],
                 "type": "EXECUTE_API", "risk": "LOW", "retries": 0, "max_retries": 3},
                {"id": "s2", "status": "PENDING",
                 "depends_on": ["s1"], "resource_targets": [],
                 "type": "EXECUTE_API", "risk": "LOW", "retries": 0, "max_retries": 3},
            ]
        }
        step_states = {"s1": "COMPLETED", "s2": "PENDING"}
        cd = ConflictDetector()
        cd.register_workflow("wf-fix2-depunblock")

        group = create_execution_group(wf, step_states, cd, "wf-fix2-depunblock")

        assert group is not None, "s2 must be schedulable once s1 is COMPLETED"
        assert "s2" in group["steps"]


# =============================================================================
# Regression: escalation in-thread retry path unaffected
# =============================================================================

class TestEscalationRetryPathUnaffected:

    def test_parallel_executor_calls_invalidate_step_outputs_independently(self):
        """
        parallel_executor.py:357 calls invalidate_step_outputs via the escalation path.
        Fix 1 adds a second call from retry_step (user-triggered).
        Both must coexist — invalidate_step_outputs is idempotent (pop on missing key is safe).
        """
        from system.orchestrator.memory_controller import invalidate_step_outputs

        wf = {
            "id": "wf-esc-idemp",
            "steps": [
                {"id": "s1", "depends_on": []},
                {"id": "s2", "depends_on": ["s1"]},
            ],
            "context": {
                "step_outputs": {
                    "s1": {"status": "success", "data": "result"},
                    "s2": {"status": "success", "data": "dep-result"},
                }
            }
        }

        # First call (escalation path)
        invalidate_step_outputs(wf, "s1")
        assert "s1" not in wf["context"]["step_outputs"]
        assert "s2" not in wf["context"]["step_outputs"]

        # Second call (user retry path / Fix 1) — must not raise, must be idempotent
        invalidate_step_outputs(wf, "s1")
        assert "s1" not in wf["context"]["step_outputs"]
        assert "s2" not in wf["context"]["step_outputs"]

    def test_escalation_handle_retry_sets_active_directly_on_live_step(self):
        """
        escalation_controller.handle_retry transitions step to ACTIVE directly on the
        live step dict during in-thread execution. It does NOT go through PERSISTENCE
        RESTORE. Fix 2 (RETRY→PENDING in PERSISTENCE RESTORE) does not affect this path.
        """
        from system.orchestrator.escalation_controller import handle_retry

        step = {
            "id": "s1", "status": "RETRY", "retries": 1, "max_retries": 3,
            "input": "divide 10 by 2",
            "type": "EXECUTE_API", "purpose": "p", "expected_outcome": "e",
            "risk": "LOW", "importance": "MEDIUM", "resource_targets": [],
            "depends_on": [],
        }
        wf = {"id": "wf-esc-live", "steps": [step]}

        result = handle_retry(step, wf, next_decision="retry")

        # handle_retry mutates step in-place: step["status"] = "ACTIVE"
        # It returns {"action": "RETRY"} (not a status dict).
        # Verify the in-place mutation — escalation path unchanged by Fix 2.
        assert step["status"] == "ACTIVE", (
            f"escalation handle_retry must set step['status'] = 'ACTIVE' directly, "
            f"got {step.get('status')!r}"
        )
        assert result.get("action") == "RETRY", (
            f"handle_retry return action must be 'RETRY', got {result!r}"
        )
        assert "blocked_reason" not in step, (
            "escalation handle_retry must not carry blocked_reason on ACTIVE step"
        )


# =============================================================================
# Regression: pause/resume unaffected
# =============================================================================

class TestPauseResumeUnaffected:

    def test_paused_step_restore_unchanged(self):
        """
        PERSISTENCE RESTORE for PAUSED workflow: workflow["status"] = PAUSED → early exit.
        Fix 2 only touches the RETRY branch. PAUSED guard is unaffected.
        """
        from system.orchestrator.orchestrator_runtime import run_workflow
        from system.orchestrator.workflow_control import (
            _workflow_state_registry, _workflow_state_lock,
        )
        wf_id = "wf-fix2-paused-unchanged"
        wf = {
            "id": wf_id, "name": "test", "status": "ACTIVE",
            "steps": [
                {"id": "s1", "status": "PENDING", "depends_on": [], "retries": 0,
                 "max_retries": 3, "type": "EXECUTE_API", "purpose": "p",
                 "expected_outcome": "e", "risk": "LOW", "importance": "MEDIUM",
                 "resource_targets": []},
            ]
        }
        # Registry says PAUSED — run_workflow must return early (pause guard)
        with _workflow_state_lock:
            _workflow_state_registry[wf_id] = {"status": "PAUSED", "last_updated": time.time()}

        try:
            result = run_workflow(wf)
            assert result.get("status") in ("control", "success"), (
                f"PAUSED workflow must return control/paused, got {result}"
            )
        finally:
            with _workflow_state_lock:
                _workflow_state_registry.pop(wf_id, None)
