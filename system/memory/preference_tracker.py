"""
PREFERENCE TRACKER — Phase 3A (MEMORY_STORAGE_CONTRACT_V1)

Responsibilities:
- Track repeated execution patterns
- Enforce write threshold (reject single-occurrence events)
- Trigger write_entry() ONLY when pattern meets threshold
- NO governance access, NO execution influence

CONTRACT RULES (MANDATORY):
- Memory MUST NOT be written from single occurrence
- Memory MUST NOT be written from failed executions
- Memory MUST NOT be written from uncertain/low-confidence events
- Pattern threshold MUST be satisfied before any write
- Failure-isolated — tracker failures MUST NOT affect execution
"""

from typing import Any, Dict, Optional

# Minimum repetitions before writing to global memory
# Per MEMORY_STORAGE_CONTRACT_V1: "repeated patterns detected"
WRITE_THRESHOLD = 3

# Initial confidence for newly written pattern entries
INITIAL_CONFIDENCE = 0.5

# Confidence increment per additional repetition above threshold
CONFIDENCE_INCREMENT = 0.1

# In-memory occurrence counter (per-runtime, not persisted)
# Key: pattern_key -> occurrence count
_occurrence_counts: Dict[str, int] = {}


def _make_pattern_key(tool_name: str, step_type: str) -> str:
    """
    Derive a stable pattern key from tool name and step type.

    Args:
        tool_name: The tool used in the step
        step_type: The step type (e.g. EXECUTE_API, ANALYZE)

    Returns:
        String key for pattern identification
    """
    t = (tool_name or "unknown").strip().lower()
    s = (step_type or "unknown").strip().lower()
    return f"tool:{t}|type:{s}"


def observe_execution(
    tool_name: str,
    step_type: str,
    execution_result: Dict[str, Any],
    step_purpose: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Observe a completed step execution and potentially write to global memory.

    Per MEMORY_STORAGE_CONTRACT_V1:
    - Only writes on repeated patterns (>= WRITE_THRESHOLD)
    - Only writes on successful executions
    - Never writes on failure or retry

    Args:
        tool_name: The tool used (e.g. "add", "multiply")
        step_type: The step type (e.g. "EXECUTE_API")
        execution_result: The execution_result dict (must be success)
        step_purpose: Optional purpose string for context

    Returns:
        Written memory entry dict if threshold met and written, else None
        Failure-isolated — returns None on any error
    """
    try:
        # Per contract: MUST NOT write from failed executions
        if not isinstance(execution_result, dict):
            return None
        if execution_result.get("status") != "success":
            return None

        pattern_key = _make_pattern_key(tool_name, step_type)

        # Increment occurrence count
        current_count = _occurrence_counts.get(pattern_key, 0) + 1
        _occurrence_counts[pattern_key] = current_count

        # Per contract: MUST NOT write from single occurrence
        if current_count < WRITE_THRESHOLD:
            return None

        # Threshold met — write or update pattern in global memory
        from system.memory.global_memory import write_entry, update_confidence, get_by_key

        existing = get_by_key(pattern_key)

        if existing is None:
            # First time crossing threshold — create entry
            confidence = INITIAL_CONFIDENCE
            value = {
                "tool": tool_name,
                "step_type": step_type,
                "occurrences": current_count,
                "purpose_hint": step_purpose or ""
            }
            return write_entry(
                key=pattern_key,
                value=value,
                category="pattern",
                confidence=confidence
            )
        else:
            # Pattern already known — reinforce confidence
            updated = update_confidence(pattern_key, CONFIDENCE_INCREMENT)
            # Update occurrence count in stored value
            if updated and isinstance(updated.get("value"), dict):
                updated["value"]["occurrences"] = current_count
                # Re-write to persist updated occurrence count
                write_entry(
                    key=pattern_key,
                    value=updated["value"],
                    category=existing.get("category", "pattern"),
                    confidence=updated.get("confidence", INITIAL_CONFIDENCE)
                )
            return updated

    except Exception:
        # Failure-isolated: tracker failures MUST NOT affect execution
        return None


def get_occurrence_count(tool_name: str, step_type: str) -> int:
    """
    Return current in-memory occurrence count for a pattern.

    Args:
        tool_name: Tool name
        step_type: Step type

    Returns:
        Current count (0 if never observed)
    """
    try:
        key = _make_pattern_key(tool_name, step_type)
        return _occurrence_counts.get(key, 0)
    except Exception:
        return 0


def reset_counts() -> None:
    """
    Reset all in-memory occurrence counters.

    Used for testing only — does not affect persisted memory.
    """
    global _occurrence_counts
    _occurrence_counts = {}
