"""
MEMORY SCHEMA — Sprint 6 (ISSUE-076, ISSUE-078)

Responsibilities:
- Define canonical memory entry schema
- Validate memory entries before write/read
- Enforce scope, category, and metadata constraints
- Enforce value content safety (prompt-injection rejection, size bounds)

CONTRACT RULES (MANDATORY):
- Memory is advisory only
- Memory MUST NOT influence execution_result
- Memory MUST NOT override governance decisions
- Schema validation MUST reject invalid entries
- Value content MUST NOT contain prompt-injection markers or authority-impersonating strings
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union


# ── Safe Value Limits ─────────────────────────────────────────────────────

MEMORY_VALUE_MAX_CHARS = 2000

_PROMPT_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "system:",
    "assistant:",
    "developer:",
    "you are now",
    "override governance",
    "bypass governance",
    "bypass system_entry",
    "execution_result",
    "failed_recoverable",
    "retry_eligible",
)

# ── Valid Values ────────────────────────────────────────────────────────────

SCOPE_GLOBAL = "GLOBAL"
SCOPE_PROJECT = "PROJECT"
VALID_SCOPES = frozenset({SCOPE_GLOBAL, SCOPE_PROJECT})

CATEGORY_BEHAVIOR = "behavior"
CATEGORY_PREFERENCE = "preference"
CATEGORY_PATTERN = "pattern"
CATEGORY_CONTEXT = "context"
VALID_CATEGORIES = frozenset({
    CATEGORY_BEHAVIOR,
    CATEGORY_PREFERENCE,
    CATEGORY_PATTERN,
    CATEGORY_CONTEXT,
})

SOURCE_USER = "user"
SOURCE_SYSTEM = "system"
SOURCE_AGENT = "agent"
SOURCE_INFERRED = "inferred"
VALID_SOURCES = frozenset({
    SOURCE_USER,
    SOURCE_SYSTEM,
    SOURCE_AGENT,
    SOURCE_INFERRED,
})

# ── Validation ───────────────────────────────────────────────────────────────


class MemoryValidationError(ValueError):
    """Raised when a memory entry fails schema validation."""
    pass


def validate_scope(scope: Any) -> str:
    """Validate and normalize scope. Returns uppercase string."""
    if not isinstance(scope, str):
        raise MemoryValidationError(f"scope must be str, got {type(scope).__name__}")
    s = scope.strip().upper()
    if s not in VALID_SCOPES:
        raise MemoryValidationError(f"invalid scope: {scope!r}, must be one of {sorted(VALID_SCOPES)}")
    return s


def validate_category(category: Any) -> str:
    """Validate and normalize category. Returns lowercase string."""
    if not isinstance(category, str):
        raise MemoryValidationError(f"category must be str, got {type(category).__name__}")
    c = category.strip().lower()
    if c not in VALID_CATEGORIES:
        raise MemoryValidationError(f"invalid category: {category!r}, must be one of {sorted(VALID_CATEGORIES)}")
    return c


def validate_confidence(confidence: Any) -> float:
    """Validate confidence is a float in [0.0, 1.0]."""
    try:
        cf = float(confidence)
    except (TypeError, ValueError):
        raise MemoryValidationError(f"confidence must be numeric, got {type(confidence).__name__}")
    if not 0.0 <= cf <= 1.0:
        raise MemoryValidationError(f"confidence must be in [0.0, 1.0], got {cf}")
    return cf


def validate_key(key: Any) -> str:
    """Validate key is a non-empty string."""
    if not isinstance(key, str):
        raise MemoryValidationError(f"key must be str, got {type(key).__name__}")
    k = key.strip()
    if not k:
        raise MemoryValidationError("key must be non-empty")
    return k


def validate_id(entry_id: Any) -> str:
    """Validate id is a non-empty string."""
    if not isinstance(entry_id, str):
        raise MemoryValidationError(f"id must be str, got {type(entry_id).__name__}")
    eid = entry_id.strip()
    if not eid:
        raise MemoryValidationError("id must be non-empty")
    return eid


def validate_project_id(project_id: Any, required: bool = False) -> Optional[str]:
    """Validate project_id. Required when scope is PROJECT."""
    if project_id is None:
        if required:
            raise MemoryValidationError("project_id is required for PROJECT scope")
        return None
    if not isinstance(project_id, str):
        raise MemoryValidationError(f"project_id must be str or None, got {type(project_id).__name__}")
    pid = project_id.strip()
    if not pid:
        raise MemoryValidationError("project_id must be non-empty when provided")
    return pid


def validate_source(source: Any) -> str:
    """Validate source value."""
    if not isinstance(source, str):
        raise MemoryValidationError(f"source must be str, got {type(source).__name__}")
    s = source.strip().lower()
    if s not in VALID_SOURCES:
        raise MemoryValidationError(f"invalid source: {source!r}, must be one of {sorted(VALID_SOURCES)}")
    return s


def validate_boolean(field_name: str, value: Any) -> bool:
    """Validate a boolean field."""
    if not isinstance(value, bool):
        raise MemoryValidationError(f"{field_name} must be bool, got {type(value).__name__}")
    return value


def _check_value_safety(value: Any) -> None:
    """
    Reject dangerous content in memory values.

    Rules:
    - String values over MEMORY_VALUE_MAX_CHARS are rejected.
    - String values containing prompt-injection markers are rejected.
    - Dict/list values are shallow-checked for dangerous string members.
    """
    if isinstance(value, str):
        if len(value) > MEMORY_VALUE_MAX_CHARS:
            raise MemoryValidationError(
                f"value string exceeds {MEMORY_VALUE_MAX_CHARS} characters ({len(value)})"
            )
        lowered = value.lower()
        for pattern in _PROMPT_INJECTION_PATTERNS:
            if pattern in lowered:
                raise MemoryValidationError(
                    f"value contains forbidden pattern: {pattern!r}"
                )
        return

    if isinstance(value, dict):
        for v in value.values():
            if isinstance(v, str):
                if len(v) > MEMORY_VALUE_MAX_CHARS:
                    raise MemoryValidationError(
                        f"nested value string exceeds {MEMORY_VALUE_MAX_CHARS} characters"
                    )
                lowered = v.lower()
                for pattern in _PROMPT_INJECTION_PATTERNS:
                    if pattern in lowered:
                        raise MemoryValidationError(
                            f"nested value contains forbidden pattern: {pattern!r}"
                        )
        return

    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                if len(item) > MEMORY_VALUE_MAX_CHARS:
                    raise MemoryValidationError(
                        f"list item string exceeds {MEMORY_VALUE_MAX_CHARS} characters"
                    )
                lowered = item.lower()
                for pattern in _PROMPT_INJECTION_PATTERNS:
                    if pattern in lowered:
                        raise MemoryValidationError(
                            f"list item contains forbidden pattern: {pattern!r}"
                        )
        return


def validate_value(value: Any) -> Any:
    """Validate memory value content for safety."""
    _check_value_safety(value)
    return value


def validate_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate a complete memory entry dict.

    Returns a normalized copy of the entry.
    Raises MemoryValidationError on any violation.
    """
    if not isinstance(entry, dict):
        raise MemoryValidationError(f"entry must be dict, got {type(entry).__name__}")

    # Required fields
    for field in ("id", "scope", "category", "key", "value", "confidence", "source", "created_at", "updated_at", "editable", "deletable"):
        if field not in entry:
            raise MemoryValidationError(f"missing required field: {field}")

    scope = validate_scope(entry["scope"])
    project_id = validate_project_id(entry.get("project_id"), required=(scope == SCOPE_PROJECT))
    if scope == SCOPE_GLOBAL and project_id is not None:
        raise MemoryValidationError("project_id must be None for GLOBAL scope")

    normalized = {
        "id": validate_id(entry["id"]),
        "scope": scope,
        "project_id": project_id,
        "category": validate_category(entry["category"]),
        "key": validate_key(entry["key"]),
        "value": validate_value(entry["value"]),
        "confidence": validate_confidence(entry["confidence"]),
        "source": validate_source(entry["source"]),
        "created_at": str(entry["created_at"]),
        "updated_at": str(entry["updated_at"]),
        "editable": validate_boolean("editable", entry["editable"]),
        "deletable": validate_boolean("deletable", entry["deletable"]),
    }

    return normalized


def build_entry(
    scope: str,
    key: str,
    value: Any,
    category: str,
    project_id: Optional[str] = None,
    source: str = SOURCE_USER,
    confidence: float = 0.5,
    editable: bool = True,
    deletable: bool = True,
    entry_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a validated memory entry dict.

    Args:
        scope: "GLOBAL" or "PROJECT"
        key: Unique identifier for this memory entry
        value: The stored data (any JSON-serializable value)
        category: "behavior" | "preference" | "pattern" | "context"
        project_id: Required when scope is "PROJECT"
        source: "user" | "system" | "agent" | "inferred"
        confidence: 0.0–1.0
        editable: Whether the entry can be edited
        deletable: Whether the entry can be deleted
        entry_id: Optional explicit id (generated if not provided)

    Returns:
        Validated memory entry dict

    Raises:
        MemoryValidationError on any schema violation
    """
    scope = validate_scope(scope)
    category = validate_category(category)
    key = validate_key(key)
    confidence = validate_confidence(confidence)
    source = validate_source(source)
    project_id = validate_project_id(project_id, required=(scope == SCOPE_PROJECT))
    if scope == SCOPE_GLOBAL and project_id is not None:
        raise MemoryValidationError("project_id must be None for GLOBAL scope")

    now = datetime.now(timezone.utc).isoformat()

    # Validate value content before embedding
    validate_value(value)

    entry = {
        "id": entry_id if entry_id else str(uuid.uuid4()),
        "scope": scope,
        "project_id": project_id,
        "category": category,
        "key": key,
        "value": value,
        "confidence": confidence,
        "source": source,
        "created_at": now,
        "updated_at": now,
        "editable": bool(editable),
        "deletable": bool(deletable),
    }

    # Final validation to ensure id is valid
    entry["id"] = validate_id(entry["id"])
    return entry
