# tools/append_file.py
"""
Appends content to an existing file inside the MutesHand project directory.
All paths must be relative to the MutesHand root.

Contract:
- File MUST already exist. Returns file_not_found if the file does not exist.
- Do NOT silently create the file. Sequencing correctness requires the file
  to have been created by a prior write_file step.
- Content is appended exactly as provided. No auto-newline is added.
  To append a new line, include the leading newline in content, e.g. "\nsecond line".
- Does NOT overwrite or delete existing content.
- Returns {"status": "success", "result": "file appended"} on success.
"""

import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")

INPUT_SPEC = {
    "path": "string",
    "content": "string",
}


def run(path, content):
    """
    Append content to an existing file inside the MutesHand project directory.

    Args:
        path: File path (relative to project root). File must already exist.
        content: Content to append. No auto-newline is added.

    Returns:
        {"status": "success", "result": "file appended"} on success.
        {"status": "failure", "reason": "file_not_found"} if file does not exist.
        {"status": "failure", "reason": "invalid_path"} / "path_safety_blocked" for bad paths.
        {"status": "failure", "reason": "invalid_content"} if content is not a string.
        {"status": "failure", "reason": "append_error"} for unexpected I/O failures.
    """
    try:
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from system.security.path_validator import validate_path

        if not isinstance(content, str):
            return {"status": "failure", "reason": "invalid_content"}

        validation = validate_path(path, BASE_PATH)
        if validation.get("status") == "failure":
            return validation

        full_path = validation["resolved_path"]

        if not os.path.isfile(full_path):
            return {"status": "failure", "reason": "file_not_found"}

        with open(full_path, "a", encoding="utf-8") as f:
            f.write(content)

        return {"status": "success", "result": "file appended"}

    except PermissionError:
        return {"status": "failure", "reason": "permission_denied"}
    except Exception:
        return {"status": "failure", "reason": "append_error"}
