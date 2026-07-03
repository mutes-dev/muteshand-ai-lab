"""
Tool policy metadata completeness tests — complements existing consistency suite.

Adds checks not already covered by test_tool_policy_metadata_consistency.py:
- mutating=True implies read_only=False (converse of existing check)
- external_call=True implies relevant metadata fields are populated
- Every TOOL_METADATA entry has extended descriptive fields
- Plan-mode-blocked tools are appropriately classified
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


def _load_tools_json() -> Dict[str, Any]:
    path = os.path.join(_PROJECT_ROOT, "system", "tool_index", "tools.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Extended metadata fields expected on every TOOL_METADATA entry.
_EXTENDED_FIELDS = {
    "provider",
    "destination",
    "data_leaving_system",
    "privacy_classification",
    "reversibility",
    "side_effect_summary",
    "confirmation_text_template",
}


class TestToolMetadataLogicalConsistency:
    """Additional logical consistency rules beyond the existing consistency suite."""

    def test_mutating_implies_not_read_only(self):
        """mutating=True must imply read_only=False."""
        failures = []
        for name, meta in TOOL_METADATA.items():
            if meta.get("mutating") is True and meta.get("read_only") is not False:
                failures.append(name)
        assert not failures, f"mutating=True but read_only!=False: {failures}"

    def test_disabled_in_plan_mode_implies_mutating_or_external_or_high_risk(self):
        """
        Tools disabled in plan mode should be mutating, external_call, or high_risk.
        Non-mutating, non-external, non-high-risk tools should not be blocked in plan mode.
        """
        failures = []
        for name, meta in TOOL_METADATA.items():
            if meta.get("disabled_in_plan_mode") is True:
                if (
                    meta.get("mutating") is not True
                    and meta.get("external_call") is not True
                    and meta.get("high_risk") is not True
                ):
                    failures.append(name)
        assert not failures, f"disabled_in_plan_mode but neither mutating nor external_call nor high_risk: {failures}"

    def test_requires_approval_implies_mutating_or_high_risk_or_external(self):
        """Tools requiring approval should have a justification (mutating, high_risk, or external)."""
        failures = []
        for name, meta in TOOL_METADATA.items():
            if meta.get("requires_approval") is True:
                if (
                    meta.get("mutating") is not True
                    and meta.get("high_risk") is not True
                    and meta.get("external_call") is not True
                ):
                    failures.append(name)
        assert not failures, f"requires_approval but not mutating/high_risk/external: {failures}"


class TestToolMetadataExtendedFields:
    """Every TOOL_METADATA entry has descriptive extended fields."""

    def test_all_entries_have_extended_fields(self):
        failures = []
        for name, meta in TOOL_METADATA.items():
            missing = _EXTENDED_FIELDS - set(meta.keys())
            if missing:
                failures.append(f"{name}: missing {missing}")
        assert not failures, f"Missing extended fields: {failures}"

    def test_external_call_consistency(self):
        """
        If external_call=True, at least one of provider/destination/data_leaving_system
        should describe the external interaction.
        """
        failures = []
        for name, meta in TOOL_METADATA.items():
            if meta.get("external_call") is True:
                provider = meta.get("provider")
                destination = meta.get("destination")
                data_leaving = meta.get("data_leaving_system")
                if provider is None and destination is None and data_leaving is None:
                    failures.append(name)
        assert not failures, f"external_call=True but no provider/destination/data_leaving: {failures}"

    def test_local_tools_have_null_external_metadata(self):
        """
        If external_call=False, provider/destination/data_leaving_system should be None.
        """
        failures = []
        for name, meta in TOOL_METADATA.items():
            if meta.get("external_call") is not False:
                continue
            for field in ("provider", "destination", "data_leaving_system"):
                if meta.get(field) is not None:
                    failures.append(f"{name}: {field}={meta[field]} but external_call=False")
        assert not failures, f"Local tools with non-null external metadata: {failures}"

    def test_privacy_classification_populated(self):
        """Every entry has a non-empty privacy_classification."""
        failures = []
        for name, meta in TOOL_METADATA.items():
            classification = meta.get("privacy_classification")
            if not classification or not isinstance(classification, str):
                failures.append(name)
        assert not failures, f"Missing or invalid privacy_classification: {failures}"

    def test_reversibility_populated(self):
        """Every entry has a non-empty reversibility."""
        failures = []
        for name, meta in TOOL_METADATA.items():
            reversibility = meta.get("reversibility")
            if not reversibility or not isinstance(reversibility, str):
                failures.append(name)
        assert not failures, f"Missing or invalid reversibility: {failures}"

    def test_side_effect_summary_populated(self):
        """Every entry has a non-empty side_effect_summary."""
        failures = []
        for name, meta in TOOL_METADATA.items():
            summary = meta.get("side_effect_summary")
            if not summary or not isinstance(summary, str):
                failures.append(name)
        assert not failures, f"Missing or invalid side_effect_summary: {failures}"

    def test_confirmation_text_template_populated(self):
        """Every entry has a non-empty confirmation_text_template."""
        failures = []
        for name, meta in TOOL_METADATA.items():
            template = meta.get("confirmation_text_template")
            if not template or not isinstance(template, str):
                failures.append(name)
        assert not failures, f"Missing or invalid confirmation_text_template: {failures}"


class TestPlanModeBlockedTools:
    """Tools blocked in plan mode are appropriately classified."""

    def test_plan_mode_blocked_tools_not_in_allowed_list(self):
        """Any tool with disabled_in_plan_mode=True must not be in PLAN_MODE_ALLOWED_TOOLS."""
        failures = []
        for name, meta in TOOL_METADATA.items():
            if meta.get("disabled_in_plan_mode") is True:
                if name in PLAN_MODE_ALLOWED_TOOLS:
                    failures.append(name)
        assert not failures, f"Tools disabled in plan mode but in PLAN_MODE_ALLOWED_TOOLS: {failures}"

    def test_high_risk_tools_disabled_in_plan_mode(self):
        """All HIGH_RISK_TOOLS must have disabled_in_plan_mode=True."""
        failures = []
        for name in HIGH_RISK_TOOLS:
            meta = TOOL_METADATA.get(name)
            assert meta is not None, f"{name} in HIGH_RISK_TOOLS but not in TOOL_METADATA"
            if meta.get("disabled_in_plan_mode") is not True:
                failures.append(name)
        assert not failures, f"HIGH_RISK_TOOLS not disabled in plan mode: {failures}"

    def test_high_risk_tools_not_in_plan_mode_allowed(self):
        """HIGH_RISK_TOOLS must not appear in PLAN_MODE_ALLOWED_TOOLS."""
        intersection = HIGH_RISK_TOOLS & PLAN_MODE_ALLOWED_TOOLS
        assert not intersection, f"HIGH_RISK_TOOLS in PLAN_MODE_ALLOWED_TOOLS: {intersection}"
