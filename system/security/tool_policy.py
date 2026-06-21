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
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Tool Metadata Classification
# ---------------------------------------------------------------------------
# Each tool is classified by its side-effect profile.
# These flags are used by plan-mode enforcement and risk assessment.
# Unknown tools default to the most restrictive classification (fail-closed).

TOOL_METADATA: Dict[str, Dict[str, Any]] = {
    # --- Production tools ---
    "add_numbers":       {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_computation", "reversibility": "read_only_no_state_change", "side_effect_summary": "adds two numbers locally", "confirmation_text_template": "This step wants to use `add_numbers` locally. No data leaves the system."},
    "cube_number":       {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_computation", "reversibility": "read_only_no_state_change", "side_effect_summary": "calculates the cube of a number locally", "confirmation_text_template": "This step wants to use `cube_number` locally. No data leaves the system."},
    "divide_numbers":    {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_computation", "reversibility": "read_only_no_state_change", "side_effect_summary": "divides two numbers locally", "confirmation_text_template": "This step wants to use `divide_numbers` locally. No data leaves the system."},
    "factorial":         {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_computation", "reversibility": "read_only_no_state_change", "side_effect_summary": "computes factorial locally", "confirmation_text_template": "This step wants to use `factorial` locally. No data leaves the system."},
    "fibonacci":         {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_computation", "reversibility": "read_only_no_state_change", "side_effect_summary": "generates Fibonacci sequence locally", "confirmation_text_template": "This step wants to use `fibonacci` locally. No data leaves the system."},
    "list_files":        {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_filesystem_read", "reversibility": "read_only_no_state_change", "side_effect_summary": "lists files in a local directory", "confirmation_text_template": "This step wants to use `list_files` locally. No data leaves the system."},
    "multiply_numbers":  {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_computation", "reversibility": "read_only_no_state_change", "side_effect_summary": "multiplies two numbers locally", "confirmation_text_template": "This step wants to use `multiply_numbers` locally. No data leaves the system."},
    "multiply_string":   {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_computation", "reversibility": "read_only_no_state_change", "side_effect_summary": "repeats a string locally", "confirmation_text_template": "This step wants to use `multiply_string` locally. No data leaves the system."},
    "read_file":         {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_filesystem_read", "reversibility": "read_only_no_state_change", "side_effect_summary": "reads content of a local file", "confirmation_text_template": "This step wants to use `read_file` locally. No data leaves the system."},
    "read_webpage":      {"read_only": True,  "mutating": False, "external_call": True,  "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": True, "provider": "target_url_host (supplied at runtime)", "destination": "supplied URL (supplied at runtime)", "data_leaving_system": "requested URL and standard HTTP request metadata", "privacy_classification": "external_url_fetch", "reversibility": "read_only_no_state_change", "side_effect_summary": "fetches the requested webpage from an external URL", "confirmation_text_template": "This step wants to fetch an external webpage using `read_webpage`. The requested URL may be contacted outside the local system. This is read-only and does not modify files or workflow state."},
    "square_number":     {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_computation", "reversibility": "read_only_no_state_change", "side_effect_summary": "calculates the square of a number locally", "confirmation_text_template": "This step wants to use `square_number` locally. No data leaves the system."},
    "square_root":       {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_computation", "reversibility": "read_only_no_state_change", "side_effect_summary": "computes square root locally", "confirmation_text_template": "This step wants to use `square_root` locally. No data leaves the system."},
    "subtract_numbers":  {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_computation", "reversibility": "read_only_no_state_change", "side_effect_summary": "subtracts two numbers locally", "confirmation_text_template": "This step wants to use `subtract_numbers` locally. No data leaves the system."},
    "web_search":        {"read_only": True,  "mutating": False, "external_call": True,  "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": True, "provider": "DuckDuckGo or SearXNG (auto-selected)", "destination": "https://html.duckduckgo.com/html/ or configured SEARXNG_BASE_URL", "data_leaving_system": "search query text", "privacy_classification": "external_query", "reversibility": "read_only_no_state_change", "side_effect_summary": "sends query text to external search provider and retrieves search results", "confirmation_text_template": "This step wants to use `web_search`. The search query text may be sent to the configured search provider (DuckDuckGo or SearXNG) outside the local system. This is read-only and does not modify files or workflow state."},
    "finalize_output":   {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_passthrough", "reversibility": "read_only_no_state_change", "side_effect_summary": "returns provided text as output", "confirmation_text_template": "This step wants to use `finalize_output` locally. No data leaves the system."},
    "write_file":        {"read_only": False, "mutating": True,  "external_call": False, "high_risk": False, "requires_approval": True,  "disabled_in_plan_mode": True,  "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_filesystem_write", "reversibility": "creates_or_overwrites_file", "side_effect_summary": "writes content to a file in the project directory", "confirmation_text_template": "This step wants to use `write_file`. This tool requires approval because it writes to a file in the project directory."},
    # --- ADOPT-005B quick-win tools ---
    "grep":              {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_filesystem_read", "reversibility": "read_only_no_state_change", "side_effect_summary": "searches for a pattern inside local files", "confirmation_text_template": "This step wants to use `grep` locally. No data leaves the system."},
    "glob":              {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_filesystem_read", "reversibility": "read_only_no_state_change", "side_effect_summary": "discovers files matching a pattern locally", "confirmation_text_template": "This step wants to use `glob` locally. No data leaves the system."},
    "edit_file":         {"read_only": False, "mutating": True,  "external_call": False, "high_risk": False, "requires_approval": True,  "disabled_in_plan_mode": True,  "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_filesystem_write", "reversibility": "modifies_file_contents", "side_effect_summary": "modifies file contents by replacing text", "confirmation_text_template": "This step wants to use `edit_file`. This tool requires approval because it modifies file contents."},
    "append_file":       {"read_only": False, "mutating": True,  "external_call": False, "high_risk": False, "requires_approval": True,  "disabled_in_plan_mode": True,  "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_filesystem_write", "reversibility": "appends_to_file_contents", "side_effect_summary": "appends content to an existing file in the project directory", "confirmation_text_template": "This step wants to use `append_file`. This tool requires approval because it writes to a file in the project directory."},
    # --- Non-production tools ---
    "bad_add":           {"read_only": False, "mutating": True,  "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": True,  "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_computation", "reversibility": "mutating_unsafe", "side_effect_summary": "adds two numbers with unsafe error handling", "confirmation_text_template": "This step wants to use `bad_add`. This is a non-production tool."},
    "health_check_system": {"read_only": True, "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_system_read", "reversibility": "read_only_no_state_change", "side_effect_summary": "reads system directory structure for integrity checks", "confirmation_text_template": "This step wants to use `health_check_system` locally. No data leaves the system."},
    "inspect_manager_section": {"read_only": True, "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_filesystem_read", "reversibility": "read_only_no_state_change", "side_effect_summary": "reads a section of manager.py by keyword match", "confirmation_text_template": "This step wants to use `inspect_manager_section` locally. No data leaves the system."},
    "migrate_error_handling": {"read_only": False, "mutating": True, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": True,  "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_filesystem_write", "reversibility": "modifies_multiple_files", "side_effect_summary": "migrates error handling patterns across files", "confirmation_text_template": "This step wants to use `migrate_error_handling`. This is a non-production mutating tool."},
    "rebuild_tool_index": {"read_only": False, "mutating": True, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": True,  "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_system_write", "reversibility": "modifies_registry_and_files", "side_effect_summary": "rebuilds tool registry by scanning directories", "confirmation_text_template": "This step wants to use `rebuild_tool_index`. This is a non-production mutating tool."},
    "run_python":        {"read_only": False, "mutating": False, "external_call": False, "high_risk": True,  "requires_approval": False, "disabled_in_plan_mode": True,  "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "arbitrary_code_execution", "reversibility": "irreversible", "side_effect_summary": "executes arbitrary Python code with full system access", "confirmation_text_template": "This step wants to use `run_python`. This tool is high-risk and blocked in all modes."},
    "run_system_maintenance": {"read_only": False, "mutating": True, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": True,  "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_system_write", "reversibility": "modifies_system_state", "side_effect_summary": "runs maintenance tasks that may modify system files", "confirmation_text_template": "This step wants to use `run_system_maintenance`. This is a non-production mutating tool."},
    "self_test_system":  {"read_only": True,  "mutating": False, "external_call": False, "high_risk": False, "requires_approval": False, "disabled_in_plan_mode": False, "overrideable_with_user_control": False, "provider": None, "destination": None, "data_leaving_system": None, "privacy_classification": "local_system_read", "reversibility": "read_only_no_state_change", "side_effect_summary": "tests and verifies integrity of tools and agents locally", "confirmation_text_template": "This step wants to use `self_test_system` locally. No data leaves the system."},
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

def get_tool_metadata(tool_name: str) -> Optional[Dict[str, Any]]:
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


# ---------------------------------------------------------------------------
# External-Call Risk Metadata Helpers (ISSUE-098H)
# ---------------------------------------------------------------------------
# Deterministic, backend-owned metadata for external-call risk acceptance.
# No LLM inference. No side effects. No registry mutations.
# Fail-closed for unknown, high-risk, or approval-required tools.


def _extract_url_from_tool_args(tool_args: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract URL from tool arguments for read_webpage."""
    if not tool_args:
        return None
    url = tool_args.get("url") or tool_args.get("path")
    if isinstance(url, str) and url.strip():
        url = url.strip().strip('"').strip("'")
        return url
    return None


def _sanitize_url_for_display(url: str) -> str:
    """Sanitize a URL for display: strip credentials and fragment."""
    parsed = urlparse(url)
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc += f":{parsed.port}"
    # Rebuild without username/password and without fragment
    from urllib.parse import urlunparse
    safe = urlunparse((
        parsed.scheme,
        netloc,
        parsed.path,
        parsed.params,
        parsed.query,
        "",
    ))
    return safe


def get_external_call_risk_metadata(
    tool_name: str,
    tool_args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Return deterministic external-call risk metadata for a tool.

    Args:
        tool_name: Name of the tool.
        tool_args: Optional runtime tool arguments (e.g., {"url": "..."}).

    Returns:
        JSON-safe dict with risk metadata. Fail-closed for unknown,
        high-risk, approval-required, or incomplete metadata.
    """
    base = get_tool_metadata(tool_name)

    # Fail-closed for unknown tools
    if base is None:
        return {
            "tool_name": tool_name,
            "external_call": False,
            "provider": None,
            "destination": None,
            "data_leaving_system": None,
            "privacy_classification": None,
            "risk_level": "HIGH",
            "read_only": False,
            "mutating": True,
            "high_risk": False,
            "requires_approval": False,
            "overrideable_with_user_control": False,
            "confirmation_text": None,
            "block_reason_if_not_overrideable": "unknown_tool_not_classified",
            "incomplete": True,
            "incomplete_reason": "tool not found in metadata registry",
        }

    external_call = bool(base.get("external_call", False))
    read_only = bool(base.get("read_only", False))
    mutating = bool(base.get("mutating", False))
    high_risk = bool(base.get("high_risk", False))
    requires_approval = bool(base.get("requires_approval", False))

    # Risk level mapping
    if high_risk:
        risk_level = "CRITICAL"
    elif requires_approval:
        risk_level = "HIGH"
    elif external_call:
        risk_level = "MEDIUM"
    elif mutating:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    result: Dict[str, Any] = {
        "tool_name": tool_name,
        "external_call": external_call,
        "provider": base.get("provider"),
        "destination": base.get("destination"),
        "data_leaving_system": base.get("data_leaving_system"),
        "privacy_classification": base.get("privacy_classification"),
        "risk_level": risk_level,
        "read_only": read_only,
        "mutating": mutating,
        "high_risk": high_risk,
        "requires_approval": requires_approval,
        "overrideable_with_user_control": False,
        "confirmation_text": None,
        "block_reason_if_not_overrideable": None,
        "incomplete": False,
        "incomplete_reason": None,
    }

    # Overrideability rules
    if high_risk:
        result["overrideable_with_user_control"] = False
        result["block_reason_if_not_overrideable"] = "high_risk_tool_blocked_in_all_modes"
        result["confirmation_text"] = base.get("confirmation_text_template")
    elif requires_approval:
        result["overrideable_with_user_control"] = False
        result["block_reason_if_not_overrideable"] = "approval_required_tool_must_use_approval_system"
        result["confirmation_text"] = base.get("confirmation_text_template")
    elif not external_call:
        result["overrideable_with_user_control"] = False
        result["block_reason_if_not_overrideable"] = "not_an_external_call_tool"
        result["confirmation_text"] = base.get("confirmation_text_template")
    else:
        # External-call tool — check metadata completeness and tool_args
        if tool_name == "read_webpage":
            url = _extract_url_from_tool_args(tool_args)
            if not url:
                result["overrideable_with_user_control"] = False
                result["block_reason_if_not_overrideable"] = "missing_url_in_tool_args"
                result["incomplete"] = True
                result["incomplete_reason"] = "read_webpage requires a URL argument"
                result["confirmation_text"] = base.get("confirmation_text_template")
            else:
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https"):
                    result["overrideable_with_user_control"] = False
                    result["block_reason_if_not_overrideable"] = (
                        f"unsupported_url_scheme_{parsed.scheme or 'none'}"
                    )
                    result["incomplete"] = True
                    result["incomplete_reason"] = "URL scheme must be http or https"
                    result["confirmation_text"] = base.get("confirmation_text_template")
                elif parsed.username or parsed.password:
                    result["overrideable_with_user_control"] = False
                    result["block_reason_if_not_overrideable"] = "credentials_embedded_in_url"
                    result["incomplete"] = True
                    result["incomplete_reason"] = "URL contains embedded credentials"
                    result["confirmation_text"] = base.get("confirmation_text_template")
                else:
                    result["overrideable_with_user_control"] = True
                    result["block_reason_if_not_overrideable"] = None
                    sanitized = _sanitize_url_for_display(url)
                    host = parsed.hostname or "unknown_host"
                    template = base.get("confirmation_text_template", "")
                    result["confirmation_text"] = (
                        f"{template} Target host: `{host}`."
                    )
                    result["destination"] = sanitized
                    result["provider"] = host
        else:
            # web_search or other external-call tools with sufficient static metadata
            result["overrideable_with_user_control"] = True
            result["block_reason_if_not_overrideable"] = None
            result["confirmation_text"] = base.get("confirmation_text_template")

    # Fallback confirmation text for any non-incomplete case where it wasn't set
    if result["confirmation_text"] is None and not result["incomplete"]:
        result["confirmation_text"] = base.get("confirmation_text_template")

    return result
