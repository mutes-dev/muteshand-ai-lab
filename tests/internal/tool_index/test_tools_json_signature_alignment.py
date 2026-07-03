"""
tools.json ↔ Python tool signature alignment tests.

Verifies that every production tool in tools.json has a corresponding
Python module under tools/ with a callable run() whose parameter names
match the tools.json inputs keys.

Non-production / system-internal tools are explicitly allowlisted.
"""

import importlib
import inspect
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


# Tools that are intentionally non-production / system-internal and do not
# require a local Python module aligned with tools.json inputs.
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

# Tools that are in tools.json but may not map 1:1 to a simple local module
# (e.g., virtual, composite, or otherwise special).
SPECIAL_LOCAL_TOOLS: Set[str] = set()


class TestToolsJsonSignatureAlignment:
    """Production tools in tools.json align with tools/<name>.py run() signatures."""

    def test_all_production_tools_have_python_module(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name in NON_PRODUCTION_TOOLS:
                continue
            if name in SPECIAL_LOCAL_TOOLS:
                continue
            module_path = os.path.join(_PROJECT_ROOT, "tools", f"{name}.py")
            if not os.path.isfile(module_path):
                failures.append(name)
        assert not failures, f"Production tools missing tools/<name>.py: {failures}"

    def test_all_production_tools_have_callable_run(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name in NON_PRODUCTION_TOOLS:
                continue
            if name in SPECIAL_LOCAL_TOOLS:
                continue
            try:
                mod = importlib.import_module(f"tools.{name}")
            except Exception as exc:
                failures.append(f"{name}: import error: {exc}")
                continue
            if not hasattr(mod, "run"):
                failures.append(f"{name}: missing 'run'")
                continue
            if not callable(mod.run):
                failures.append(f"{name}: 'run' is not callable")
        assert not failures, f"run() issues: {failures}"

    def test_production_tool_inputs_match_run_signature(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name in NON_PRODUCTION_TOOLS:
                continue
            if name in SPECIAL_LOCAL_TOOLS:
                continue
            try:
                mod = importlib.import_module(f"tools.{name}")
                sig = inspect.signature(mod.run)
            except Exception as exc:
                failures.append(f"{name}: inspect error: {exc}")
                continue

            param_names = set(sig.parameters.keys())
            input_keys = set(spec.get("inputs", {}).keys())

            missing = input_keys - param_names
            if missing:
                failures.append(f"{name}: inputs {missing} not in run() params {param_names}")

        assert not failures, f"Signature alignment failures: {failures}"

    def test_tools_json_arg_order_matches_run_signature_order(self):
        """
        Arg order in tools.json should match run() positional parameter order.
        Only validates tools where all inputs are positional (no *args, **kwargs).
        """
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name in NON_PRODUCTION_TOOLS:
                continue
            if name in SPECIAL_LOCAL_TOOLS:
                continue
            try:
                mod = importlib.import_module(f"tools.{name}")
                sig = inspect.signature(mod.run)
            except Exception as exc:
                failures.append(f"{name}: inspect error: {exc}")
                continue

            arg_order = list(spec.get("arg_order", []))
            if not arg_order:
                continue

            # Build ordered list of run() params that have no default (required positional)
            # followed by params with defaults.
            params = list(sig.parameters.values())
            param_names = [p.name for p in params]

            # If run() uses *args or **kwargs, skip order check
            if any(p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD) for p in params):
                continue

            # Validate that arg_order is a prefix/subset in the same order as run() params
            # We only check that required params (no default) match the beginning of arg_order.
            required_params = [p.name for p in params if p.default is inspect.Parameter.empty]
            if required_params:
                # required_params must be the prefix of arg_order
                if arg_order[:len(required_params)] != required_params:
                    failures.append(
                        f"{name}: required run() params {required_params} "
                        f"do not match arg_order prefix {arg_order[:len(required_params)]}"
                    )

        assert not failures, f"Arg order failures: {failures}"
