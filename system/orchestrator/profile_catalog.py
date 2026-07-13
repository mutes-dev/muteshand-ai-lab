"""
Tool Profile Catalog — TOOL_PROFILE_GATING_CONTRACT_V1

Read-only profile definitions and scoped tool catalog builder.

Profiles defined:
- DocumentReadProfile
- DocumentSummaryProfile
- WebReadProfile
- WebSearchProfile
- WebResearchProfile
- ComputeProfile
- FileMutationProfile
- GeneralFallbackProfile

This module does NOT:
- Execute tools
- Select profiles
- Override planner authority
- Influence lifecycle/governance/execution_result
"""

import json
import os
from typing import Any, Dict, List, Optional, Set


_PROFILE_CATALOG_PATH = os.path.join("system", "tool_index", "tools.json")

_PROFILE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "DocumentReadProfile": {
        "allowed_tools": [
            "read_file",
            "read_pdf",
            "read_docx",
            "read_csv",
            "read_spreadsheet",
            "read_image_text",
            "read_pdf_ocr",
            "list_files",
            "preview_table_schema",
            "resolve_table_reference",
            "finalize_output",
        ],
        "allowed_tool_families": [
            "file_read",
            "folder_list",
            "text_finalization",
        ],
    },
    "DocumentSummaryProfile": {
        "allowed_tools": [
            "read_file",
            "read_pdf",
            "read_docx",
            "read_csv",
            "read_spreadsheet",
            "read_image_text",
            "read_pdf_ocr",
            "semantic_transform",
            "finalize_output",
        ],
        "allowed_tool_families": [
            "file_read",
            "folder_list",
            "text_synthesis",
            "text_finalization",
        ],
    },
    "WebReadProfile": {
        "allowed_tools": [
            "read_webpage",
            "finalize_output",
        ],
        "allowed_tool_families": [
            "web_read",
            "text_finalization",
        ],
    },
    "WebSearchProfile": {
        "allowed_tools": [
            "web_search",
            "finalize_output",
        ],
        "allowed_tool_families": [
            "web_search",
            "text_finalization",
        ],
    },
    "WebResearchProfile": {
        "allowed_tools": [
            "web_search",
            "read_webpage",
            "finalize_output",
        ],
        "allowed_tool_families": [
            "web_search",
            "web_read",
            "text_finalization",
        ],
    },
    "ComputeProfile": {
        "allowed_tools": [
            "add_numbers",
            "subtract_numbers",
            "multiply_numbers",
            "divide_numbers",
            "square_number",
            "cube_number",
            "square_root",
            "factorial",
            "fibonacci",
            "finalize_output",
        ],
        "allowed_tool_families": [
            "math",
            "text_finalization",
        ],
    },
    "FileMutationProfile": {
        "allowed_tools": [
            "write_file",
            "edit_file",
            "append_file",
            "read_file",
            "list_files",
            "finalize_output",
        ],
        "allowed_tool_families": [
            "file_write",
            "file_read",
            "folder_list",
            "text_finalization",
        ],
    },
    "GeneralFallbackProfile": {
        "allowed_tools": [
            "add_numbers",
            "subtract_numbers",
            "multiply_numbers",
            "divide_numbers",
            "square_number",
            "cube_number",
            "square_root",
            "factorial",
            "fibonacci",
            "multiply_string",
            "read_file",
            "read_pdf",
            "read_docx",
            "read_csv",
            "read_spreadsheet",
            "read_image_text",
            "read_pdf_ocr",
            "list_files",
            "grep",
            "glob",
            "read_webpage",
            "semantic_transform",
            "finalize_output",
            "write_file",
            "append_file",
            "edit_file",
        ],
        "allowed_tool_families": [
            "math",
            "string_utility",
            "file_read",
            "folder_list",
            "web_read",
            "text_synthesis",
            "text_finalization",
            "text_processing",
            "file_mutation",
            "file_write",
        ],
    },
}


def get_profile_names() -> List[str]:
    """Return list of all defined profile names."""
    return list(_PROFILE_DEFINITIONS.keys())


def get_profile_definition(profile_name: str) -> Optional[Dict[str, Any]]:
    """Return profile definition dict or None if not found."""
    return _PROFILE_DEFINITIONS.get(profile_name)


def get_allowed_tools(profile_name: str) -> Optional[Set[str]]:
    """
    Return set of allowed tool names for the profile.
    Returns None only for profiles that explicitly allow all production tools.
    GeneralFallbackProfile now returns an explicit snapshot allowlist.
    Returns empty set for unknown profiles.
    """
    defn = _PROFILE_DEFINITIONS.get(profile_name)
    if defn is None:
        return set()
    tools = defn.get("allowed_tools")
    if tools is None:
        return None
    return set(tools)


def get_allowed_tool_families(profile_name: str) -> Optional[Set[str]]:
    """
    Return set of allowed tool families for the profile.
    Returns None for GeneralFallbackProfile.
    Returns empty set for unknown profiles.
    """
    defn = _PROFILE_DEFINITIONS.get(profile_name)
    if defn is None:
        return set()
    families = defn.get("allowed_tool_families")
    if families is None:
        return None
    return set(families)


def is_tool_in_profile(tool_name: str, profile_name: str) -> bool:
    """
    Check if a tool is allowed within the given profile.
    GeneralFallbackProfile uses its explicit snapshot allowlist.
    """
    allowed = get_allowed_tools(profile_name)
    if allowed is None:
        return True
    return tool_name in allowed


def build_scoped_tool_index(profile_name: str) -> Dict[str, Dict[str, Any]]:
    """
    Build a scoped tool index dict containing only tools allowed by the profile.

    For GeneralFallbackProfile, returns only its explicit snapshot allowlist.
    For unknown profiles, returns empty dict.
    """
    allowed = get_allowed_tools(profile_name)
    with open(_PROFILE_CATALOG_PATH, "r", encoding="utf-8") as f:
        tool_index = json.load(f)

    if allowed is None:
        return {
            name: data for name, data in tool_index.items()
            if data.get("production", False)
        }

    return {
        name: data for name, data in tool_index.items()
        if data.get("production", False) and name in allowed
    }


def build_scoped_tool_context(profile_name: str) -> str:
    """
    Build a tool context string for the planner prompt, scoped to the profile.
    Format matches the existing planner tool_context format.
    """
    scoped = build_scoped_tool_index(profile_name)
    tool_lines = []
    for tool_name, tool_data in scoped.items():
        inputs = tool_data.get("inputs", {})
        arg_keys = list(inputs.keys())
        arg_names = []
        for i, arg in enumerate(arg_keys):
            if inputs[arg] == "string":
                arg_names.append(f'"{arg}"')
            else:
                arg_names.append(f"number{i+1}")
        args = " ".join(arg_names)
        description = tool_data.get("description", "").strip()
        if description:
            tool_lines.append(f"- {tool_name} {args}\n  use: {description}".strip())
        else:
            tool_lines.append(f"- {tool_name} {args}".strip())
    return "\n".join(tool_lines)


def build_scoped_capability_view(profile_name: str) -> Dict[str, Dict[str, Any]]:
    """
    Build a scoped AG1 capability view for the profile.
    Uses build_ag1_capability_view() and filters to profile-allowed tools.
    """
    from system.tool_index.tool_capability_index import build_ag1_capability_view

    full_view = build_ag1_capability_view()
    allowed = get_allowed_tools(profile_name)

    if allowed is None:
        return full_view

    return {
        name: cap for name, cap in full_view.items()
        if name in allowed
    }


def get_profile_metadata(profile_name: str) -> Dict[str, Any]:
    """
    Return observable profile metadata for trace/observability.
    """
    defn = _PROFILE_DEFINITIONS.get(profile_name)
    if defn is None:
        return {
            "profile_name": profile_name,
            "valid": False,
            "allowed_tools": [],
            "allowed_tool_families": [],
        }

    allowed = get_allowed_tools(profile_name)
    families = get_allowed_tool_families(profile_name)

    return {
        "profile_name": profile_name,
        "valid": True,
        "allowed_tools": sorted(allowed) if allowed is not None else "ALL_PRODUCTION",
        "allowed_tool_families": sorted(families) if families is not None else "ALL",
    }
