"""
Tool Metadata Baseline Tests — SPRINT-11B

Verifies that tools.json contains a consistent, non-authoritative
minimal metadata baseline for every production tool.

Covers:
- Required metadata field presence and types
- Allowed vocabulary for enumerated fields
- Internal consistency rules
- Alignment with tool_policy.py TOOL_METADATA (advisory only)
- Non-authoritative proof: runtime policy gates remain in tool_policy.py
"""

import json
import os
import sys
from typing import Any, Dict, Set

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from system.security.tool_policy import (
    TOOL_METADATA,
    PLAN_MODE_ALLOWED_TOOLS,
    HIGH_RISK_TOOLS,
    check_tool_policy,
)


# ── TEST-ONLY EXCLUSION LIST ─────────────────────────────────────────────────
#
# These are system/internal tools that exist in tool_policy.py TOOL_METADATA
# but are intentionally absent from the canonical tools.json registry.
#
# IMPORTANT:
# - This is NOT the canonical production tool list.
# - Production tools are derived dynamically from tools.json below.
# - tools.json remains the sole canonical authority for production tool names.
#
# SYNC REQUIREMENT:
# This constant must stay in sync with the identical system/internal-tool
# exclusion constant in:
#   tests/internal/security/test_tool_policy_metadata_consistency.py
#
# NOTE: If a shared test-constants module is introduced later, this set
# can be moved there. Do NOT create a new shared module as part of this
# change.
# ──────────────────────────────────────────────────────────────────────────────
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


# Allowed vocabularies per the Sprint-11B metadata baseline spec
ALLOWED_SIDE_EFFECTS = {
    "none",
    "local_read",
    "local_write",
    "network_read",
    "network_call",
    "format_only",
    "compute_only",
}

ALLOWED_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}

# Required metadata fields for every production tool in tools.json
REQUIRED_FIELDS = {
    "read_only",
    "destructive",
    "idempotent",
    "external_call",
    "side_effects",
    "risk_level",
    "requires_approval",
}


def _load_tools_json() -> Dict[str, Any]:
    path = os.path.join(_PROJECT_ROOT, "system", "tool_index", "tools.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Field presence and type correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestMetadataFieldPresence:
    """Every production tool has all required metadata fields with correct types."""

    def test_all_production_tools_have_required_fields(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            missing = REQUIRED_FIELDS - set(spec.keys())
            if missing:
                failures.append(f"{name}: missing {missing}")
        assert not failures, f"Missing metadata fields: {failures}"

    def test_read_only_is_bool(self):
        tools_json = _load_tools_json()
        for name, spec in tools_json.items():
            if spec.get("production"):
                assert isinstance(spec["read_only"], bool), f"{name}: read_only must be bool"

    def test_destructive_is_bool(self):
        tools_json = _load_tools_json()
        for name, spec in tools_json.items():
            if spec.get("production"):
                assert isinstance(spec["destructive"], bool), f"{name}: destructive must be bool"

    def test_idempotent_is_bool(self):
        tools_json = _load_tools_json()
        for name, spec in tools_json.items():
            if spec.get("production"):
                assert isinstance(spec["idempotent"], bool), f"{name}: idempotent must be bool"

    def test_external_call_is_bool(self):
        tools_json = _load_tools_json()
        for name, spec in tools_json.items():
            if spec.get("production"):
                assert isinstance(spec["external_call"], bool), f"{name}: external_call must be bool"

    def test_requires_approval_is_bool(self):
        tools_json = _load_tools_json()
        for name, spec in tools_json.items():
            if spec.get("production"):
                assert isinstance(spec["requires_approval"], bool), f"{name}: requires_approval must be bool"

    def test_side_effects_is_string(self):
        tools_json = _load_tools_json()
        for name, spec in tools_json.items():
            if spec.get("production"):
                assert isinstance(spec["side_effects"], str), f"{name}: side_effects must be str"

    def test_risk_level_is_string(self):
        tools_json = _load_tools_json()
        for name, spec in tools_json.items():
            if spec.get("production"):
                assert isinstance(spec["risk_level"], str), f"{name}: risk_level must be str"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Allowed vocabulary
# ─────────────────────────────────────────────────────────────────────────────

class TestMetadataAllowedValues:
    """Enumerated fields use only approved vocabulary values."""

    def test_side_effects_uses_allowed_vocabulary(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            val = spec["side_effects"]
            if val not in ALLOWED_SIDE_EFFECTS:
                failures.append(f"{name}: side_effects='{val}' not in {ALLOWED_SIDE_EFFECTS}")
        assert not failures, f"Invalid side_effects values: {failures}"

    def test_risk_level_uses_allowed_vocabulary(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            val = spec["risk_level"]
            if val not in ALLOWED_RISK_LEVELS:
                failures.append(f"{name}: risk_level='{val}' not in {ALLOWED_RISK_LEVELS}")
        assert not failures, f"Invalid risk_level values: {failures}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Internal consistency rules
# ─────────────────────────────────────────────────────────────────────────────

class TestMetadataConsistency:
    """Logical consistency within tools.json metadata."""

    def test_read_only_implies_not_destructive(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if spec["read_only"] is True and spec["destructive"] is not False:
                failures.append(name)
        assert not failures, f"read_only=True but destructive!=False: {failures}"

    def test_destructive_implies_not_read_only(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if spec["destructive"] is True and spec["read_only"] is not False:
                failures.append(name)
        assert not failures, f"destructive=True but read_only!=False: {failures}"

    def test_external_call_implies_network_side_effects(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if spec["external_call"] is True and "network" not in spec["side_effects"]:
                failures.append(
                    f"{name}: external_call=True but side_effects='{spec['side_effects']}'"
                )
        assert not failures, f"external_call=True without network side_effects: {failures}"

    def test_high_risk_implies_requires_approval(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if spec["risk_level"] == "HIGH" and spec["requires_approval"] is not True:
                failures.append(name)
        assert not failures, f"risk_level=HIGH but requires_approval!=True: {failures}"

    def test_requires_approval_implies_not_read_only(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if spec["requires_approval"] is True and spec["read_only"] is not False:
                failures.append(name)
        assert not failures, f"requires_approval=True but read_only!=False: {failures}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Alignment with tool_policy.py TOOL_METADATA
# ─────────────────────────────────────────────────────────────────────────────

class TestMetadataAlignmentWithToolPolicy:
    """
    Where tools.json and tool_policy.py both describe the same concept,
    values must align (tools.json is a non-authoritative mirror).
    """

    def test_read_only_aligns_with_tool_policy(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name not in TOOL_METADATA:
                continue
            json_val = spec["read_only"]
            policy_val = TOOL_METADATA[name]["read_only"]
            if json_val != policy_val:
                failures.append(f"{name}: read_only json={json_val} policy={policy_val}")
        assert not failures, f"read_only misalignment: {failures}"

    def test_idempotent_aligns_with_tool_policy(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name not in TOOL_METADATA:
                continue
            json_val = spec["idempotent"]
            policy_val = TOOL_METADATA[name]["idempotent"]
            if json_val != policy_val:
                failures.append(f"{name}: idempotent json={json_val} policy={policy_val}")
        assert not failures, f"idempotent misalignment: {failures}"

    def test_external_call_aligns_with_tool_policy(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name not in TOOL_METADATA:
                continue
            json_val = spec["external_call"]
            policy_val = TOOL_METADATA[name]["external_call"]
            if json_val != policy_val:
                failures.append(f"{name}: external_call json={json_val} policy={policy_val}")
        assert not failures, f"external_call misalignment: {failures}"

    def test_requires_approval_aligns_with_tool_policy(self):
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name not in TOOL_METADATA:
                continue
            json_val = spec["requires_approval"]
            policy_val = TOOL_METADATA[name]["requires_approval"]
            if json_val != policy_val:
                failures.append(
                    f"{name}: requires_approval json={json_val} policy={policy_val}"
                )
        assert not failures, f"requires_approval misalignment: {failures}"

    def test_destructive_implies_mutating_in_tool_policy(self):
        """tools.json destructive=True must align with tool_policy.py mutating=True."""
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name not in TOOL_METADATA:
                continue
            if spec["destructive"] is True and TOOL_METADATA[name]["mutating"] is not True:
                failures.append(
                    f"{name}: destructive=True in tools.json but mutating!=True in policy"
                )
        assert not failures, f"destructive/mutating misalignment: {failures}"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Non-authoritative proof
# ─────────────────────────────────────────────────────────────────────────────

class TestMetadataNonAuthoritative:
    """
    Prove that tools.json metadata does NOT govern runtime execution.
    Runtime policy gates remain in tool_policy.py.
    """

    def test_tool_policy_still_uses_own_metadata_for_execution_checks(self):
        """
        check_tool_policy() must use TOOL_METADATA / HIGH_RISK_TOOLS /
        PLAN_MODE_ALLOWED_TOOLS directly, not tools.json fields.
        This is proven by the function's behavior and its documented
        contract: it imports from tool_policy.py constants.
        """
        # Direct behavioral proof: run_python is in HIGH_RISK_TOOLS and is blocked
        result = check_tool_policy("run_python", mode="normal")
        assert result.allowed is False
        assert result.reason == "tool_policy_blocked"

        # A production read-only tool is allowed in normal mode
        result = check_tool_policy("read_file", mode="normal")
        assert result.allowed is True

        # A mutating tool is blocked in plan mode
        result = check_tool_policy("write_file", mode="plan")
        assert result.allowed is False
        assert "mutating" in result.detail

    def test_tools_json_not_imported_by_tool_policy_module(self):
        """
        tool_policy.py must not import or load tools.json.
        It must remain an independent authority layer.
        """
        import inspect
        import system.security.tool_policy as policy_mod

        source = inspect.getsource(policy_mod)
        assert "tools.json" not in source, (
            "tool_policy.py must not reference tools.json; it is an independent authority layer"
        )

    def test_no_production_tool_missing_tool_policy_metadata(self):
        """Every production tool in tools.json that is not system-internal
        must have a corresponding TOOL_METADATA entry. This ensures the
        policy layer remains complete and authoritative."""
        tools_json = _load_tools_json()
        failures = []
        for name, spec in tools_json.items():
            if not spec.get("production"):
                continue
            if name in SYSTEM_INTERNAL_TOOLS_NO_JSON:
                continue
            if name not in TOOL_METADATA:
                failures.append(name)
        assert not failures, f"Production tools missing TOOL_METADATA: {failures}"
