INPUT_SPEC = {
    "path": "string"
}

import os
from core.config import BASE_PATH
from pathlib import Path

def run(path):
    """
    Read file content exactly as-is.

    Returns full content with newlines preserved.
    Returns structured dict for all cases.
    """
    try:
        full_path = (BASE_PATH / path).resolve()

        # Prevent escaping project directory
        if not full_path.startswith(BASE_PATH.resolve()):
            return {"status": "failure", "reason": "access_denied"}

        # Check if file exists
        if not full_path.exists():
            return {"status": "failure", "reason": "file_not_found"}

        # Read and return full content
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
            return {"status": "success", "result": content}
    
    except Exception:
        return {"status": "failure", "reason": "read_error"}