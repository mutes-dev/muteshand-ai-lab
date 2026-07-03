# tools/write_file.py
"""
Writes content to a file inside the MutesHand project directory.
All paths must be relative to the MutesHand root.
"""

import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")

INPUT_SPEC = {
    "path": "string",
    "content": "string"
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


def run(path, content):
    """
    Write content to a file inside the MutesHand project directory.
    
    Supports multi-line content with \n characters.
    Uses overwrite mode ("w") - each write replaces entire file.
    """
    try:
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from system.security.path_validator import validate_path

        # Validate content is string
        if not isinstance(content, str):
            return {"status": "failure", "reason": "invalid_content"}

        validation = validate_path(path, BASE_PATH)
        if validation.get("status") == "failure":
            return validation

        full_path = validation["resolved_path"]

        # Reject overwriting existing binary files
        if os.path.isfile(full_path) and _is_binary(full_path):
            return {"status": "failure", "reason": "binary_file", "detail": "writing binary files is not supported"}

        # Ensure directory exists
        dir_path = os.path.dirname(full_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        
        # Write content exactly as provided (supports multi-line)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        return {"status": "success", "result": "file written"}
    
    except PermissionError:
        return {"status": "failure", "reason": "permission_denied"}
    except Exception:
        return {"status": "failure", "reason": "write_error"}