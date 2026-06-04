"""
MEMORY STORE — Sprint 6 (ISSUE-076)

Responsibilities:
- Provide canonical memory storage primitives for GLOBAL and PROJECT scopes
- Local JSON persistence only, atomic writes where reasonable
- Failure-isolated: all errors absorbed, safe defaults returned

CONTRACT RULES (MANDATORY):
- Memory is advisory only
- Memory MUST NOT influence execution_result
- Memory MUST NOT override governance decisions
- Memory MUST NOT be confused with workflow persistence, projection stores, trace data, or runtime recovery
- Storage is local-first only
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from system.memory.schema import (
    build_entry,
    validate_entry,
    validate_scope,
    validate_key,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    MemoryValidationError,
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

MEMORY_DIR = os.path.join(_ROOT, "memory")
GLOBAL_STORE_PATH = os.path.join(MEMORY_DIR, "memory_store.json")
PROJECTS_DIR = os.path.join(MEMORY_DIR, "projects")


# ── Internal helpers ───────────────────────────────────────────────────────


def _ensure_dirs() -> None:
    """Ensure memory directory and projects subdirectory exist."""
    os.makedirs(MEMORY_DIR, exist_ok=True)
    os.makedirs(PROJECTS_DIR, exist_ok=True)


def _load_json(path: str) -> List[Dict[str, Any]]:
    """
    Load a JSON list from disk. Returns empty list on any error.
    Failure-isolated.
    """
    try:
        _ensure_dirs()
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def _save_json(path: str, entries: List[Dict[str, Any]]) -> bool:
    """
    Atomically save a JSON list to disk.
    Returns True on success, False on failure. Failure-isolated.
    """
    try:
        _ensure_dirs()
        tmp_fd, tmp_path = tempfile.mkstemp(dir=MEMORY_DIR, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
            os.replace(tmp_path, path)
            return True
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            return False
    except Exception:
        return False


def _project_path(project_id: str) -> str:
    """Return the storage path for a project's memory file."""
    safe_id = "".join(c for c in project_id if c.isalnum() or c in ("-", "_", "."))
    if not safe_id:
        safe_id = "unknown"
    return os.path.join(PROJECTS_DIR, f"{safe_id}.json")


def _load_scope(scope: str, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load entries for a given scope."""
    scope = validate_scope(scope)
    if scope == SCOPE_GLOBAL:
        return _load_json(GLOBAL_STORE_PATH)
    else:
        if not project_id:
            return []
        return _load_json(_project_path(project_id))


def _save_scope(scope: str, entries: List[Dict[str, Any]], project_id: Optional[str] = None) -> bool:
    """Save entries for a given scope."""
    scope = validate_scope(scope)
    if scope == SCOPE_GLOBAL:
        return _save_json(GLOBAL_STORE_PATH, entries)
    else:
        if not project_id:
            return False
        return _save_json(_project_path(project_id), entries)


# ── Public primitives ────────────────────────────────────────────────────────


def list_entries(
    scope: Optional[str] = None,
    project_id: Optional[str] = None,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List memory entries with optional filtering.

    Args:
        scope: "GLOBAL", "PROJECT", or None for all
        project_id: Required when scope="PROJECT", optional when scope=None
        category: Optional category filter

    Returns:
        List of validated memory entry dicts. Empty list on error.
    """
    try:
        results: List[Dict[str, Any]] = []

        if scope is None or validate_scope(scope) == SCOPE_GLOBAL:
            for entry in _load_json(GLOBAL_STORE_PATH):
                try:
                    entry = validate_entry(entry)
                    if category is None or entry["category"] == category:
                        results.append(entry)
                except MemoryValidationError:
                    continue

        if scope is None or validate_scope(scope) == SCOPE_PROJECT:
            if project_id:
                for entry in _load_json(_project_path(project_id)):
                    try:
                        entry = validate_entry(entry)
                        if category is None or entry["category"] == category:
                            results.append(entry)
                    except MemoryValidationError:
                        continue
            elif scope is None:
                # List all project memory files
                _ensure_dirs()
                for fname in os.listdir(PROJECTS_DIR):
                    if not fname.endswith(".json"):
                        continue
                    pid = fname[:-5]
                    for entry in _load_json(os.path.join(PROJECTS_DIR, fname)):
                        try:
                            entry = validate_entry(entry)
                            if category is None or entry["category"] == category:
                                results.append(entry)
                        except MemoryValidationError:
                            continue

        return results
    except Exception:
        return []


def read(scope: str, key: str, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Read a single memory entry by scope and key.

    Args:
        scope: "GLOBAL" or "PROJECT"
        key: Entry key
        project_id: Required when scope="PROJECT"

    Returns:
        Validated entry dict or None if not found / on error.
    """
    try:
        scope = validate_scope(scope)
        key = validate_key(key)
        entries = _load_scope(scope, project_id)
        for entry in entries:
            if entry.get("key") == key:
                try:
                    return validate_entry(entry)
                except MemoryValidationError:
                    return None
        return None
    except Exception:
        return None


def write(
    scope: str,
    key: str,
    value: Any,
    category: str,
    project_id: Optional[str] = None,
    source: str = "user",
    confidence: float = 0.5,
    editable: bool = True,
    deletable: bool = True,
) -> Optional[Dict[str, Any]]:
    """
    Write a new memory entry. Replaces existing entry with same scope+key.

    Args:
        scope: "GLOBAL" or "PROJECT"
        key: Unique key for this entry within scope
        value: Stored data (any JSON-serializable)
        category: "behavior" | "preference" | "pattern" | "context"
        project_id: Required when scope="PROJECT"
        source: "user" | "system" | "agent" | "inferred"
        confidence: 0.0–1.0
        editable: bool
        deletable: bool

    Returns:
        Written entry dict or None on failure.
    """
    try:
        entry = build_entry(
            scope=scope,
            key=key,
            value=value,
            category=category,
            project_id=project_id,
            source=source,
            confidence=confidence,
            editable=editable,
            deletable=deletable,
        )

        scope = entry["scope"]
        entries = _load_scope(scope, project_id)

        # Replace existing entry with same key
        entries = [e for e in entries if e.get("key") != entry["key"]]
        entries.append(entry)

        if _save_scope(scope, entries, project_id):
            return entry
        return None
    except Exception:
        return None


def update(scope: str, key: str, value: Any, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Update the value and updated_at of an existing memory entry.

    Args:
        scope: "GLOBAL" or "PROJECT"
        key: Entry key
        value: New value
        project_id: Required when scope="PROJECT"

    Returns:
        Updated entry dict or None if not found / not editable / on error.
    """
    try:
        scope = validate_scope(scope)
        key = validate_key(key)
        entries = _load_scope(scope, project_id)

        for i, entry in enumerate(entries):
            if entry.get("key") == key:
                try:
                    validated = validate_entry(entry)
                except MemoryValidationError:
                    return None
                if not validated.get("editable", True):
                    return None
                entries[i]["value"] = value
                entries[i]["updated_at"] = datetime.now(timezone.utc).isoformat()
                if _save_scope(scope, entries, project_id):
                    return validate_entry(entries[i])
                return None
        return None
    except Exception:
        return None


def delete(scope: str, key: str, project_id: Optional[str] = None) -> bool:
    """
    Delete a memory entry if it is deletable.

    Args:
        scope: "GLOBAL" or "PROJECT"
        key: Entry key
        project_id: Required when scope="PROJECT"

    Returns:
        True if deleted, False if not found / not deletable / on error.
    """
    try:
        scope = validate_scope(scope)
        key = validate_key(key)
        entries = _load_scope(scope, project_id)

        target = None
        for entry in entries:
            if entry.get("key") == key:
                target = entry
                break

        if target is None:
            return False

        try:
            validated = validate_entry(target)
        except MemoryValidationError:
            return False

        if not validated.get("deletable", True):
            return False

        entries = [e for e in entries if e.get("key") != key]
        return _save_scope(scope, entries, project_id)
    except Exception:
        return False


def reset(scope: str, project_id: Optional[str] = None) -> bool:
    """
    Reset memory entries for a given scope.

    Args:
        scope: "GLOBAL" | "PROJECT" | "all"
        project_id: Required when scope="PROJECT"

    Returns:
        True on success, False on failure.
    """
    try:
        s = str(scope).strip().upper()
        if s == "ALL":
            ok_global = _save_json(GLOBAL_STORE_PATH, [])
            ok_projects = True
            _ensure_dirs()
            for fname in os.listdir(PROJECTS_DIR):
                if fname.endswith(".json"):
                    try:
                        os.remove(os.path.join(PROJECTS_DIR, fname))
                    except Exception:
                        ok_projects = False
            return ok_global and ok_projects

        scope = validate_scope(scope)
        if scope == SCOPE_GLOBAL:
            return _save_json(GLOBAL_STORE_PATH, [])
        else:
            if not project_id:
                return False
            return _save_json(_project_path(project_id), [])
    except Exception:
        return False
