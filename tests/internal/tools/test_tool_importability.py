"""
Tool importability tests.

Verifies that every production tool in tools.json can be imported as
tools.<tool_name> and exposes a callable run attribute.

Non-production / system-internal tools are explicitly allowlisted.
"""

import importlib
import json
import os
import sys
from typing import Any, Dict, Set

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _load_tools_json() -> Dict[str, Any]:
    path = os.path.join(_PROJECT_ROOT, "system", "tool_index", "tools.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Tools that are intentionally non-production / system-internal.
NON_PRODUCTION_TOOLS: Set[str] = {
    "bad_add",
    "health_check_system",
    "inspect_manager_section",
    "migrate_error_handling",
    "rebuild_tool_index",
    "run_python",
    "run_system_maintenance",
    "self_test_system",
}


class TestToolImportability:
    """Production tools are importable and expose callable run."""

    def test_all_production_tools_importable(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name in NON_PRODUCTION_TOOLS:
                continue
            try:
                mod = importlib.import_module(f"tools.{name}")
            except Exception as exc:
                failures.append(f"{name}: {exc}")
                continue
            if not hasattr(mod, "run"):
                failures.append(f"{name}: missing 'run'")
                continue
            if not callable(mod.run):
                failures.append(f"{name}: 'run' not callable")
        assert not failures, f"Importability failures: {failures}"

    def test_imported_tools_have_input_spec_or_docstring(self):
        """
        Every production tool module should have either INPUT_SPEC or a run() docstring.
        This ensures there is a discoverable schema definition.
        """
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name in NON_PRODUCTION_TOOLS:
                continue
            try:
                mod = importlib.import_module(f"tools.{name}")
            except Exception:
                continue  # already caught by test_all_production_tools_importable
            has_input_spec = hasattr(mod, "INPUT_SPEC")
            has_docstring = bool(getattr(mod.run, "__doc__", None))
            if not has_input_spec and not has_docstring:
                failures.append(f"{name}: missing INPUT_SPEC and run() docstring")
        assert not failures, f"Schema definition failures: {failures}"
