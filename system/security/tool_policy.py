"""
AI Lab -- Backend Tool Policy / Plan Mode / Read-Only Controls

Tool policy concepts adapted from Odysseus (MIT License)
Sources:
- src/tool_security.py
- src/tool_policy.py
Original copyright: Copyright (c) 2025 Odysseus Contributors
Modifications: Rewritten for AI Lab backend-governed tool policy / system_entry model.

Responsibilities:
- Classify tools by risk/metadata (read_only, mutating, external_call, high_risk, etc.)
- Enforce plan/read-only mode backend gate (not prompt-only)
- Detect guide-only / no-tools user intent as advisory metadata only
- Return clean tool failure results for blocked tools

Architecture:
- Pure deterministic utility -- no side effects beyond lookup
- No lifecycle, governance, execution_result, or memory authority
- Tool-level pre-gate only -- does not bypass system_entry
- Fail-closed for unknown/unclassified tools in plan mode
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Tool Metadata Classification
# ---------------------------------------------------------------------------
# Each tool is classified by its side-effect profile.
# These flags are used by plan-mode enforcement and risk assessment.
# Unknown tools default to the most restrictive classification (fail-closed).

TOOL_METADATA: Dict[str, Dict[str, bool]] = {
    # --- Production tools ---
    "add_numbers":       {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "cube_number":       {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "divide_numbers":    {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "factorial":         {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "fibonacci":         {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "list_files":        {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "multiply_numbers":  {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "multiply_string":   {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "read_file":         {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "read_webpage":      {"read_only": True,  "mutating": False, "external_call": True,  "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "square_number":     {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "square_root":       {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "subtract_numbers":  {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "web_search":        {"read_only": True,  "mutating": False, "external_call": True,  "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "finalize_output":   {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "write_file":        {"read_only": False, "mutating": True,  "external_call": False, "high_risk": False, "requires_approval": True,  "disabled_in_plan_mode": True},
    # --- ADOPT-005B quick-win tools ---
    "grep":              {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "glob":              {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "edit_file":         {"read_only": False, "mutating": True,  "external_call": False, "high_risk": False, "requires_approval": True,  "disabled_in_plan_mode": True},
    # --- Non-production tools ---
    "bad_add":           {"read_only": False, "mutating": True,  "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": True},
    "health_check_system": {"read_only": True, "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "inspect_manager_section": {"read_only": True, "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
    "migrate_error_handling": {"read_only": False, "mutating": True, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": True},
    "rebuild_tool_index": {"read_only": False, "mutating": True, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": True},
    "run_python":        {"read_only": False, "mutating": False, "external_call": False, "high_risk": True,  "requires_approval": False, "disabled_in_plan_mode": True},
    "run_system_maintenance": {"read_only": False, "mutating": True, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": True},
    "self_test_system":  {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False},
}


# ---------------------------------------------------------------------------
# Plan Mode / Read-Only Mode Allowlist
# ---------------------------------------------------------------------------
# Fail-closed: only tools explicitly listed here are allowed in plan mode.
# Any tool not in this set is BLOCKED when plan/read-only mode is active.
# Unknown tools are also blocked (fail-closed).

PLAN_MODE_ALLOWED_TOOLS: Set[str] = {
    "add_numbers",
    "cube_number",
    "divide_numbers",
    "factorial",
    "fibonacci",
    "list_files",
    "multiply_numbers",
    "multiply_string",
    "read_file",
    "read_webpage",
    "square_number",
    "square_root",
    "subtract_numbers",
    "web_search",
    "finalize_output",
    "health_check_system",
    "inspect_manager_section",
    "self_test_system",
    "grep",
    "glob",
}


# ---------------------------------------------------------------------------
# High-Risk Tools (blocked in ALL modes)
# ---------------------------------------------------------------------------
# These tools represent extreme risk (code execution, shell access, etc.)
# and are blocked regardless of execution mode.

HIGH_RISK_TOOLS: Set[str] = {
    "run_python",
}


# ---------------------------------------------------------------------------
# Guide-Only / No-Tools Intent Detection
# ---------------------------------------------------------------------------
# Adapted from Odysseus _GUIDE_ONLY_PATTERNS.
# This is ADVISORY ONLY -- it produces metadata, it does NOT block tools.
# The caller (orchestrator / governance) decides whether to act on it.

_GUIDE_ONLY_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason)
    for pattern, reason in (
        (r"\bguide[-\s]?only mode\b", "guide-only mode requested"),
        (r"\bno[-\s]?tools? mode\b", "no-tools mode requested"),
        (r"\bdo not use (?:any )?tools?\b", "user forbade tool use"),
        (r"\bdon'?t use (?:any )?tools?\b", "user forbade tool use"),
        (r"\bnot allowed to use (?:any )?tools?\b", "user forbade tool use"),
        (r"\bplan only\b", "plan-only mode requested"),
        (r"\bjust explain\b", "user requested explanation only"),
        (r"\bguide me only\b", "user requested guidance only"),
        (r"\bexplain without tools\b", "user requested explanation without tools"),
        (r"\bno tool calls\b", "user forbade tool calls"),
    )
)


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolPolicyResult:
    """Result of a tool policy check."""
    allowed: bool
    reason: Optional[str] = None
    detail: Optional[str] = None
    tool_name: Optional[str] = None
    mode: str = "normal"

    def to_dict(self) -> Dict:
        if self.allowed:
            return {"status": "success", "allowed": True, "tool_name": self.tool_name, "mode": self.mode}
        return {
            "status": "failure",
            "reason": self.reason or "tool_policy_blocked",
            "detail": self.detail or "tool blocked by policy",
            "tool_name": self.tool_name,
            "mode": self.mode,
        }


@dataclass(frozen=True)
class GuideOnlyResult:
    """Advisory result of guide-only intent detection."""
    is_guide_only: bool
    reason: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "is_guide_only": self.is_guide_only,
            "reason": self.reason,
            "advisory_only": True,
        }


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def get_tool_metadata(tool_name: str) -> Optional[Dict[str, bool]]:
    """Return metadata for a tool, or None if unknown."""
    return TOOL_METADATA.get(tool_name)


def is_read_only_tool(tool_name: str) -> bool:
    """Return True if the tool is classified as read-only."""
    meta = get_tool_metadata(tool_name)
    if meta is None:
        return False  # Unknown = not read-only (fail-closed)
    return meta.get("read_only", False)


def is_mutating_tool(tool_name: str) -> bool:
    """Return True if the tool performs mutation (write, delete, etc.)."""
    meta = get_tool_metadata(tool_name)
    if meta is None:
        return True  # Unknown = mutating (fail-closed)
    return meta.get("mutating", False)


def is_high_risk_tool(tool_name: str) -> bool:
    """Return True if the tool is high-risk (blocked in all modes)."""
    return tool_name in HIGH_RISK_TOOLS


def check_tool_policy(tool_name: str, mode: str = "normal") -> ToolPolicyResult:
    """
    Check whether a tool is permitted under the current execution mode.

    Args:
        tool_name: The name of the tool to check.
        mode: Execution mode. "normal" allows all non-high-risk tools.
              "plan", "read_only", or "guide_only" enforce allowlist (fail-closed).

    Returns:
        ToolPolicyResult with allowed=True/False and reason detail.
    """
    # Normalize mode
    mode = (mode or "normal").strip().lower()

    # --- HIGH-RISK BLOCK (all modes) ---
    if is_high_risk_tool(tool_name):
        return ToolPolicyResult(
            allowed=False,
            reason="tool_policy_blocked",
            detail=f"high-risk tool '{tool_name}' blocked in all modes",
            tool_name=tool_name,
            mode=mode,
        )

    # --- NORMAL MODE ---
    if mode == "normal":
        return ToolPolicyResult(
            allowed=True,
            tool_name=tool_name,
            mode=mode,
        )

    # --- PLAN / READ-ONLY / GUIDE-ONLY MODE ---
    if mode in ("plan", "read_only", "guide_only"):
        if tool_name in PLAN_MODE_ALLOWED_TOOLS:
            return ToolPolicyResult(
                allowed=True,
                tool_name=tool_name,
                mode=mode,
            )
        # Unknown or not in allowlist -> fail closed
        meta = get_tool_metadata(tool_name)
        if meta is None:
            detail = f"unknown tool '{tool_name}' blocked in {mode} mode (fail-closed)"
        elif meta.get("mutating"):
            detail = f"mutating tool '{tool_name}' blocked in {mode} mode"
        elif meta.get("external_call"):
            detail = f"external-call tool '{tool_name}' blocked in {mode} mode"
        else:
            detail = f"tool '{tool_name}' not in {mode} mode allowlist"
        return ToolPolicyResult(
            allowed=False,
            reason="plan_mode_blocked" if mode == "plan" else "tool_policy_blocked",
            detail=detail,
            tool_name=tool_name,
            mode=mode,
        )

    # --- UNKNOWN MODE ---
    return ToolPolicyResult(
        allowed=False,
        reason="tool_policy_blocked",
        detail=f"unknown policy mode '{mode}'",
        tool_name=tool_name,
        mode=mode,
    )


def detect_guide_only_intent(text: str) -> GuideOnlyResult:
    """
    Detect whether user text expresses a guide-only / no-tools intent.

    This is ADVISORY ONLY. It returns metadata; it does NOT block tools.
    The caller (orchestrator / governance) decides whether to use this signal.

    Adapted from Odysseus src/tool_policy.py detect_guide_only_turn().
    """
    if not isinstance(text, str) or not text.strip():
        return GuideOnlyResult(is_guide_only=False, reason=None)

    normalized = re.sub(r"\s+", " ", text.strip())
    for pattern, reason in _GUIDE_ONLY_PATTERNS:
        if pattern.search(normalized):
            return GuideOnlyResult(is_guide_only=True, reason=reason)

    return GuideOnlyResult(is_guide_only=False, reason=None)


def list_plan_mode_allowed_tools() -> List[str]:
    """Return the sorted list of tools permitted in plan/read-only mode."""
    return sorted(PLAN_MODE_ALLOWED_TOOLS)


def list_high_risk_tools() -> List[str]:
    """Return the sorted list of high-risk tools (blocked in all modes)."""
    return sorted(HIGH_RISK_TOOLS)
