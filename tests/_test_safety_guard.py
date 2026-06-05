"""
Test Safety Guard — Prevent destructive test operations against production persistence.

This module provides:
1. _is_production_persistence_path(path) — detects real E:\MutesHand\memory, system\checkpoints
2. guard_delete(path) / guard_rmtree(path) — refuse to delete production paths
3. _isolate_persistence(monkeypatch, tmp_path) — fixture helper for pytest isolation
4. get_test_active_dir(tmp_path) / get_test_checkpoint_dir(tmp_path) — temp dir helpers
5. fail_fast_if_production_imported() — emergency fail-fast for test modules
6. guard_clear_directory(path) — bulk directory cleanup with guard
7. guard_delete_workflow(workflow_id) — wraps delete_workflow with guard

Usage in test files:
    @pytest.fixture(autouse=True)
    def _isolate_active_workflows(monkeypatch, tmp_path):
        _isolate_persistence(
            monkeypatch, tmp_path,
            module=system.orchestrator.persistence,
            attr="ACTIVE_WORKFLOW_DIR",
            subdir="active_workflows"
        )

Or for standalone scripts:
    from tests._test_safety_guard import guard_delete, _is_production_persistence_path
    guard_delete(some_path)  # raises RuntimeError if protected
"""

import os
import sys
import shutil
import tempfile

# Resolve production root (2 levels up from tests/)
_PRODUCTION_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_PROTECTED_PATHS = [
    os.path.join(_PRODUCTION_ROOT, "memory"),
    os.path.join(_PRODUCTION_ROOT, "system", "checkpoints"),
    os.path.join(_PRODUCTION_ROOT, "traces"),
]

_PROTECTED_FILES = [
    os.path.join(_PRODUCTION_ROOT, "memory", "projection_stores.json"),
    os.path.join(_PRODUCTION_ROOT, "memory", "workflows.json"),
]

# Windows temp directories + pytest tmp_path root
_TEMP_PARENTS = [
    os.path.abspath(tempfile.gettempdir()),
]


def _normalize_path(path: str) -> str:
    """Normalize path for safe comparison (realpath, normpath, abspath)."""
    if not path:
        return ""
    try:
        return os.path.normcase(os.path.abspath(os.path.realpath(os.path.normpath(path))))
    except (OSError, ValueError):
        return os.path.normcase(os.path.abspath(path))


def _is_production_persistence_path(path: str) -> bool:
    """
    Check if `path` resolves under a protected production persistence directory or file.
    Returns True if the path is (or is inside) any protected production directory
    or matches a protected file exactly.
    """
    if not path:
        return False
    real_path = _normalize_path(path)
    for protected in _PROTECTED_PATHS:
        protected_real = _normalize_path(protected)
        if real_path == protected_real:
            return True
        # Windows path separator handling
        sep = os.sep
        if real_path.startswith(protected_real + sep):
            return True
    for protected_file in _PROTECTED_FILES:
        if real_path == _normalize_path(protected_file):
            return True
    return False


def _is_test_sandbox_path(path: str) -> bool:
    """Check if path resolves inside a known temp / test sandbox directory."""
    if not path:
        return False
    real_path = _normalize_path(path)
    for temp_parent in _TEMP_PARENTS:
        temp_norm = _normalize_path(temp_parent)
        sep = os.sep
        if real_path == temp_norm or real_path.startswith(temp_norm + sep):
            return True
    return False


def guard_delete(path: str) -> bool:
    """
    Delete a file only if it is NOT under a protected production persistence path.

    Raises:
        RuntimeError: If path is under a protected production directory.

    Returns:
        True if deleted or didn't exist.
    """
    if _is_production_persistence_path(path):
        raise RuntimeError(
            f"SAFETY GUARD: Refusing to delete production persistence path: {path}. "
            f"Use test-isolated paths (e.g., tmp_path) or monkeypatch persistence directories."
        )
    if os.path.exists(path):
        os.remove(path)
    return True


def guard_rmtree(path: str) -> bool:
    """
    Remove a directory tree only if it is NOT under a protected production persistence path.

    Raises:
        RuntimeError: If path is under a protected production directory.

    Returns:
        True if removed or didn't exist.
    """
    if _is_production_persistence_path(path):
        raise RuntimeError(
            f"SAFETY GUARD: Refusing to rmtree production persistence path: {path}. "
            f"Use test-isolated paths (e.g., tmp_path) or monkeypatch persistence directories."
        )
    if os.path.exists(path):
        shutil.rmtree(path)
    return True


def guard_clear_directory(path: str) -> bool:
    """
    Remove all files inside a directory. Guards the directory path itself
    and refuses to operate on production persistence.
    """
    if _is_production_persistence_path(path):
        raise RuntimeError(
            f"SAFETY GUARD: Refusing to clear production persistence directory: {path}."
        )
    if os.path.exists(path):
        for fname in os.listdir(path):
            fpath = os.path.join(path, fname)
            if os.path.isfile(fpath):
                guard_delete(fpath)
            elif os.path.isdir(fpath):
                guard_rmtree(fpath)
    return True


def guard_delete_workflow(workflow_id: str) -> bool:
    """
    Wrap delete_workflow with safety guard. Only deletes if the resolved
    active workflow path is NOT under production persistence.
    """
    from system.orchestrator.persistence import _active_workflow_path
    path = _active_workflow_path(workflow_id)
    if _is_production_persistence_path(path):
        raise RuntimeError(
            f"SAFETY GUARD: Refusing to delete workflow {workflow_id!r} because "
            f"its persistence path resolves under production: {path}."
        )
    from system.orchestrator.persistence import delete_workflow
    delete_workflow(workflow_id)
    return True


def get_test_active_dir(tmp_path) -> str:
    """Return an isolated test directory for active workflows."""
    d = str(tmp_path / "active_workflows")
    os.makedirs(d, exist_ok=True)
    return d


def get_test_checkpoint_dir(tmp_path) -> str:
    """Return an isolated test directory for checkpoints."""
    d = str(tmp_path / "checkpoints")
    os.makedirs(d, exist_ok=True)
    return d


def _isolate_module_attr(monkeypatch, tmp_path, source_module, attr_name, subdir):
    """
    Monkeypatch a module-level directory constant to a tmp_path subdirectory.
    Also patches the same attribute in the calling test module if imported there.
    """
    test_dir = str(tmp_path / subdir)
    os.makedirs(test_dir, exist_ok=True)

    # Patch the source module (affects functions defined there that do global lookups)
    monkeypatch.setattr(source_module, attr_name, test_dir)

    # Patch the test module that may have imported the constant directly
    # Walk sys.modules to find test modules that have this attribute
    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith("test_") or mod_name.startswith("tests."):
            if hasattr(mod, attr_name):
                current_val = getattr(mod, attr_name)
                # Only patch if it's a string path (not a function)
                if isinstance(current_val, str) and _is_production_persistence_path(current_val):
                    monkeypatch.setattr(mod, attr_name, test_dir)

    return test_dir


def fail_fast_if_production_imported(caller_module_name: str = None):
    """
    Emergency fail-fast: If the caller's module has imported a production
    persistence path constant and it still resolves to production,
    raise RuntimeError immediately.

    Use at the top of standalone test scripts (non-pytest) after imports.
    """
    import inspect
    if caller_module_name is None:
        caller = inspect.currentframe().f_back
        caller_module = inspect.getmodule(caller)
        caller_module_name = caller_module.__name__ if caller_module else "__main__"

    target = sys.modules.get(caller_module_name)
    if not target:
        return

    for attr in ("ACTIVE_WORKFLOW_DIR", "CHECKPOINT_DIR"):
        if hasattr(target, attr):
            val = getattr(target, attr)
            if isinstance(val, str) and _is_production_persistence_path(val):
                raise RuntimeError(
                    f"SAFETY GUARD FAIL-FAST: Module {caller_module_name!r} imported "
                    f"production {attr}={val!r} without isolation. "
                    f"Tests must monkeypatch or use temp directories before any destructive operation."
                )

