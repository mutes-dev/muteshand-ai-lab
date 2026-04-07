INPUT_SPEC = {
    "directory": "string"
}

import os

def run(directory):
    """
    List files in a directory.
    
    Returns clean list (one filename per line, sorted).
    Excludes hidden files (starting with ".").
    Returns structured dict for all cases.
    """
    # Define project root as base directory
    base_dir = os.path.abspath(os.getcwd())
    
    # Block absolute path inputs
    if os.path.isabs(directory):
        return {"status": "failure", "reason": "access_denied"}
    
    # Resolve input path relative to base_dir
    resolved_path = os.path.abspath(os.path.join(base_dir, directory))
    
    # Enforce sandbox: path must be within base_dir
    if not resolved_path.startswith(base_dir):
        return {"status": "failure", "reason": "access_denied"}
    
    try:
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