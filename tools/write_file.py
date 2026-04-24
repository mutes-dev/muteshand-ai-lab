# tools/write_file.py
"""
Writes content to a file inside the MutesHand project directory.
All paths must be relative to the MutesHand root.
"""

import os
from pathlib import Path
from core.config import BASE_PATH

INPUT_SPEC = {
    "path": "string",
    "content": "string"
}

def run(path, content):
    """
    Write content to a file inside the MutesHand project directory.
    
    Supports multi-line content with \n characters.
    Uses overwrite mode ("w") - each write replaces entire file.
    """
    try:
        # Clean path quotes
        relative_path = path.replace('"', '').replace("'", "")
        
        # Validate content is string
        if not isinstance(content, str):
            return {"status": "failure", "reason": "invalid_content"}
        
        # Build full path
        full_path = (BASE_PATH / relative_path).resolve()
        
        # Prevent escaping project directory
        if not full_path.startswith(BASE_PATH.resolve()):
            return {"status": "failure", "reason": "access_denied"}
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Write content exactly as provided (supports multi-line)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        return {"status": "success", "result": "file written"}
    
    except PermissionError:
        return {"status": "failure", "reason": "permission_denied"}
    except Exception:
        return {"status": "failure", "reason": "write_error"}