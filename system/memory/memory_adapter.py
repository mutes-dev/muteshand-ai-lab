"""
MEMORY ADAPTER — Phase 3A (MEMORY_STORAGE_CONTRACT_V1)

Responsibilities:
- Read from global_memory and inject into agent context ONLY
- Provide advisory context enrichment for agent input
- NO writes (writes are handled by parallel_executor via preference_tracker)

CONTRACT RULES (MANDATORY):
- Memory context is INJECTED into agent input only
- Memory MUST NOT influence execution_result
- Memory MUST NOT influence governance decisions
- Memory MAY provide advisory context (tool preference hints)
- Failure-isolated — adapter failures MUST NOT affect execution
- Returns safe defaults on any failure
"""

from typing import Any, Dict, Optional


def get_memory_context(tool_name: Optional[str], step_type: Optional[str]) -> Dict[str, Any]:
    """
    Read global memory and return advisory context for agent injection.

    Per MEMORY_STORAGE_CONTRACT_V1 READ RULES:
    - Memory MAY be used to influence approval confidence
    - Memory MAY suggest optimizations
    - Memory MUST NOT override user instructions
    - Memory MUST NOT bypass governance

    Per MEMORY_STORAGE_CONTRACT_V1 CONFIDENCE MODEL:
    - LOW (<0.4): returns empty context (no injection)
    - MEDIUM (0.4–0.7): returns weak advisory hint
    - HIGH (>0.7): returns strong advisory hint

    Args:
        tool_name: The tool expected to be used (may be None)
        step_type: The step type (may be None)

    Returns:
        Advisory context dict (may be empty). Never raises.
        {
            "memory_hint": str,          # human-readable advisory
            "memory_confidence": float,  # 0.0–1.0
            "memory_key": str            # the memory key that matched
        }
        OR empty dict {} if no relevant memory or below confidence threshold
    """
    try:
        from system.memory.global_memory import get_by_key, CONFIDENCE_LOW
        from system.memory.preference_tracker import _make_pattern_key

        if not tool_name and not step_type:
            return {}

        pattern_key = _make_pattern_key(tool_name or "", step_type or "")
        entry = get_by_key(pattern_key)

        if entry is None:
            return {}

        confidence = float(entry.get("confidence", 0.0))

        # Per MEMORY_STORAGE_CONTRACT_V1: LOW (<0.4) → ignore
        if confidence < CONFIDENCE_LOW:
            return {}

        value = entry.get("value", {})
        tool = value.get("tool", tool_name or "unknown")
        hint = f"Pattern known: tool '{tool}' has been used successfully for this type of step."

        return {
            "memory_hint": hint,
            "memory_confidence": confidence,
            "memory_key": pattern_key
        }
    except Exception:
        # Failure-isolated: adapter MUST NOT affect execution
        return {}


def enrich_agent_context(
    existing_context: Optional[Dict[str, Any]],
    tool_name: Optional[str],
    step_type: Optional[str]
) -> Dict[str, Any]:
    """
    Enrich an existing agent context dict with memory advisory data.

    This is the ONLY integration point for injecting memory into agent input.
    Returns the context dict (possibly unchanged if no memory match).

    Args:
        existing_context: Current agent context dict (e.g. {"last_result": ...})
        tool_name: Tool name for pattern lookup
        step_type: Step type for pattern lookup

    Returns:
        Enriched context dict. Never raises.
    """
    try:
        base = dict(existing_context) if isinstance(existing_context, dict) else {}
        memory_ctx = get_memory_context(tool_name, step_type)
        if memory_ctx:
            base["memory_context"] = memory_ctx
        return base
    except Exception:
        # Failure-isolated: return original context unmodified
        if isinstance(existing_context, dict):
            return dict(existing_context)
        return {}
