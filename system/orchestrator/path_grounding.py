"""
PDIAG-008B8 — Pre-system_entry File Path Grounding Utility

Shared module imported by:
  - system.orchestrator.tool_selection_agent (pre-dispatch, before system_entry)
  - system.orchestrator.step_executor (post-execution fallback read path if needed)

DO NOT import step_executor or agent_executor from here — would create circular imports.
Import chain: tool_selection_agent -> path_grounding -> planning_compiler -> synthesis_dependency_utils
Import chain: step_executor -> path_grounding -> planning_compiler -> synthesis_dependency_utils
"""

import re
import shlex

# === File tool sets ===

# All local-file tools eligible for purpose-path grounding
FILE_PATH_TOOLS = frozenset(["write_file", "read_file", "edit_file", "append_file", "list_files"])

# Mutating tools — grounding MUST happen pre-system_entry (wrong-path write = side effect)
FILE_MUTATING_TOOLS = frozenset(["write_file", "edit_file", "append_file"])

# TLDs that signal a URL/domain rather than a local file
_INTERNET_TLDS = frozenset([
    "com", "org", "net", "io", "edu", "gov", "co", "uk", "de", "fr", "au",
    "ca", "ru", "jp", "cn", "br", "in", "mx", "nl", "se", "no", "fi",
    "html", "htm",
])


def _safe_extract_tool_name_pg(tool_call: str):
    """Extract tool name from a tool_call string. Failure-isolated."""
    if not tool_call or not isinstance(tool_call, str):
        return None
    cleaned = tool_call.strip()
    if cleaned.startswith("USE_TOOL:"):
        cleaned = cleaned.split("USE_TOOL:", 1)[1].strip()
    parts = cleaned.split()
    return parts[0] if parts else None


def _extract_quoted_path_pg(tool_call: str):
    """Extract the first quoted string argument (path token) from a tool call. Failure-isolated."""
    if not tool_call or not isinstance(tool_call, str):
        return None
    try:
        cleaned = tool_call.strip()
        if cleaned.startswith("USE_TOOL:"):
            cleaned = cleaned.split("USE_TOOL:", 1)[1].strip()
        tokens = shlex.split(cleaned)
        return tokens[1] if len(tokens) >= 2 else None
    except Exception:
        return None


def _normalize_path_pg(path: str):
    """Normalize a file path for comparison: lowercase, forward slashes, strip trailing slash."""
    if not path or not isinstance(path, str):
        return None
    return path.replace("\\", "/").lower().rstrip("/")


def _count_valid_raw_filenames(text: str) -> int:
    """
    Count all bare filename patterns (name.ext) in text, excluding URL/TLD-like extensions.
    Used as secondary guard: if count > 1 the purpose is ambiguous.
    """
    all_fns = re.findall(
        r'(?<!\w)([a-zA-Z0-9_.-]+\.[a-zA-Z0-9]{1,10})(?=\s|$|[,;.!?\)])',
        text
    )
    valid = [
        fn for fn in all_fns
        if "/" not in fn and "\\" not in fn
        and not re.match(r'(?i)^https?', fn)
        and fn.rsplit(".", 1)[-1].lower() not in _INTERNET_TLDS
        and len(fn.rsplit(".", 1)[0]) >= 2
    ]
    return len(valid)


def _rebuild_tool_call_with_new_path(original_tool_call: str, new_path: str):
    """
    Replace only the path token (tokens[1]) in original_tool_call with new_path.
    Preserves the original raw suffix (tokens[2:]) exactly — no re-quoting of
    numeric flags like '0 0' for edit_file.

    Returns the corrected call string, or None if rebuild failed.
    Failure-isolated: never raises.
    """
    try:
        cleaned = original_tool_call.strip()
        if cleaned.startswith("USE_TOOL:"):
            cleaned = cleaned.split("USE_TOOL:", 1)[1].strip()

        tokens = shlex.split(cleaned)
        if len(tokens) < 2:
            return None

        # Extract raw suffix after the first two tokens by walking the cleaned string.
        # We use shlex with a StringIO to find the cursor position after consuming
        # tool_name + path_token, preserving the exact original whitespace/quoting
        # for all remaining args.
        try:
            import io
            _lex = shlex.shlex(io.StringIO(cleaned), posix=True)
            _lex.whitespace_split = False
            _lex.whitespace = ' \t\n'
            _lex.get_token()   # consume tool name
            _lex.get_token()   # consume original path token
            _pos = _lex.instream.tell()
            _suffix = cleaned[_pos:].lstrip()
        except Exception:
            # Fallback: find suffix by locating end of first quoted block after tool name
            _after_tool = cleaned[len(tokens[0]):].lstrip()
            _suffix = ""
            if _after_tool.startswith('"'):
                _end = _after_tool.find('"', 1)
                if _end != -1:
                    _suffix = _after_tool[_end + 1:].lstrip()
            if not _suffix and len(tokens) > 2:
                _suffix = " ".join(tokens[2:])

        corrected = f'{tokens[0]} "{new_path}"'
        if _suffix:
            corrected = f'{corrected} {_suffix}'
        return corrected
    except Exception:
        return None


def ground_tool_call_to_purpose_path(tool_call: str, purpose: str, already_attempted: bool = False):
    """
    PDIAG-008B8: Bounded deterministic pre-dispatch file path grounding.

    Checks whether the path in tool_call differs from the single unambiguous
    local filename in the step purpose, and if so returns the corrected tool_call.

    This function does NOT call system_entry — it only computes the corrected call.
    The caller is responsible for calling system_entry with the returned call.

    Activation conditions (ALL must be true):
      1. tool is a local file path tool (FILE_PATH_TOOLS)
      2. purpose contains exactly ONE extractable local file path
      3. raw filename count in purpose is exactly 1 (secondary multi-path guard)
      4. tool_call contains a parseable quoted path
      5. normalized purpose path differs from normalized executed path
      6. purpose path is not URL/domain-like (enforced by _extract_local_file_paths)
      7. already_attempted is False (one correction per step)

    Returns:
      str: corrected tool_call string if grounding should fire
      None: if conditions not met (caller uses original tool_call unchanged)

    NEVER alters content/old_text/new_text/flags.
    NEVER fires when purpose has zero or multiple filenames.
    NEVER fires on URL/domain-like paths.
    NEVER raises — failure-isolated.
    """
    try:
        if already_attempted:
            return None

        current_tool = _safe_extract_tool_name_pg(tool_call)
        if current_tool not in FILE_PATH_TOOLS:
            return None

        if not purpose or not isinstance(purpose, str):
            return None

        # Primary: extract keyword-anchored file paths from purpose
        from system.orchestrator.planning_compiler import (
            _extract_local_file_paths,
            _normalize_local_file_path,
        )
        purpose_paths = _extract_local_file_paths(purpose)
        if len(purpose_paths) != 1:
            return None

        # Secondary: count ALL bare filenames — if > 1, purpose is ambiguous
        if _count_valid_raw_filenames(purpose) != 1:
            return None

        purpose_path_raw = purpose_paths[0]
        purpose_path_norm = _normalize_local_file_path(purpose_path_raw)
        if not purpose_path_norm:
            return None

        executed_path_raw = _extract_quoted_path_pg(tool_call)
        if not executed_path_raw:
            return None

        executed_path_norm = _normalize_path_pg(executed_path_raw)
        if not executed_path_norm:
            return None

        if purpose_path_norm == executed_path_norm:
            return None

        return _rebuild_tool_call_with_new_path(tool_call, purpose_path_raw)
    except Exception:
        return None
