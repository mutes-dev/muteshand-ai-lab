"""
Safety Guard Proof Tests

Validates that _test_safety_guard refuses to delete or rmtree production
persistence paths (memory/, system/checkpoints/, traces/)."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from tests._test_safety_guard import (
    _is_production_persistence_path,
    _is_test_sandbox_path,
    guard_delete,
    guard_rmtree,
    guard_clear_directory,
    guard_delete_workflow,
    fail_fast_if_production_imported,
)


class TestSafetyGuardDetection:
    def test_detects_active_workflows_as_production(self):
        assert _is_production_persistence_path(r"E:\MutesHand\memory\active_workflows")

    def test_detects_events_as_production(self):
        assert _is_production_persistence_path(r"E:\MutesHand\memory\events\foo.jsonl")

    def test_detects_checkpoints_as_production(self):
        assert _is_production_persistence_path(r"E:\MutesHand\system\checkpoints\wf.json")

    def test_detects_traces_as_production(self):
        assert _is_production_persistence_path(r"E:\MutesHand\traces\wf.json")

    def test_rejects_temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            assert not _is_production_persistence_path(td)

    def test_rejects_subdir_of_temp(self):
        with tempfile.TemporaryDirectory() as td:
            sub = os.path.join(td, "active_workflows", "wf.json")
            assert not _is_production_persistence_path(sub)


class TestSafetyGuardDelete:
    def test_guard_delete_allows_temp_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        assert guard_delete(path) is True
        assert not os.path.exists(path)

    def test_guard_delete_blocks_production_path(self):
        with pytest.raises(RuntimeError, match="SAFETY GUARD"):
            guard_delete(r"E:\MutesHand\memory\active_workflows\test.json")

    def test_guard_delete_allows_nonexistent_production(self):
        # Even if file doesn't exist, the path itself is protected
        with pytest.raises(RuntimeError, match="SAFETY GUARD"):
            guard_delete(r"E:\MutesHand\memory\active_workflows\nonexistent.json")


class TestSafetyGuardRmtree:
    def test_guard_rmtree_allows_temp_dir(self):
        with tempfile.TemporaryDirectory() as td:
            sub = os.path.join(td, "nested")
            os.makedirs(sub)
            assert guard_rmtree(sub) is True
            assert not os.path.exists(sub)

    def test_guard_rmtree_blocks_production_dir(self):
        with pytest.raises(RuntimeError, match="SAFETY GUARD"):
            guard_rmtree(r"E:\MutesHand\memory\active_workflows")

    def test_guard_rmtree_blocks_production_checkpoint_dir(self):
        with pytest.raises(RuntimeError, match="SAFETY GUARD"):
            guard_rmtree(r"E:\MutesHand\system\checkpoints")


class TestSafetyGuardAbsolutePathNormalization:
    def test_normalized_paths_detected(self):
        # Absolute realpath of a relative path pointing to production
        rel = os.path.join("..", "memory", "active_workflows")
        abs_path = os.path.abspath(rel)
        # Only counts if it actually resolves to the production root
        assert _is_production_persistence_path(abs_path) == (
            abs_path.startswith(os.path.abspath(r"E:\MutesHand\memory"))
        )


class TestSafetyGuardSandboxDetection:
    def test_temp_dir_is_sandbox(self):
        with tempfile.TemporaryDirectory() as td:
            assert _is_test_sandbox_path(td)

    def test_production_path_is_not_sandbox(self):
        assert not _is_test_sandbox_path(r"E:\MutesHand\memory\active_workflows")

    def test_subdir_of_temp_is_sandbox(self):
        with tempfile.TemporaryDirectory() as td:
            sub = os.path.join(td, "active_workflows")
            os.makedirs(sub)
            assert _is_test_sandbox_path(sub)


class TestSafetyGuardProtectedFiles:
    def test_projection_stores_json_is_protected(self):
        assert _is_production_persistence_path(r"E:\MutesHand\memory\projection_stores.json")

    def test_workflows_json_is_protected(self):
        assert _is_production_persistence_path(r"E:\MutesHand\memory\workflows.json")

    def test_unrelated_json_not_protected(self):
        assert not _is_production_persistence_path(r"E:\MutesHand\unrelated.json")


class TestSafetyGuardClearDirectory:
    def test_guard_clear_directory_allows_temp(self):
        with tempfile.TemporaryDirectory() as td:
            sub = os.path.join(td, "active_workflows")
            os.makedirs(sub)
            path = os.path.join(sub, "wf.json")
            with open(path, "w") as f:
                f.write("{}")
            assert guard_clear_directory(sub) is True
            assert not os.path.exists(path)

    def test_guard_clear_directory_blocks_production(self):
        with pytest.raises(RuntimeError, match="SAFETY GUARD"):
            guard_clear_directory(r"E:\MutesHand\memory\active_workflows")


class TestSafetyGuardDeleteWorkflow:
    def test_guard_delete_workflow_blocks_production(self):
        # Module-level ACTIVE_WORKFLOW_DIR is still production in this test process,
        # so guard_delete_workflow should refuse.
        with pytest.raises(RuntimeError, match="SAFETY GUARD"):
            guard_delete_workflow("test_should_be_blocked")


class TestSafetyGuardFailFast:
    def test_fail_fast_catches_unisolated_import(self):
        import types
        fake_mod = types.ModuleType("test_fake_unisolated")
        fake_mod.ACTIVE_WORKFLOW_DIR = r"E:\MutesHand\memory\active_workflows"
        sys.modules["test_fake_unisolated"] = fake_mod
        try:
            with pytest.raises(RuntimeError, match="SAFETY GUARD FAIL-FAST"):
                fail_fast_if_production_imported("test_fake_unisolated")
        finally:
            sys.modules.pop("test_fake_unisolated", None)

    def test_fail_fast_passes_isolated_import(self):
        import types
        fake_mod = types.ModuleType("test_fake_isolated")
        fake_mod.ACTIVE_WORKFLOW_DIR = r"C:\temp\test_active"
        sys.modules["test_fake_isolated"] = fake_mod
        try:
            fail_fast_if_production_imported("test_fake_isolated")
        finally:
            sys.modules.pop("test_fake_isolated", None)
