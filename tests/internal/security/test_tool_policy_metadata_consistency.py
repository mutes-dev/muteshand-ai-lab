"""
Tool metadata consistency tests for tools.json ↔ tool_policy.py alignment.

Covers:
- Every TOOL_METADATA entry has required legacy fields unchanged.
- If read_only=True, then mutating=False.
- If high_risk=True, then requires_approval=True.
- Every PLAN_MODE_ALLOWED_TOOLS entry exists in TOOL_METADATA.
- Every PLAN_MODE_ALLOWED_TOOLS entry has read_only=True.
- Every PLAN_MODE_ALLOWED_TOOLS entry has disabled_in_plan_mode=False.
- Every production tool in tools.json has corresponding TOOL_METADATA where expected.
- No TOOL_METADATA entry points to a removed/nonexistent production tool unless explicitly documented as system/internal.
- idempotent exists and is bool for each relevant TOOL_METADATA entry.
"""

import json
import os
import sys
from typing import Any, Dict, Set

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from system.security.tool_policy import (
    TOOL_METADATA,
    PLAN_MODE_ALLOWED_TOOLS,
    HIGH_RISK_TOOLS,
)


# Production tools that intentionally lack a tools.json entry
# (system/internal tools that are not exposed to the routing layer)
SYSTEM_INTERNAL_TOOLS_NO_JSON = {
    "bad_add",
    "health_check_system",
    "inspect_manager_section",
    "migrate_error_handling",
    "rebuild_tool_index",
    "run_python",
    "run_system_maintenance",
    "self_test_system",
}

# Tools that are in TOOL_METADATA but may be non-production / system-internal
NON_PRODUCTION_TOOLS = SYSTEM_INTERNAL_TOOLS_NO_JSON


def _load_tools_json() -> Dict[str, Any]:
    path = os.path.join(_PROJECT_ROOT, "system", "tool_index", "tools.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestToolMetadataFieldPresence:
    """Every TOOL_METADATA entry has required fields."""

    def test_all_entries_have_read_only(self):
        for name, meta in TOOL_METADATA.items():
            assert "read_only" in meta, f"{name} missing read_only"
            assert isinstance(meta["read_only"], bool)

    def test_all_entries_have_mutating(self):
        for name, meta in TOOL_METADATA.items():
            assert "mutating" in meta, f"{name} missing mutating"
            assert isinstance(meta["mutating"], bool)

    def test_all_entries_have_external_call(self):
        for name, meta in TOOL_METADATA.items():
            assert "external_call" in meta, f"{name} missing external_call"
            assert isinstance(meta["external_call"], bool)

    def test_all_entries_have_high_risk(self):
        for name, meta in TOOL_METADATA.items():
            assert "high_risk" in meta, f"{name} missing high_risk"
            assert isinstance(meta["high_risk"], bool)

    def test_all_entries_have_requires_approval(self):
        for name, meta in TOOL_METADATA.items():
            assert "requires_approval" in meta, f"{name} missing requires_approval"
            assert isinstance(meta["requires_approval"], bool)

    def test_all_entries_have_disabled_in_plan_mode(self):
        for name, meta in TOOL_METADATA.items():
            assert "disabled_in_plan_mode" in meta, f"{name} missing disabled_in_plan_mode"
            assert isinstance(meta["disabled_in_plan_mode"], bool)

    def test_all_entries_have_idempotent(self):
        for name, meta in TOOL_METADATA.items():
            assert "idempotent" in meta, f"{name} missing idempotent"
            assert isinstance(meta["idempotent"], bool)


class TestToolMetadataConsistency:
    """Consistency rules within TOOL_METADATA."""

    def test_read_only_implies_not_mutating(self):
        failures = []
        for name, meta in TOOL_METADATA.items():
            if meta.get("read_only") is True and meta.get("mutating") is not False:
                failures.append(name)
        assert not failures, f"read_only=True but mutating!=False: {failures}"

    def test_high_risk_implies_requires_approval(self):
        failures = []
        # run_python is in HIGH_RISK_TOOLS (blocked in all modes unconditionally);
        # it does not require approval because it is never allowed regardless of mode.
        exempt = {"run_python"}
        for name, meta in TOOL_METADATA.items():
            if name in exempt:
                continue
            if meta.get("high_risk") is True and meta.get("requires_approval") is not True:
                failures.append(name)
        assert not failures, f"high_risk=True but requires_approval!=True: {failures}"

    def test_high_risk_tools_set_matches_metadata(self):
        for name in HIGH_RISK_TOOLS:
            assert name in TOOL_METADATA, f"{name} in HIGH_RISK_TOOLS but not in TOOL_METADATA"
            assert TOOL_METADATA[name]["high_risk"] is True, f"{name} in HIGH_RISK_TOOLS but metadata high_risk=False"

    def test_plan_mode_allowed_tools_have_read_only(self):
        failures = []
        for name in PLAN_MODE_ALLOWED_TOOLS:
            meta = TOOL_METADATA.get(name)
            assert meta is not None, f"{name} in PLAN_MODE_ALLOWED_TOOLS but not in TOOL_METADATA"
            if meta.get("read_only") is not True:
                failures.append(name)
        assert not failures, f"PLAN_MODE_ALLOWED_TOOLS entries with read_only!=True: {failures}"

    def test_plan_mode_allowed_tools_not_disabled_in_plan_mode(self):
        failures = []
        for name in PLAN_MODE_ALLOWED_TOOLS:
            meta = TOOL_METADATA.get(name)
            if meta.get("disabled_in_plan_mode") is not False:
                failures.append(name)
        assert not failures, f"PLAN_MODE_ALLOWED_TOOLS entries with disabled_in_plan_mode!=False: {failures}"


class TestToolsJsonAlignment:
    """tools.json ↔ tool_policy.py alignment."""

    def test_every_production_tool_in_json_has_metadata(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name in NON_PRODUCTION_TOOLS:
                continue
            if name not in TOOL_METADATA:
                failures.append(name)
        assert not failures, f"Production tools in tools.json missing TOOL_METADATA: {failures}"

    def test_no_orphan_production_metadata_without_json(self):
        """TOOL_METADATA entries that are marked as production-like should exist in tools.json.
        System/internal tools are explicitly allowlisted."""
        tools_json = _load_tools_json()
        failures = []
        for name in TOOL_METADATA:
            if name in NON_PRODUCTION_TOOLS:
                continue
            if name not in tools_json:
                failures.append(name)
        assert not failures, f"TOOL_METADATA entries not in tools.json (and not in allowlist): {failures}"

    def test_json_and_metadata_tool_names_aligned(self):
        tools_json = _load_tools_json()
        json_names = set(tools_json.keys())
        metadata_names = set(TOOL_METADATA.keys())
        # All production json tools should be in metadata
        prod_json_names = {n for n, s in tools_json.items() if s.get("production")}
        missing_in_metadata = prod_json_names - metadata_names
        assert not missing_in_metadata, f"Production tools in tools.json missing from TOOL_METADATA: {missing_in_metadata}"
