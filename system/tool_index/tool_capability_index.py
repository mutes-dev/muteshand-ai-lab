"""
PDIAG-006 Slice 1 — Deterministic AG1 Tool Capability Grounding

Read-only composed capability view for AG1 prompt enrichment.

Merges:
- system/tool_index/tools.json (canonical runtime tool index)
- system/security/tool_policy.py (risk/policy metadata)

Does NOT:
- Execute tools
- Use LLMs
- Mutate tools.json
- Create a third authority source
"""

import json
import os
from typing import Any, Dict, List, Optional

from system.security.tool_policy import TOOL_METADATA

_TOOL_INDEX_PATH = os.path.join("system", "tool_index", "tools.json")


def _read_category_from_manifest(tool_data: Dict[str, Any], tool_name: str) -> str:
    """Read category from manifest, with conservative fallback."""
    category = tool_data.get("category")
    if category:
        return category
    
    # Conservative fallback for missing metadata
    print(f"WARNING: Tool '{tool_name}' missing category in manifest, using conservative fallback")
    return "utility"


def _read_output_kind_from_manifest(tool_data: Dict[str, Any], tool_name: str) -> str:
    """Read output_kind from manifest, with conservative fallback."""
    output_kind = tool_data.get("output_kind")
    if output_kind:
        return output_kind
    
    # Conservative fallback for missing metadata
    print(f"WARNING: Tool '{tool_name}' missing output_kind in manifest, using conservative fallback")
    return "text"


def _read_use_when_from_manifest(tool_data: Dict[str, Any], tool_name: str) -> List[str]:
    """Read use_when from manifest, with conservative fallback."""
    use_when = tool_data.get("use_when")
    if use_when and isinstance(use_when, list):
        return use_when
    
    # Conservative fallback for missing metadata
    print(f"WARNING: Tool '{tool_name}' missing use_when in manifest, using conservative fallback")
    return ["only when the tool description directly matches the requested action"]


def _read_do_not_use_when_from_manifest(tool_data: Dict[str, Any], tool_name: str) -> List[str]:
    """Read do_not_use_when from manifest, with conservative fallback."""
    do_not_use_when = tool_data.get("do_not_use_when")
    if do_not_use_when and isinstance(do_not_use_when, list):
        return do_not_use_when
    
    # Conservative fallback for missing metadata
    print(f"WARNING: Tool '{tool_name}' missing do_not_use_when in manifest, using conservative fallback")
    return ["tasks not directly described by this tool's documented purpose"]


def build_ag1_capability_view() -> Dict[str, Dict[str, Any]]:
    """
    Build a deterministic, read-only composed capability view for AG1.

    Returns:
        Dict mapping production tool_name -> composed capability metadata.
    """
    with open(_TOOL_INDEX_PATH, "r", encoding="utf-8") as f:
        tool_index = json.load(f)

    view: Dict[str, Dict[str, Any]] = {}
    for tool_name, tool_data in tool_index.items():
        if not tool_data.get("production", False):
            continue

        policy_meta = TOOL_METADATA.get(tool_name, {})
        inputs = tool_data.get("inputs", {})
        
        # Read capability metadata from manifest instead of inferring
        category = _read_category_from_manifest(tool_data, tool_name)
        output_kind = _read_output_kind_from_manifest(tool_data, tool_name)
        use_when = _read_use_when_from_manifest(tool_data, tool_name)
        do_not_use_when = _read_do_not_use_when_from_manifest(tool_data, tool_name)

        view[tool_name] = {
            "name": tool_name,
            "category": category,
            "args": inputs,
            "arg_order": tool_data.get("arg_order", []),
            "description": tool_data.get("description", ""),
            "output_kind": output_kind,
            "production": True,
            "read_only": bool(policy_meta.get("read_only", False)),
            "mutating": bool(policy_meta.get("mutating", False)),
            "external_call": bool(policy_meta.get("external_call", False)),
            "high_risk": bool(policy_meta.get("high_risk", False)),
            "requires_approval": bool(policy_meta.get("requires_approval", False)),
            "disabled_in_plan_mode": bool(policy_meta.get("disabled_in_plan_mode", False)),
            "overrideable_with_user_control": bool(policy_meta.get("overrideable_with_user_control", False)),
            "provider": policy_meta.get("provider"),
            "destination": policy_meta.get("destination"),
            "data_leaving_system": bool(policy_meta.get("data_leaving_system")) if policy_meta.get("data_leaving_system") is not None else None,
            "privacy_classification": policy_meta.get("privacy_classification"),
            "reversibility": policy_meta.get("reversibility"),
            "side_effect_summary": policy_meta.get("side_effect_summary"),
            "use_when": use_when,
            "do_not_use_when": do_not_use_when,
        }

    return view


def format_ag1_capability_prompt_line(cap: Dict[str, Any]) -> str:
    """
    Format a single capability entry into a concise prompt line for AG1.

    Returns a single multi-line string (joined with \\n) per tool.
    """
    name = cap["name"]
    args_dict = cap.get("args", {})
    arg_names = []
    for i, (arg_key, arg_type) in enumerate(args_dict.items()):
        if arg_type == "string":
            arg_names.append(f'"{arg_key}"')
        else:
            arg_names.append(f"number{i+1}")
    args_str = " ".join(arg_names)

    category = cap.get("category", "utility")
    description = cap.get("description", "") or cap.get("side_effect_summary", "")

    lines = [f"- {name} {args_str}"]
    lines.append(f"  category: {category}")
    if description:
        lines.append(f"  use: {description}")

    return "\n".join(lines)


def build_ag1_capability_prompt() -> str:
    """
    Build the full Available Tools prompt section for AG1.

    Returns a single string ready for insertion into the AG1 prompt.
    """
    view = build_ag1_capability_view()
    tool_lines = [format_ag1_capability_prompt_line(cap) for cap in view.values()]
    return "\n".join(tool_lines)
