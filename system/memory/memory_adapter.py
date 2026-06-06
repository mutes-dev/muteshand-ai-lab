"""
MEMORY ADAPTER — Phase 3A (MEMORY_STORAGE_CONTRACT_V1) + ISSUE-078 Guardrails

Responsibilities:
- Read from global_memory and inject into agent context ONLY
- Provide advisory context enrichment for agent input
- NO writes (writes are handled by parallel_executor via preference_tracker)
- Enforce size bounds and advisory-only guard metadata

CONTRACT RULES (MANDATORY):
- Memory context is INJECTED into agent input only
- Memory MUST NOT influence execution_result
- Memory MUST NOT influence governance decisions
- Memory MAY provide advisory context (tool preference hints)
- Failure-isolated — adapter failures MUST NOT affect execution
- Returns safe defaults on any failure
"""

import json
from typing import Any, Dict, Optional

_MAX_MEMORY_CONTEXT_CHARS = 1000


def _truncate_memory_context(ctx: Dict[str, Any], max_chars: int = _MAX_MEMORY_CONTEXT_CHARS) -> Dict[str, Any]:
    """
    Truncate memory_context to fit within max_chars while preserving all
    safety/advisory guard fields.

    Strategy:
    - Serialize and measure.
    - If over limit, shorten 'memory_hint' first.
    - Never remove advisory guard fields.
    """
    try:
        serialized = json.dumps(ctx, ensure_ascii=False)
    except (TypeError, ValueError):
        return ctx

    if len(serialized) <= max_chars:
        return ctx

    # Clone so we don't mutate the original
    safe = dict(ctx)
    hint = safe.get("memory_hint", "")
    if isinstance(hint, str):
        overage = len(serialized) - max_chars
        # Leave a small buffer for JSON escaping overhead
        new_len = max(0, len(hint) - overage - 20)
        if new_len < len(hint):
            safe["memory_hint"] = hint[:new_len] + "... [truncated]"
            # Re-check
            try:
                if len(json.dumps(safe, ensure_ascii=False)) <= max_chars:
                    return safe
            except (TypeError, ValueError):
                pass

    # If still too large, drop memory_hint entirely but keep guards
    safe.pop("memory_hint", None)
    try:
        if len(json.dumps(safe, ensure_ascii=False)) <= max_chars:
            return safe
    except (TypeError, ValueError):
        pass

    # Ultimate fallback: return minimal guard-only context
    return {
        "advisory_only": True,
        "source": "memory",
        "memory_authority": "advisory_only",
        "must_not_override_user_instruction": True,
        "must_not_override_execution_result": True,
        "must_not_override_governance": True,
        "must_not_affect_lifecycle": True,
        "must_not_affect_retry_recovery_replay_replan": True,
        "must_not_affect_projection_truth": True,
    }


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
            "advisory_only": true,
            "source": "memory",
            "memory_authority": "advisory_only",
            "must_not_override_user_instruction": true,
            "must_not_override_execution_result": true,
            "must_not_override_governance": true,
            "must_not_affect_lifecycle": true,
            "must_not_affect_retry_recovery_replay_replan": true,
            "must_not_affect_projection_truth": true,
            "memory_hint": str,
            "memory_confidence": float,
            "memory_key": str
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

        ctx = {
            "advisory_only": True,
            "source": "memory",
            "memory_authority": "advisory_only",
            "must_not_override_user_instruction": True,
            "must_not_override_execution_result": True,
            "must_not_override_governance": True,
            "must_not_affect_lifecycle": True,
            "must_not_affect_retry_recovery_replay_replan": True,
            "must_not_affect_projection_truth": True,
            "memory_hint": hint,
            "memory_confidence": confidence,
            "memory_key": pattern_key,
        }

        return _truncate_memory_context(ctx)
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
