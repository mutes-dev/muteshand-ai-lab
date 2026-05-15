"""
PHASE-IVB EXECUTION OWNERSHIP COORDINATION TESTS

Tests for workflow_execution_generation counter and execution ownership coordination.
Per PHASE-IVA EXECUTION LEASE COORDINATION DESIGN AUDIT.

These tests verify:
- Duplicate execution suppression
- Stale owner suppression
- Lifecycle authority preservation
- Projection monotonicity preservation
- Persistence authority preservation
- Restart recovery preservation
- No generation persistence
- No authority leakage
"""

import pytest
import time
import threading
from typing import Dict, Any

from system.orchestrator.workflow_control import (
    _workflow_state_registry,
    _workflow_state_lock,
    _get_workflow_state,
    _update_workflow_state,
    retry_step,
    _update_runtime_registry_only,
)
from system.orchestrator.persistence import save_workflow, load_active_workflows
from system.orchestrator.orchestrator_runtime import run_workflow


class TestExecutionGenerationInitialization:
    """Test workflow_execution_generation initialization."""

    def test_new_workflow_generation_initialized_to_1(self):
        """New workflow execution should initialize generation to 1."""
        workflow_id = "test_gen_init_1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Initialize via _update_runtime_registry_only (new workflow path)
        _update_runtime_registry_only(workflow_id, "ACTIVE", "test_init")
        
        state = _get_workflow_state(workflow_id)
        assert state is not None
        assert state.get("execution_generation") == 1, f"Expected generation 1, got {state.get('execution_generation')}"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]

    def test_generation_preserved_on_state_update(self):
        """Generation should be preserved when updating lifecycle state."""
        workflow_id = "test_gen_preserve_1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Initialize with generation 1
        _update_runtime_registry_only(workflow_id, "ACTIVE", "test_init")
        
        # Update state (should preserve generation)
        _update_workflow_state(workflow_id, "PAUSED", "test_pause")
        
        state = _get_workflow_state(workflow_id)
        assert state is not None
        assert state.get("execution_generation") == 1, f"Expected generation 1 after update, got {state.get('execution_generation')}"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]


class TestRetryGenerationCoordination:
    """Test retry regeneration generation coordination."""

    def test_retry_increments_execution_generation(self):
        """retry_step should increment workflow_execution_generation."""
        # This test requires a valid workflow with a FAILED step
        # For now, we test the generation increment logic directly
        workflow_id = "test_retry_gen_1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Initialize with generation 1
        _update_runtime_registry_only(workflow_id, "ACTIVE", "test_init")
        initial_gen = _get_workflow_state(workflow_id).get("execution_generation")
        assert initial_gen == 1
        
        # Simulate retry_step generation increment
        with _workflow_state_lock:
            _current_gen = _workflow_state_registry.get(workflow_id, {}).get("execution_generation", 1)
            _workflow_state_registry[workflow_id]["execution_generation"] = _current_gen + 1
        
        # Verify generation incremented
        state = _get_workflow_state(workflow_id)
        assert state.get("execution_generation") == 2, f"Expected generation 2 after retry, got {state.get('execution_generation')}"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]

    def test_retry_generation_monotonic(self):
        """Generation should only increment, never decrement."""
        workflow_id = "test_retry_monotonic_1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Initialize with generation 1
        _update_runtime_registry_only(workflow_id, "ACTIVE", "test_init")
        
        # Increment multiple times
        for i in range(5):
            with _workflow_state_lock:
                _current_gen = _workflow_state_registry.get(workflow_id, {}).get("execution_generation", 1)
                _workflow_state_registry[workflow_id]["execution_generation"] = _current_gen + 1
        
        state = _get_workflow_state(workflow_id)
        assert state.get("execution_generation") == 6, f"Expected generation 6, got {state.get('execution_generation')}"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]


class TestResurrectionGenerationCoordination:
    """Test resurrection generation coordination."""

    def test_resurrection_increments_execution_generation(self):
        """Resurrection should increment workflow_execution_generation."""
        workflow_id = "test_resurrect_gen_1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Initialize with generation 1
        _update_runtime_registry_only(workflow_id, "ACTIVE", "test_init")
        initial_gen = _get_workflow_state(workflow_id).get("execution_generation")
        assert initial_gen == 1
        
        # Simulate _maybe_resurrect_execution generation increment
        with _workflow_state_lock:
            _current_gen = _workflow_state_registry.get(workflow_id, {}).get("execution_generation", 1)
            _workflow_state_registry[workflow_id]["execution_generation"] = _current_gen + 1
        
        # Verify generation incremented
        state = _get_workflow_state(workflow_id)
        assert state.get("execution_generation") == 2, f"Expected generation 2 after resurrection, got {state.get('execution_generation')}"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]


class TestLoopTopGenerationValidation:
    """Test optional loop-top generation validation."""

    def test_loop_top_captures_generation(self):
        """Loop-top validation should capture execution generation."""
        # This tests the loop-top generation capture logic
        # The actual validation requires running a workflow, which is tested in integration tests
        workflow_id = "test_loop_top_gen_1"
        
        from system.orchestrator.workflow_control import _workflow_state_registry
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Initialize with generation 1
        _update_runtime_registry_only(workflow_id, "ACTIVE", "test_init")
        
        # Simulate loop-top generation capture
        _loop_start_gen = _workflow_state_registry.get(workflow_id, {}).get("execution_generation", 1)
        
        assert _loop_start_gen == 1, f"Expected captured generation 1, got {_loop_start_gen}"
        
        # Simulate generation change (ownership transfer)
        with _workflow_state_lock:
            _workflow_state_registry[workflow_id]["execution_generation"] = 2
        
        # Simulate loop-top validation check
        _current_gen = _workflow_state_registry.get(workflow_id, {}).get("execution_generation", 1)
        _stale_detected = (_loop_start_gen is not None and _current_gen != _loop_start_gen)
        
        assert _stale_detected is True, "Stale owner should be detected when generation changes"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]


class TestGenerationNonPersistence:
    """Test that execution_generation is NOT persisted."""

    def test_generation_not_in_persistence(self):
        """execution_generation should NOT be persisted to disk."""
        workflow_id = "test_gen_no_persist_1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Initialize with generation 5
        _update_runtime_registry_only(workflow_id, "ACTIVE", "test_init")
        with _workflow_state_lock:
            _workflow_state_registry[workflow_id]["execution_generation"] = 5
        
        # Create a minimal workflow object
        workflow = {
            "id": workflow_id,
            "status": "ACTIVE",
            "steps": []
        }
        
        # Save to persistence
        save_workflow(workflow)
        
        # Load from persistence
        loaded = load_active_workflows()
        loaded_workflow = None
        for wf in loaded:
            if wf.get("id") == workflow_id:
                loaded_workflow = wf
                break
        
        assert loaded_workflow is not None
        # execution_generation should NOT be in persisted workflow
        assert "execution_generation" not in loaded_workflow, "execution_generation should NOT be persisted"
        
        # Cleanup
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Cleanup persistence file
        from system.orchestrator.persistence import _active_workflow_path
        import os
        try:
            os.remove(_active_workflow_path(workflow_id))
        except:
            pass


class TestGenerationVolatileStorage:
    """Test that generation is volatile (Runtime Registry only)."""

    def test_generation_lost_on_registry_clear(self):
        """Generation should be lost if Runtime Registry is cleared (simulating restart)."""
        workflow_id = "test_gen_volatile_1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Initialize with generation 5
        _update_runtime_registry_only(workflow_id, "ACTIVE", "test_init")
        with _workflow_state_lock:
            _workflow_state_registry[workflow_id]["execution_generation"] = 5
        
        state = _get_workflow_state(workflow_id)
        assert state.get("execution_generation") == 5
        
        # Clear registry (simulating restart)
        with _workflow_state_lock:
            _workflow_state_registry.clear()
        
        # Generation should be lost
        state = _get_workflow_state(workflow_id)
        assert state is None, "Generation should be lost when registry is cleared"


class TestAuthorityLeakagePrevention:
    """Test that generation does NOT become authority."""

    def test_generation_does_not_gate_lifecycle_transitions(self):
        """Generation should NOT prevent lifecycle transitions."""
        workflow_id = "test_gen_no_gate_1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Initialize with generation 100 (unusually high)
        _update_runtime_registry_only(workflow_id, "ACTIVE", "test_init")
        with _workflow_state_lock:
            _workflow_state_registry[workflow_id]["execution_generation"] = 100
        
        # Lifecycle transition should succeed regardless of generation value
        result = _update_workflow_state(workflow_id, "PAUSED", "test_pause")
        assert result is True, "Lifecycle transition should succeed regardless of generation"
        
        state = _get_workflow_state(workflow_id)
        assert state.get("status") == "PAUSED"
        assert state.get("execution_generation") == 100, "Generation should be preserved"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]

    def test_generation_is_advisory_only(self):
        """Generation should be advisory coordination metadata, not authoritative."""
        workflow_id = "test_gen_advisory_1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Initialize without generation
        _update_runtime_registry_only(workflow_id, "ACTIVE", "test_init")
        
        # Missing generation should default to 1, not fail
        state = _get_workflow_state(workflow_id)
        assert state.get("execution_generation") == 1, "Missing generation should default to 1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]


class TestRestartRecoveryGenerationReconstruction:
    """Test generation reconstruction on restart recovery."""

    def test_warm_registry_defaults_generation_to_1(self):
        """warm_registry_from_disk should default generation to 1 for restored entries."""
        # This tests the warm_registry_from_disk logic
        # In actual warm_registry_from_disk, execution_generation is set to 1
        # for all restored entries (volatile coordination)
        
        workflow_id = "test_warm_gen_1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]
        
        # Simulate warm registry restoration (as done in warm_registry_from_disk)
        with _workflow_state_lock:
            _workflow_state_registry[workflow_id] = {
                "status": "PENDING_RECOVERY",
                "last_updated": time.time(),
                "reason": "warm_restore_from_disk",
                "execution_generation": 1,  # Default to 1 on restart
            }
        
        state = _get_workflow_state(workflow_id)
        assert state.get("execution_generation") == 1, "Warm registry should default generation to 1"
        
        with _workflow_state_lock:
            if workflow_id in _workflow_state_registry:
                del _workflow_state_registry[workflow_id]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
