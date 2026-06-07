"""
glob tool — AI Lab-native file discovery by glob pattern.

Odysseus used as behavior/catalogue reference only.
No Odysseus runtime or tool dispatcher code was copied.
"""

import fnmatch
import os
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")

INPUT_SPEC = {
    "pattern": "string",
    "directory": "string",
    "recursive": "number",
    "max_results": "number",
}

_MAX_RESULTS_DEFAULT = 500


def run(pattern="*", directory=".", recursive=1, max_results=500):
    """
    Discover files matching a glob pattern under an allowed root.

    Args:
        pattern: Glob pattern (e.g., "*.py", "**/*.md").
        directory: Base directory to search in (relative to project root).
        recursive: 1 = recursive search, 0 = top-level only.
        max_results: Maximum number of paths to return.

    Returns:
        Structured list of matching paths or clean failure dict.
    """
    try:
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from system.security.path_validator import validate_path

        # Validate pattern
        if not isinstance(pattern, str) or not pattern:
            return {"status": "failure", "reason": "invalid_pattern", "detail": "pattern must be a non-empty string"}

        validation = validate_path(directory, BASE_PATH, allow_base_dir=True)
        if validation.get("status") == "failure":
            return validation

        base_dir = validation["resolved_path"]
        if not os.path.isdir(base_dir):
            return {"status": "failure", "reason": "directory_not_found", "detail": f"directory not found: {directory}"}

        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = _MAX_RESULTS_DEFAULT

        try:
            recursive = int(recursive)
        except (TypeError, ValueError):
            recursive = 1

        # Normalize pattern for fnmatch
        clean_pattern = pattern.strip()

        matches = []
        if recursive:
            for root, _dirs, files in os.walk(base_dir):
                for filename in files:
                    if fnmatch.fnmatch(filename, clean_pattern):
                        full = os.path.join(root, filename)
                        rel = os.path.relpath(full, BASE_PATH)
                        matches.append(rel)
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break
        else:
            try:
                entries = os.listdir(base_dir)
            except OSError:
                entries = []
            for entry in entries:
                full = os.path.join(base_dir, entry)
                if os.path.isfile(full) and fnmatch.fnmatch(entry, clean_pattern):
                    rel = os.path.relpath(full, BASE_PATH)
                    matches.append(rel)
                    if len(matches) >= max_results:
                        break

        if not matches:
            return {"status": "success", "result": {"paths": [], "count": 0, "message": "no matches found"}}

        return {
            "status": "success",
            "result": {
                "paths": matches,
                "count": len(matches),
            }
        }

    except Exception:
        return {"status": "failure", "reason": "glob_error"}
