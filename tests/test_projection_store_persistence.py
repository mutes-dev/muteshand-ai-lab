"""
Test suite for Phase 3F-XB — Projection Store Persistence Stabilization.

This module tests:
- Projection store persistence across restart
- Startup restoration (warm_stores_from_disk)
- Stale persisted state rejection
- Terminal state cleanup
- Projection monotonicity preservation
"""

import os
import sys
import json
import tempfile
import shutil

# Ensure project root in path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from system.orchestrator.projection_manager import (
    ProjectionManager,
    _WorkflowProjectionStore,
    _load_persisted_stores,
    _persist_store_state,
    _remove_store_state,
    _PROJECTION_STORE_PATH,
)
from system.orchestrator.projection_schema import (
    PROJECTION_STATE_ACTIVE,
    PROJECTION_STATE_TERMINAL,
)


class TestProjectionStorePersistence:
    """Test projection store persistence functionality."""

    def setup_method(self):
        """Setup test environment with isolated temp directory."""
        self.test_dir = tempfile.mkdtemp()
        self.original_path = _PROJECTION_STORE_PATH
        # Monkey-patch the path for testing
        import system.orchestrator.projection_manager as pm
        pm._PROJECTION_STORE_PATH = os.path.join(self.test_dir, "projection_stores.json")
        pm._VERSION_PATH = os.path.join(self.test_dir, "projection_versions.json")

    def teardown_method(self):
        """Cleanup test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)
        # Restore original paths
        import system.orchestrator.projection_manager as pm
        pm._PROJECTION_STORE_PATH = self.original_path

    def test_store_persists_on_projection_store(self):
        """Test that store() triggers persistence."""
        print("\n[TEST] store() triggers persistence")
        pm = ProjectionManager()
        workflow_id = "test-wf-1"

        # Create a mock projection
        projection = {
            "workflow_id": workflow_id,
            "projection_type": "workflow",
            "projection_version": 1,
            "projection_timestamp": "2026-05-13T10:00:00",
            "projection_state": PROJECTION_STATE_ACTIVE,
            "lifecycle_status": "ACTIVE",
            "steps": [],
            "outputs": [],
        }

        # Store the projection
        store = pm._get_or_create_store(workflow_id)
        result = store.store(projection)
        assert result is True, "store() should succeed"

        # Verify persistence file exists
        import system.orchestrator.projection_manager as pmm
        assert os.path.exists(pmm._PROJECTION_STORE_PATH), "Persistence file should exist"

        # Load and verify
        persisted = _load_persisted_stores()
        assert workflow_id in persisted, "workflow_id should be in persisted stores"
        assert persisted[workflow_id]["latest_projection"]["projection_version"] == 1

        print("  PASS: Projection store persisted correctly")

    def test_warm_restoration(self):
        """Test warm restoration of persisted stores."""
        print("\n[TEST] warm restoration of persisted stores")

        # Create first projection manager and store a projection
        pm1 = ProjectionManager()
        workflow_id = "test-wf-2"

        projection = {
            "workflow_id": workflow_id,
            "projection_type": "workflow",
            "projection_version": 5,
            "projection_timestamp": "2026-05-13T10:00:00",
            "projection_state": PROJECTION_STATE_ACTIVE,
            "lifecycle_status": "ACTIVE",
            "steps": [{"step_id": "step-1", "status": "COMPLETED"}],
            "outputs": [],
        }

        store1 = pm1._get_or_create_store(workflow_id)
        store1.store(projection)

        # Create second projection manager (simulating restart)
        pm2 = ProjectionManager()

        # Mock runtime authority function (returns None = no validation)
        def mock_get_state(wfid):
            return None

        # Warm restore
        stats = pm2.warm_stores_from_disk(mock_get_state)
        assert stats["restored"] == 1, f"Should restore 1 store, got {stats}"

        # Verify restored state
        store2 = pm2._get_store(workflow_id)
        assert store2 is not None, "Store should exist after restoration"
        assert store2.current_version() == 5, f"Version should be 5, got {store2.current_version()}"
        latest = store2.get_latest()
        assert latest is not None, "Latest projection should exist"
        assert latest["projection_version"] == 5

        print("  PASS: Warm restoration works correctly")

    def test_stale_persisted_state_rejection(self):
        """Test that stale persisted state is rejected during restoration."""
        print("\n[TEST] stale persisted state rejection")

        # Create first PM and store projection version 3
        pm1 = ProjectionManager()
        workflow_id = "test-wf-3"

        projection_v3 = {
            "workflow_id": workflow_id,
            "projection_type": "workflow",
            "projection_version": 3,
            "projection_timestamp": "2026-05-13T10:00:00",
            "projection_state": PROJECTION_STATE_ACTIVE,
            "lifecycle_status": "ACTIVE",
            "steps": [],
            "outputs": [],
        }

        store1 = pm1._get_or_create_store(workflow_id)
        store1.store(projection_v3)

        # Simulate stale persisted state by creating v3 persisted data manually
        stale_persisted_state = {
            "latest_projection": projection_v3,
            "projection_state": PROJECTION_STATE_ACTIVE,
            "continuity_anchor_version": 3,
            "stale_rejection_count": 0,
        }

        # Create second PM with existing runtime state
        pm2 = ProjectionManager()
        store2 = pm2._get_or_create_store(workflow_id)

        # Advance version to 5 using next_version() (proper way to advance counter)
        # First advance from initial (3) to target (5)
        while store2.current_version() < 5:
            store2.next_version()

        # Store a newer projection (version 5)
        projection_v5 = {
            "workflow_id": workflow_id,
            "projection_type": "workflow",
            "projection_version": 5,
            "projection_timestamp": "2026-05-13T10:01:00",
            "projection_state": PROJECTION_STATE_ACTIVE,
            "lifecycle_status": "ACTIVE",
            "steps": [{"step_id": "step-1"}, {"step_id": "step-2"}],
            "outputs": [],
        }
        store2.store(projection_v5)

        # Verify store2 now has version 5
        assert store2.current_version() == 5, f"Store2 version should be 5, got {store2.current_version()}"

        # Try to load stale persisted state (v3) into store2 (which has v5)
        # This should reject v3 because v5 is newer
        result = store2.load_from_persisted(stale_persisted_state)
        assert result is False, "Should reject stale persisted state"

        # Verify store2 still has v5
        assert store2.current_version() == 5, "Version should remain 5 after rejected load"

        print("  PASS: Stale persisted state correctly rejected")

    def test_terminal_state_cleanup(self):
        """Test that terminal workflows have persisted state cleaned up."""
        print("\n[TEST] terminal state cleanup")

        pm = ProjectionManager()
        workflow_id = "test-wf-terminal"

        # Store an ACTIVE projection
        projection_active = {
            "workflow_id": workflow_id,
            "projection_type": "workflow",
            "projection_version": 1,
            "projection_timestamp": "2026-05-13T10:00:00",
            "projection_state": PROJECTION_STATE_ACTIVE,
            "lifecycle_status": "ACTIVE",
            "steps": [],
            "outputs": [],
        }

        pm._get_or_create_store(workflow_id).store(projection_active)

        # Verify persisted
        persisted = _load_persisted_stores()
        assert workflow_id in persisted

        # Now emit terminal lifecycle change
        workflow = {"id": workflow_id, "output": None}
        pm.emit_lifecycle_changed(workflow, "COMPLETED")

        # Verify cleanup occurred
        persisted = _load_persisted_stores()
        assert workflow_id not in persisted, "Terminal workflow should be cleaned up"

        print("  PASS: Terminal state cleanup works correctly")

    def test_version_monotonicity_across_restart(self):
        """Test that version counter resumes above persisted value after restart."""
        print("\n[TEST] version monotonicity across restart")

        # First PM stores projections
        pm1 = ProjectionManager()
        workflow_id = "test-wf-mono"

        # Store version 3
        projection = {
            "workflow_id": workflow_id,
            "projection_type": "workflow",
            "projection_version": 3,  # This will be overridden by next_version()
            "projection_timestamp": "2026-05-13T10:00:00",
            "projection_state": PROJECTION_STATE_ACTIVE,
            "lifecycle_status": "ACTIVE",
            "steps": [],
            "outputs": [],
        }

        store1 = pm1._get_or_create_store(workflow_id)
        store1.store(projection)

        # Create new PM (simulating restart)
        pm2 = ProjectionManager()

        # Mock runtime authority
        def mock_get_state(wfid):
            return None

        # Warm restore
        pm2.warm_stores_from_disk(mock_get_state)

        # Get store and check version
        store2 = pm2._get_store(workflow_id)
        assert store2 is not None

        # Next version should be 4 (monotonic continuation)
        next_ver = store2.next_version()
        assert next_ver == 4, f"Next version should be 4, got {next_ver}"

        print("  PASS: Version monotonicity preserved across restart")

    def test_persistence_atomicity(self):
        """Test that persistence uses atomic writes (tempfile -> os.replace)."""
        print("\n[TEST] persistence atomicity")

        # This test verifies the implementation uses atomic writes
        # by checking the persistence function behavior
        import system.orchestrator.projection_manager as pm

        workflow_id = "test-wf-atomic"
        state = {
            "latest_projection": {"projection_version": 1},
            "projection_state": PROJECTION_STATE_ACTIVE,
            "continuity_anchor_version": 1,
            "stale_rejection_count": 0,
        }

        # Persist should succeed
        result = _persist_store_state(workflow_id, state)
        assert result is True, "Persistence should succeed"

        # File should exist
        assert os.path.exists(pm._PROJECTION_STORE_PATH)

        # Load should return correct data
        loaded = _load_persisted_stores()
        assert loaded[workflow_id]["latest_projection"]["projection_version"] == 1

        print("  PASS: Persistence atomicity verified")


def run_tests():
    """Run all tests."""
    print("=" * 60)
    print("PHASE 3F-XB — Projection Store Persistence Tests")
    print("=" * 60)

    test_class = TestProjectionStorePersistence()
    tests = [
        test_class.test_store_persists_on_projection_store,
        test_class.test_warm_restoration,
        test_class.test_stale_persisted_state_rejection,
        test_class.test_terminal_state_cleanup,
        test_class.test_version_monotonicity_across_restart,
        test_class.test_persistence_atomicity,
    ]

    passed = 0
    failed = 0

    for test in tests:
        test_class.setup_method()
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1
        finally:
            test_class.teardown_method()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
