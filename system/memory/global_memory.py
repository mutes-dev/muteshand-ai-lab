"""
GLOBAL MEMORY — Phase 3A (MEMORY_STORAGE_CONTRACT_V1)

Responsibilities:
- Persist global advisory memory entries to local JSON file
- Provide get_by_key(), write_entry(), update_confidence(), decay_entries()
- Atomic writes only (temp file → rename)

CONTRACT RULES (MANDATORY):
- Memory MUST NOT influence governance decisions
- Memory MUST NOT override execution_result
- Memory MAY influence confidence ONLY
- Memory entries are advisory knowledge only
- Local storage only — NO external transfer
- Writes ONLY from repeated patterns (enforced by preference_tracker)
- Failures MUST NOT affect execution (failure-isolated)
"""

import json
import os
import uuid
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

MEMORY_DIR = os.path.join(_ROOT, "memory")
GLOBAL_MEMORY_PATH = os.path.join(MEMORY_DIR, "global_memory.json")

# Confidence thresholds per MEMORY_STORAGE_CONTRACT_V1
CONFIDENCE_LOW = 0.4
CONFIDENCE_HIGH = 0.7

# Decay factor applied per decay_entries() call
DECAY_FACTOR = 0.05
DECAY_FLOOR = 0.1


def _ensure_memory_dir() -> None:
    """Ensure memory directory exists."""
    os.makedirs(MEMORY_DIR, exist_ok=True)


def _load_all() -> List[Dict[str, Any]]:
    """
    Load all memory entries from disk.

    Returns empty list on any error (failure-isolated).
    """
    try:
        _ensure_memory_dir()
        if not os.path.exists(GLOBAL_MEMORY_PATH):
            return []
        with open(GLOBAL_MEMORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def _save_all(entries: List[Dict[str, Any]]) -> bool:
    """
    Atomically save all memory entries to disk.

    Uses temp file → rename for atomicity.
    Returns True on success, False on failure (failure-isolated).
    """
    try:
        _ensure_memory_dir()
        tmp_fd, tmp_path = tempfile.mkstemp(dir=MEMORY_DIR, suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
            os.replace(tmp_path, GLOBAL_MEMORY_PATH)
            return True
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            return False
    except Exception:
        return False


def get_by_key(key: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a memory entry by its key.

    Returns the entry dict or None if not found.
    Failure-isolated — returns None on any error.

    Args:
        key: The memory entry identifier

    Returns:
        Memory entry dict or None
    """
    try:
        entries = _load_all()
        for entry in entries:
            if entry.get("key") == key:
                return entry
        return None
    except Exception:
        return None


def get_all_entries() -> List[Dict[str, Any]]:
    """
    Return all memory entries.

    Returns empty list on any error (failure-isolated).
    """
    try:
        return _load_all()
    except Exception:
        return []


def write_entry(
    key: str,
    value: Any,
    category: str = "pattern",
    confidence: float = 0.5
) -> Optional[Dict[str, Any]]:
    """
    Write a new memory entry or update existing.

    Per MEMORY_STORAGE_CONTRACT_V1:
    - MUST NOT be called from single-occurrence events
    - Caller (preference_tracker) is responsible for pattern threshold
    - Atomic write enforced

    Args:
        key: Unique identifier for this memory entry
        value: The stored data (pattern, preference, behavior)
        category: "behavior" | "preference" | "pattern" | "context"
        confidence: Initial confidence score (0.0–1.0)

    Returns:
        The written/updated entry dict, or None on failure
    """
    try:
        entries = _load_all()
        now = datetime.utcnow().isoformat()

        # Check for existing entry with same key
        for i, entry in enumerate(entries):
            if entry.get("key") == key:
                # Update existing entry
                entries[i]["value"] = value
                entries[i]["confidence"] = min(1.0, float(confidence))
                entries[i]["updated_at"] = now
                _save_all(entries)
                return entries[i]

        # New entry — per MEMORY_STORAGE_CONTRACT_V1 structure
        new_entry = {
            "id": str(uuid.uuid4()),
            "type": "GLOBAL",
            "category": category,
            "key": key,
            "value": value,
            "confidence": min(1.0, max(0.0, float(confidence))),
            "created_at": now,
            "updated_at": now
        }
        entries.append(new_entry)
        _save_all(entries)
        return new_entry
    except Exception:
        return None


def update_confidence(key: str, delta: float) -> Optional[Dict[str, Any]]:
    """
    Adjust confidence of an existing memory entry.

    Per MEMORY_STORAGE_CONTRACT_V1:
    - Confidence increases with consistent repetition
    - Confidence decreases with contradiction
    - updated_at MUST be refreshed

    Args:
        key: Memory entry key
        delta: Signed delta to apply (positive = reinforce, negative = contradict)

    Returns:
        Updated entry dict or None if not found / on failure
    """
    try:
        entries = _load_all()
        now = datetime.utcnow().isoformat()

        for i, entry in enumerate(entries):
            if entry.get("key") == key:
                current = float(entry.get("confidence", 0.5))
                entries[i]["confidence"] = min(1.0, max(0.0, current + delta))
                entries[i]["updated_at"] = now
                _save_all(entries)
                return entries[i]
        return None
    except Exception:
        return None


def decay_entries() -> int:
    """
    Apply confidence decay to all entries.

    Per MEMORY_STORAGE_CONTRACT_V1:
    - Stale entries lose confidence over time
    - Entries at or below DECAY_FLOOR are not reduced further
    - outdated patterns are deprioritized

    Returns:
        Number of entries decayed, or 0 on failure
    """
    try:
        entries = _load_all()
        if not entries:
            return 0

        count = 0
        now = datetime.utcnow().isoformat()

        for i, entry in enumerate(entries):
            current = float(entry.get("confidence", 0.5))
            if current > DECAY_FLOOR:
                entries[i]["confidence"] = max(DECAY_FLOOR, current - DECAY_FACTOR)
                entries[i]["updated_at"] = now
                count += 1

        if count > 0:
            _save_all(entries)
        return count
    except Exception:
        return 0


def delete_entry(key: str) -> bool:
    """
    Delete a memory entry by key.

    Per MEMORY_STORAGE_CONTRACT_V1: System MAY delete obsolete entries.

    Args:
        key: Memory entry key to delete

    Returns:
        True if deleted, False if not found or on failure
    """
    try:
        entries = _load_all()
        original_len = len(entries)
        entries = [e for e in entries if e.get("key") != key]
        if len(entries) < original_len:
            _save_all(entries)
            return True
        return False
    except Exception:
        return False


def reset_all() -> bool:
    """
    Reset all memory entries (per MEMORY_STORAGE_CONTRACT_V1 reset rule).

    Per contract: System MAY reset memory on user request.
    Returns True on success, False on failure.
    """
    try:
        return _save_all([])
    except Exception:
        return False
