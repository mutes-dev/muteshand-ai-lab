"""
edit_file tool — AI Lab-native exact-string file replacement.

Odysseus used as behavior/catalogue reference only.
No Odysseus runtime or tool dispatcher code was copied.

Safer alternative to full write_file overwrite:
- exact-string replacement (not positional)
- dry_run preview
- ambiguous match rejection when replace_all=false
"""

import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")

INPUT_SPEC = {
    "path": "string",
    "old_text": "string",
    "new_text": "string",
    "replace_all": "number",
    "dry_run": "number",
}


def _is_binary(filepath: str, sample_size: int = 1024) -> bool:
    """Heuristic: check if file appears binary by null byte presence."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(sample_size)
            if b"\x00" in chunk:
                return True
    except Exception:
        return True
    return False


def run(path, old_text, new_text, replace_all=0, dry_run=0):
    """
    Replace exact string occurrences in a file.

    Args:
        path: File path (relative to project root).
        old_text: Exact text to replace.
        new_text: Replacement text.
        replace_all: 1 = replace all occurrences, 0 = replace first only (default 0).
        dry_run: 1 = preview only, do not write (default 0).

    Returns:
        dict with status, replacements count, preview.
    """
    try:
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from system.security.path_validator import validate_path

        # Input validation
        if not isinstance(path, str) or not path:
            return {"status": "failure", "reason": "invalid_path", "detail": "path must be a non-empty string"}

        if not isinstance(old_text, str):
            return {"status": "failure", "reason": "invalid_old_text", "detail": "old_text must be a string"}

        if not old_text:
            return {"status": "failure", "reason": "empty_old_text", "detail": "old_text cannot be empty"}

        validation = validate_path(path, BASE_PATH)
        if validation.get("status") == "failure":
            return validation

        full_path = validation["resolved_path"]

        if not os.path.isfile(full_path):
            return {"status": "failure", "reason": "file_not_found", "detail": f"file not found: {path}"}

        # Reject binary files
        if _is_binary(full_path):
            return {"status": "failure", "reason": "binary_file", "detail": "editing binary files is not supported"}

        # Read file content
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            return {"status": "failure", "reason": "read_error", "detail": "unable to read file"}

        # Count occurrences
        count = content.count(old_text)

        if count == 0:
            return {"status": "failure", "reason": "old_text_not_found", "detail": "old_text not found in file"}

        try:
            replace_all = int(replace_all)
        except (TypeError, ValueError):
            replace_all = 0

        try:
            dry_run = int(dry_run)
        except (TypeError, ValueError):
            dry_run = 0

        # Ambiguous match check when replace_all=false
        if count > 1 and not replace_all:
            return {
                "status": "failure",
                "reason": "ambiguous_match",
                "detail": f"found {count} occurrences of old_text; set replace_all=1 to replace all, or use a more specific old_text",
            }

        # Perform replacement
        if replace_all:
            new_content = content.replace(old_text, new_text)
            replacements = count
        else:
            new_content = content.replace(old_text, new_text, 1)
            replacements = 1

        # Build preview (first changed line context)
        preview = _build_preview(content, new_content)

        if dry_run:
            return {
                "status": "success",
                "result": {
                    "dry_run": True,
                    "replacements": replacements,
                    "preview": preview,
                    "path": path,
                    "message": f"dry run: would replace {replacements} occurrence(s)",
                }
            }

        # Write modified content
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except (OSError, PermissionError):
            return {"status": "failure", "reason": "write_error", "detail": "unable to write file"}

        return {
            "status": "success",
            "result": {
                "replacements": replacements,
                "preview": preview,
                "path": path,
                "message": f"replaced {replacements} occurrence(s)",
            }
        }

    except Exception:
        return {"status": "failure", "reason": "edit_error"}


def _build_preview(old_content: str, new_content: str) -> str:
    """Build a short preview showing the first changed line."""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    for i in range(min(len(old_lines), len(new_lines))):
        if old_lines[i] != new_lines[i]:
            return new_lines[i][:200]
    # If line counts differ, show first new line
    if len(new_lines) > len(old_lines):
        return new_lines[len(old_lines)][:200] if len(new_lines) > len(old_lines) else ""
    return "(no visible change)"
