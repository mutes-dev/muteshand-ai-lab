INPUT_SPEC = {
    "directory": "string"
}

import os
import importlib

def run(directory):
    # Define project root as base directory
    base_dir = os.getcwd()
    
    # Block absolute path inputs
    if os.path.isabs(directory):
        return {"status": "failure", "reason": "access_denied"}
    
    # Resolve input path relative to base_dir
    resolved_path = os.path.abspath(os.path.join(base_dir, directory))
    
    # Enforce sandbox: path must be within base_dir (secure containment check)
    if os.path.commonpath([base_dir, resolved_path]) != base_dir:
        return {"status": "failure", "reason": "access_denied"}
    
    try:
        if not os.path.isdir(resolved_path):
            return {"status": "failure", "reason": "file_not_found"}

        files = os.listdir(resolved_path)
        return {"status": "success", "result": files}

    except Exception:
        return {"status": "failure", "reason": "access_denied"}