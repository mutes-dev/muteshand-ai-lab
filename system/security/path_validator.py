"""Path safety validation for filesystem-capable tools.

Inspired by Odysseus path confinement test patterns (MIT License).
Source reference: E:\ReferenceRepos\odysseus\tests\test_tool_path_confinement.py

This is an AI Lab-native implementation — no Odysseus runtime or tool
dispatcher code was copied.
"""

from __future__ import annotations

import os
import platform
from typing import Optional


# Sensitive directory fragments (case-insensitive substring match)
_SENSITIVE_SUBPATHS = frozenset({
    ".ssh/",
    ".gnupg/",
    "/etc/",
    "/var/log/",
    "system32/",
    "syswow64/",
    "program files/",
    "windows/",
})

# Sensitive filenames (exact match, case-insensitive)
_SENSITIVE_FILENAMES = frozenset({
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "authorized_keys",
    ".env",
    ".netrc",
    ".bashrc",
    ".zshrc",
    ".profile",
    ".bash_profile",
    ".bash_login",
})


def _is_inside_root(resolved_path: str, root: str) -> bool:
    """Check if resolved_path is inside or equal to root."""
    resolved_path = os.path.normpath(resolved_path)
    root = os.path.normpath(root)
    if not root.endswith(os.sep):
        root_prefix = root + os.sep
    else:
        root_prefix = root
    return resolved_path == root or resolved_path.startswith(root_prefix)


def validate_path(
    path: object,
    base_dir: str,
    *,
    allow_base_dir: bool = False,
) -> dict:
    """Validate a filesystem path for tool execution.

    Returns:
        {"status": "success", "resolved_path": <str>}
      OR
        {"status": "failure", "reason": "path_safety_blocked", "detail": <reason>}
    """
    # Basic input validation
    if not isinstance(path, str):
        return {"status": "failure", "reason": "path_safety_blocked", "detail": "path must be a string"}
    if not path or not path.strip():
        return {"status": "failure", "reason": "path_safety_blocked", "detail": "path is required"}

    # Strip quotes (common from LLM output)
    clean_path = path.strip().strip('"').strip("'")

    # Prevent null bytes and control chars
    if "\x00" in clean_path:
        return {"status": "failure", "reason": "path_safety_blocked", "detail": "path contains null bytes"}

    # Build absolute path relative to base_dir
    full_path = os.path.abspath(os.path.join(base_dir, clean_path))

    # Resolve symlinks (critical for symlink escape prevention)
    try:
        real_path = os.path.realpath(full_path)
    except OSError as exc:
        return {"status": "failure", "reason": "path_safety_blocked", "detail": f"cannot resolve path: {exc}"}

    # Check traversal outside base_dir
    base_dir_real = os.path.realpath(base_dir)
    if not _is_inside_root(real_path, base_dir_real):
        return {"status": "failure", "reason": "path_safety_blocked", "detail": "path outside allowed root"}

    # Block access to base_dir itself unless explicitly allowed (e.g. list_files)
    if not allow_base_dir and os.path.normpath(real_path) == os.path.normpath(base_dir_real):
        return {"status": "failure", "reason": "path_safety_blocked", "detail": "path must be inside allowed root, not the root itself"}

    # Check sensitive subpaths (case-insensitive)
    real_lower = real_path.lower().replace("\\", "/")
    for subpath in _SENSITIVE_SUBPATHS:
        if subpath in real_lower:
            return {"status": "failure", "reason": "path_safety_blocked", "detail": f"sensitive path: {subpath}"}

    # Check sensitive filenames (case-insensitive)
    basename = os.path.basename(real_path).lower()
    if basename in _SENSITIVE_FILENAMES:
        return {"status": "failure", "reason": "path_safety_blocked", "detail": f"sensitive filename: {basename}"}

    return {"status": "success", "resolved_path": real_path}
