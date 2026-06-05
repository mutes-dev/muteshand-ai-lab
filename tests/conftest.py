"""
Pytest conftest — Emergency fail-fast for destructive test isolation.

This file adds an autouse fixture that verifies any test module importing
ACTIVE_WORKFLOW_DIR or CHECKPOINT_DIR has properly monkeypatched them
before any test runs.
"""

import sys
import os

# Ensure safety guard is importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_ProjectRoot = os.path.abspath(os.path.join(_HERE, ".."))
if _ProjectRoot not in sys.path:
    sys.path.insert(0, _ProjectRoot)

import pytest
from tests._test_safety_guard import _is_production_persistence_path


@pytest.fixture(autouse=True)
def _fail_fast_if_unisolated():
    """
    Before each test, verify that any imported production persistence path
    constants in test modules are NOT pointing to real production directories.
    If they are, the test is aborted immediately.
    """
    # Check all currently loaded test modules
    for mod_name, mod in list(sys.modules.items()):
        if not (mod_name.startswith("test_") or mod_name.startswith("tests.")):
            continue
        if not mod:
            continue
        for attr in ("ACTIVE_WORKFLOW_DIR", "CHECKPOINT_DIR"):
            if not hasattr(mod, attr):
                continue
            val = getattr(mod, attr)
            if not isinstance(val, str):
                continue
            if _is_production_persistence_path(val):
                pytest.fail(
                    f"SAFETY GUARD FAIL-FAST: Module {mod_name!r} has unisolated "
                    f"{attr}={val!r} at test runtime. "
                    f"Add a monkeypatch fixture or module-level temp isolation before running tests."
                )
    yield
