"""
grep tool — AI Lab-native regex search across files.

Odysseus used as behavior/catalogue reference only.
No Odysseus runtime or tool dispatcher code was copied.
"""

import os
import re
import sys

BASE_PATH = os.path.abspath("E:/MutesHand")

INPUT_SPEC = {
    "pattern": "string",
    "directory": "string",
    "recursive": "number",
    "max_results": "number",
    "case_sensitive": "number",
}

_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB per file
_MAX_RESULTS_DEFAULT = 100


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


def run(pattern, directory=".", recursive=1, max_results=100, case_sensitive=1):
    """
    Search for a regex pattern inside files under an allowed root.

    Args:
        pattern: Regex pattern to search for.
        directory: Base directory to search in (relative to project root).
        recursive: 1 = recursive, 0 = non-recursive.
        max_results: Maximum number of matches to return.
        case_sensitive: 1 = case-sensitive, 0 = case-insensitive.

    Returns:
        Structured matches or clean failure dict.
    """
    try:
        _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from system.security.path_validator import validate_path

        # Validate inputs
        if not isinstance(pattern, str) or not pattern:
            return {"status": "failure", "reason": "invalid_pattern", "detail": "pattern must be a non-empty string"}

        validation = validate_path(directory, BASE_PATH, allow_base_dir=True)
        if validation.get("status") == "failure":
            return validation

        base_dir = validation["resolved_path"]
        if not os.path.isdir(base_dir):
            return {"status": "failure", "reason": "directory_not_found", "detail": f"directory not found: {directory}"}

        try:
            flags = 0 if int(case_sensitive) else re.IGNORECASE
        except (TypeError, ValueError):
            flags = 0

        try:
            max_results = int(max_results)
        except (TypeError, ValueError):
            max_results = _MAX_RESULTS_DEFAULT

        try:
            recursive = int(recursive)
        except (TypeError, ValueError):
            recursive = 1

        try:
            compiled = re.compile(pattern, flags)
        except re.error as exc:
            return {"status": "failure", "reason": "invalid_regex", "detail": f"invalid regex pattern: {exc}"}
        matches = []
        result_count = 0

        if recursive:
            walk_iter = os.walk(base_dir)
        else:
            # Only the top-level directory
            try:
                entries = os.listdir(base_dir)
            except OSError:
                entries = []
            files = [os.path.join(base_dir, e) for e in entries if os.path.isfile(os.path.join(base_dir, e))]
            walk_iter = [(base_dir, [], [os.path.basename(f) for f in files])]

        for root, _dirs, files in walk_iter:
            for filename in files:
                if result_count >= max_results:
                    break

                filepath = os.path.join(root, filename)

                # Skip binary files
                if _is_binary(filepath):
                    continue

                # Skip huge files
                try:
                    size = os.path.getsize(filepath)
                    if size > _MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue

                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        for line_no, line in enumerate(f, start=1):
                            if result_count >= max_results:
                                break
                            if compiled.search(line):
                                rel_path = os.path.relpath(filepath, BASE_PATH)
                                matches.append({
                                    "file": rel_path,
                                    "line": line_no,
                                    "text": line.rstrip("\n\r"),
                                })
                                result_count += 1
                except (OSError, UnicodeDecodeError):
                    continue

            if result_count >= max_results:
                break

        if not matches:
            return {"status": "success", "result": {"matches": [], "count": 0, "message": "no matches found"}}

        return {
            "status": "success",
            "result": {
                "matches": matches,
                "count": len(matches),
            }
        }

    except Exception:
        return {"status": "failure", "reason": "grep_error"}
