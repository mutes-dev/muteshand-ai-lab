INPUT_SPEC = {
    "path": "string"
}

import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")

def run(path):
    """
    Read file content exactly as-is.
    
    Returns full content with newlines preserved.
    Returns structured dict for all cases.
    """
    try:
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from system.security.path_validator import validate_path

        validation = validate_path(path, BASE_PATH)
        if validation.get("status") == "failure":
            return validation

        full_path = validation["resolved_path"]

        # Check if file exists
        if not os.path.exists(full_path):
            return {"status": "failure", "reason": "file_not_found"}
        
        # Read and return full content
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
            return {"status": "success", "result": content}
    
    except Exception:
        return {"status": "failure", "reason": "read_error"}