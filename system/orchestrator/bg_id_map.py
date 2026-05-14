"""
BG_ID MAP — Minimal bg_id → orchestrator_workflow_id Continuity Persistence

Per Phase 3F-XA (bg_id Continuity Persistence):
- Persists bg_id → orchestrator_workflow_id mapping to survive process restart.
- Enables the API layer to recover stream context after restart.
- Per LIFECYCLE_AND_PROJECTION_AUTHORITY_CONTRACT_V1 §RESUME RULES:
  Resume MUST reuse same projection identity (bg_id) to maintain continuity.

Architecture constraints:
- This module is PERSISTENCE ONLY — no lifecycle authority.
- NO websocket redesign.
- NO stream architecture redesign.
- The bg_id map is advisory — a missing or stale entry is non-fatal.
- Failure MUST NOT affect execution or API availability.

Storage:
- memory/bg_id_map.json
"""

import json
import os
import tempfile
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_MAP_PATH = os.path.join(_ROOT, "memory", "bg_id_map.json")


def _load_raw() -> dict:
    """Load the raw bg_id map from disk. Returns empty dict on any error."""
    try:
        if os.path.exists(_MAP_PATH):
            with open(_MAP_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_raw(mapping: dict) -> bool:
    """Atomically write the mapping dict to disk. Returns True on success."""
    try:
        dir_name = os.path.dirname(_MAP_PATH)
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, _MAP_PATH)
            return True
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False
    except Exception:
        return False


def register_bg_id(bg_id: str, orchestrator_workflow_id: str) -> bool:
    """
    Persist a bg_id → orchestrator_workflow_id mapping.

    Called when a new background execution is registered.
    Failure is non-fatal.

    Returns:
        True if persisted successfully, False otherwise.
    """
    if not bg_id or not orchestrator_workflow_id:
        return False
    try:
        mapping = _load_raw()
        mapping[bg_id] = orchestrator_workflow_id
        return _save_raw(mapping)
    except Exception:
        return False


def resolve_bg_id(bg_id: str) -> Optional[str]:
    """
    Resolve a bg_id to its orchestrator_workflow_id from persisted map.

    Returns:
        orchestrator_workflow_id string if found, None otherwise.
    """
    if not bg_id:
        return None
    try:
        mapping = _load_raw()
        return mapping.get(bg_id)
    except Exception:
        return None


def deregister_bg_id(bg_id: str) -> bool:
    """
    Remove a bg_id entry from the persisted map (called on workflow terminal).

    Returns:
        True if removed or not present, False on write failure.
    """
    if not bg_id:
        return True
    try:
        mapping = _load_raw()
        if bg_id in mapping:
            del mapping[bg_id]
            return _save_raw(mapping)
        return True
    except Exception:
        return False


def load_all() -> dict:
    """
    Return all persisted bg_id → orchestrator_workflow_id mappings.

    Used on startup to restore stream context for active workflows.

    Returns:
        dict of {bg_id: orchestrator_workflow_id}
    """
    return _load_raw()
