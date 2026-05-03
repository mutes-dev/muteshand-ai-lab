"""Tool Call Converter — Agent Output → Core Interface.

Extracts and validates agent output to produce a clean tool_call string
for system_entry. This module contains NO execution logic — only
conversion and validation.
"""

import json
import os
import re
import shlex


def _load_tool_index():
    """Load tool index for validation."""
    tool_index_path = os.path.join("system", "tool_index", "tools.json")
    with open(tool_index_path, "r", encoding="utf-8") as f:
        return json.load(f)


def convert_agent_output_to_tool_call(tool_line: str) -> tuple[str | None, dict | None]:
    """
    Convert agent output line to validated tool_call.

    Args:
        tool_line: Line containing "USE_TOOL: <tool_name> <args>"

    Returns:
        tuple: (tool_call, failure_result)
        - On valid: (tool_call_string, None)
        - On invalid: (None, failure_result_dict)

    EXACT logic moved from agent_executor.py (lines 452-526).
    NO behavior change — pure extraction.
    """
    # --- EXTRACTION ---
    tool_call = tool_line.split("USE_TOOL:", 1)[1].strip()
    raw_call = tool_call.strip()

    # --- VALIDATION GATE (STRICT) ---

    # shlex parsing
    try:
        parts = shlex.split(raw_call, posix=False)
    except ValueError:
        failure = {
            "status": "failure",
            "reason": "invalid_tool_syntax"
        }
        return None, failure

    if len(parts) == 0:
        failure = {
            "status": "failure",
            "reason": "invalid_tool_syntax"
        }
        return None, failure

    tool_name = parts[0]
    args = parts[1:]

    # TOOL NAME VALIDATION
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', tool_name):
        failure = {
            "status": "failure",
            "reason": "invalid_tool_syntax"
        }
        return None, failure

    # ARGUMENT VALIDATION
    for arg in args:
        if re.match(r'^-?\d+$', arg):  # integer
            continue
        if re.match(r'^-?\d+\.\d+$', arg):  # float
            continue
        if re.match(r'^".*"$', arg):  # quoted string
            continue

        failure = {
            "status": "failure",
            "reason": "invalid_tool_syntax"
        }
        return None, failure

    # TOOL INDEX VALIDATION
    try:
        tool_index = _load_tool_index()
    except Exception:
        failure = {
            "status": "failure",
            "reason": "tool_index_unavailable"
        }
        return None, failure

    if tool_name not in tool_index:
        failure = {
            "status": "failure",
            "reason": "unknown_tool"
        }
        return None, failure

    if not tool_index[tool_name].get("production", False):
        failure = {
            "status": "failure",
            "reason": "non_production_tool"
        }
        return None, failure

    # --- VALIDATION PASSED ---
    return tool_call, None
