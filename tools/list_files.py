INPUT_SPEC = {
    "directory": "string"
}

import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")

def run(directory):
    """
    List files in a directory.
    
    Returns clean list (one filename per line, sorted).
    Excludes hidden files (starting with ".").
    Returns structured dict for all cases.
    """
    try:
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from system.security.path_validator import validate_path

        validation = validate_path(directory, BASE_PATH, allow_base_dir=True)
        if validation.get("status") == "failure":
            return validation

        resolved_path = validation["resolved_path"]

        if not os.path.isdir(resolved_path):
            return {"status": "failure", "reason": "file_not_found"}
        
        # Get files, exclude hidden, sort alphabetically
        files = os.listdir(resolved_path)
        files = [f for f in files if not f.startswith(".")]
        files.sort()
        
        # Build formatted string
        if not files:
            formatted = "(empty)"
        else:
            formatted = "\n".join(files)
        
        return {"status": "success", "result": formatted}
    
    except Exception:
        return {"status": "failure", "reason": "access_denied"}