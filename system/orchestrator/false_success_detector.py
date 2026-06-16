"""
False Success Detector — PDIAG-005 Phase 1 (Advisory Only)

Pure deterministic helper for detecting observable false-success patterns
in workflow execution results. This module is WARNING-ONLY.

Architecture rules preserved:
- Does NOT change lifecycle, governance, retry, replan, execution_result
- Does NOT set purpose_met=false
- Does NOT block step or workflow completion
- Does NOT trigger retry or replan
- Does NOT change governance decisions
- Does NOT mutate lifecycle state
- Does NOT override execution_result
- Does NOT mark workflow failed/incomplete
- Does NOT introduce subjective quality scoring
- Does NOT use LLM-as-judge
"""

import re
from typing import Any, Dict, List, Optional, Set


# ── Pattern Constants ──────────────────────────────────────────────────────────

_PLACEHOLDER_PATTERNS = [
    re.compile(r"\{\{.*?\}\}"),           # {{value}}
    re.compile(r"<\s*placeholder\s*>"),   # <placeholder>
    re.compile(r"\[\s*missing\s*\]"),    # [missing]
    re.compile(r"\bTBD\b"),               # TBD
    re.compile(r"\bTODO\b"),               # TODO
    re.compile(r"\bN/A\b"),               # N/A
    re.compile(r"\b__PLACEHOLDER__\b"),   # __PLACEHOLDER__
]

_GENERIC_NON_ANSWER_PATTERNS = [
    re.compile(r"i\s+(?:cannot|can\s+not|can't|could\s+not|couldn't)\s+(?:help|answer|provide|do|process|complete|resolve)", re.IGNORECASE),
    re.compile(r"please\s+provide\s+(?:more\s+information|more\s+context|additional\s+details)", re.IGNORECASE),
    re.compile(r"insufficient\s+(?:information|data|context|details)", re.IGNORECASE),
    re.compile(r"unable\s+to\s+(?:answer|help|provide|complete|process)", re.IGNORECASE),
    re.compile(r"not\s+(?:enough|sufficient)\s+(?:information|data|context)", re.IGNORECASE),
    re.compile(r"i\s+don't\s+have\s+(?:enough|sufficient|the)\s+(?:information|data|context)", re.IGNORECASE),
    re.compile(r"(?:i'm|i\s+am)\s+(?:sorry|afraid)\s+i\s+(?:cannot|can't)", re.IGNORECASE),
    re.compile(r"no\s+(?:answer|result|data|information)\s+(?:available|found|provided)", re.IGNORECASE),
]

_COMPARISON_KEYWORDS = frozenset({
    "compare", "comparison", "versus", "vs", "difference between",
    "which is", "which one", "better", "worse", "larger", "smaller",
    "higher", "lower", "greater", "less than", "more than",
})

_SYNTHESIS_KEYWORDS = frozenset({
    "summarize", "summary", "combine", "aggregate", "synthesize", "synthesis",
    "final answer", "final output", "report", "consolidate", "merge",
    "use all previous", "create final", "write summary from",
    "compare", "recommendation",
})

_MULTIPLE_OUTPUT_KEYWORDS = frozenset({
    "both", "all", "each", "list", "multiple", "several",
    "compare both", "list both", "all results", "every",
})


# ── Helpers ──────────────────────────────────────────────────────────────────

def _normalize(text: Any) -> str:
    """Safe string normalization."""
    if text is None:
        return ""
    return str(text).strip()


def _has_placeholders(text: str) -> bool:
    """Check for unresolved placeholder patterns."""
    for pattern in _PLACEHOLDER_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _is_generic_non_answer(text: str) -> bool:
    """Check for generic non-answer patterns."""
    for pattern in _GENERIC_NON_ANSWER_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _looks_like_instruction_echo(purpose: str, result_text: str) -> bool:
    """
    Detect when output is nearly identical to the instruction/purpose,
    suggesting the tool echoed the instruction instead of producing content.
    """
    if not purpose or not result_text:
        return False
    purpose_norm = _normalize(purpose).lower()
    result_norm = _normalize(result_text).lower()

    # Exact match or very close match
    if purpose_norm == result_norm:
        return True

    # Result is a prefix/substring of purpose (common echo pattern)
    if len(result_norm) > 10 and result_norm in purpose_norm:
        return True

    # Purpose is a prefix of result (slight variation)
    if len(purpose_norm) > 10 and purpose_norm in result_norm:
        return True

    # High word overlap with same order (Jaccard-ish conservative check)
    purpose_words = set(purpose_norm.split())
    result_words = set(result_norm.split())
    if not purpose_words or not result_words:
        return False

    overlap = purpose_words & result_words
    # If >80% of result words are in purpose, it's likely an echo
    if len(result_words) >= 3 and len(overlap) / len(result_words) >= 0.85:
        return True

    return False


def _looks_like_missing_comparison(purpose: str, result_text: str) -> bool:
    """
    Detect when a comparison request returns only a scalar/raw value
    with no comparative language.
    """
    if not purpose or not result_text:
        return False
    purpose_lower = purpose.lower()

    # Check if purpose implies comparison
    is_comparison_purpose = any(kw in purpose_lower for kw in _COMPARISON_KEYWORDS)
    if not is_comparison_purpose:
        return False

    result_lower = result_text.lower()
    # Check if result contains comparative language
    comparison_indicators = {
        "than", "vs", "versus", "compared", "difference", "similar",
        "better", "worse", "larger", "smaller", "higher", "lower",
        "greater", "less", "more", "and", "both", "while", "whereas",
        "on the other hand", "in contrast", "however", "but",
    }
    has_comparative_language = any(ind in result_lower for ind in comparison_indicators)

    # Also check if result is extremely short (single number/word)
    # This is a conservative signal — we only warn if there's NO comparative language
    if not has_comparative_language:
        return True

    return False


def _looks_like_missing_synthesis_sources(
    purpose: str, result_text: str, source_outputs: List[Dict[str, Any]]
) -> bool:
    """
    Detect when a synthesis step result doesn't appear to reference
    its source dependency outputs.
    """
    if not purpose or not result_text:
        return False
    purpose_lower = purpose.lower()

    # Only check steps that look like synthesis
    is_synthesis = any(kw in purpose_lower for kw in _SYNTHESIS_KEYWORDS)
    if not is_synthesis:
        return False

    if len(source_outputs) < 2:
        # Can't be missing multiple sources if there's only one or zero
        return False

    result_lower = result_text.lower()

    # Collect source result strings to look for
    source_values: List[str] = []
    for src in source_outputs:
        er = src.get("execution_result")
        if isinstance(er, dict):
            val = er.get("result")
            if val is not None:
                source_values.append(str(val).lower())
        elif er is not None:
            source_values.append(str(er).lower())

    # If source values are too short (like "A", "B"), skip to avoid false positives
    meaningful_sources = [v for v in source_values if len(v) > 1]
    if len(meaningful_sources) < 2:
        return False

    # Check if at least some source content appears in result
    sources_found = 0
    for sv in meaningful_sources:
        # Allow partial match for longer source values
        if len(sv) > 10:
            # For longer values, check if a significant substring appears
            if sv in result_lower or sv[:20] in result_lower:
                sources_found += 1
        else:
            if sv in result_lower:
                sources_found += 1

    # If fewer than half the meaningful sources are referenced, flag it
    if sources_found < max(1, len(meaningful_sources) // 2):
        return True

    return False


def _looks_like_single_output_when_multiple_requested(
    purpose: str, result_text: str, source_outputs: List[Dict[str, Any]]
) -> bool:
    """
    Detect when a request explicitly asked for multiple outputs
    but the result only contains one.
    """
    if not purpose or not result_text:
        return False
    purpose_lower = purpose.lower()

    # Check if purpose implies multiple outputs
    implies_multiple = any(kw in purpose_lower for kw in _MULTIPLE_OUTPUT_KEYWORDS)
    if not implies_multiple:
        return False

    # Count apparent outputs in result
    # Conservative: look for list structure, numbered items, or clear separators
    result_lower = result_text.lower()
    has_list_structure = any(
        marker in result_lower
        for marker in ("\n- ", "\n* ", "\n1. ", "\n2. ", "1)", "2)", "•")
    )
    has_numbered_lines = bool(re.search(r"\n\s*\d+\W", result_text))
    has_separators = bool(re.search(r"[,;]\s+and\s+|[;|]", result_text))

    if has_list_structure or has_numbered_lines or has_separators:
        return False

    # If result is very short and no structural signals, warn
    word_count = len(result_text.split())
    if word_count < 15:
        return True

    return False


def _looks_like_artifact_is_instruction(purpose: str, result_text: str) -> bool:
    """
    Detect when artifact/file content appears to contain only the task
    instruction rather than produced content.
    """
    if not purpose or not result_text:
        return False
    purpose_lower = purpose.lower()

    # Only check generation/creation purposes
    generation_keywords = {"generate", "create", "build", "write", "produce",
                           "draft", "compose", "render", "compile"}
    is_generation = any(kw in purpose_lower for kw in generation_keywords)
    if not is_generation:
        return False

    return _looks_like_instruction_echo(purpose, result_text)


# ── Main Evaluation ────────────────────────────────────────────────────────────

def evaluate_false_success(
    workflow: Dict[str, Any],
    output_aggregation: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evaluate workflow output aggregation for observable false-success patterns.

    This function is PURE, DETERMINISTIC, and ADVISORY-ONLY.
    It returns warning metadata that does NOT affect lifecycle, governance,
    retry, replan, execution_result, or purpose_met.

    Args:
        workflow: The live workflow dict (for step metadata access)
        output_aggregation: The computed output_aggregation dict

    Returns:
        {
            "warning": bool,
            "warnings": [
                {
                    "code": str,
                    "severity": "warning",
                    "message": str,
                    "step_id": str,
                    "evidence": str,
                }
            ],
            "summary": str,
        }
    """
    warnings: List[Dict[str, Any]] = []

    step_map = {s.get("id"): s for s in (workflow.get("steps") or []) if s.get("id")}
    terminal_outputs = output_aggregation.get("terminal_success_outputs") or []
    source_outputs = output_aggregation.get("source_outputs") or []

    for entry in terminal_outputs:
        step_id = entry.get("step_id", "unknown")
        step = step_map.get(step_id, {})
        purpose = _normalize(step.get("purpose"))
        expected_outcome = _normalize(step.get("expected_outcome"))
        exec_res = entry.get("execution_result")
        result_value = None
        if isinstance(exec_res, dict):
            result_value = exec_res.get("result")
        result_text = _normalize(result_value)

        if not result_text:
            continue

        # (1) Unresolved placeholders
        if _has_placeholders(result_text):
            warnings.append({
                "code": "unresolved_placeholder",
                "severity": "warning",
                "message": f"Step {step_id} output contains unresolved placeholder(s).",
                "step_id": step_id,
                "evidence": "placeholder pattern detected in result",
            })

        # (2) Generic non-answer
        if _is_generic_non_answer(result_text):
            warnings.append({
                "code": "generic_non_answer",
                "severity": "warning",
                "message": f"Step {step_id} output appears to be a generic non-answer rather than a concrete result.",
                "step_id": step_id,
                "evidence": "generic refusal/insufficient-info pattern detected",
            })

        # (3) Instruction echo
        if _looks_like_instruction_echo(purpose, result_text):
            warnings.append({
                "code": "instruction_echo_output",
                "severity": "warning",
                "message": f"Step {step_id} output appears to echo the instruction instead of producing requested content.",
                "step_id": step_id,
                "evidence": "output closely matches step purpose text",
            })

        # (4) Missing comparison
        if _looks_like_missing_comparison(purpose, result_text):
            warnings.append({
                "code": "missing_comparison",
                "severity": "warning",
                "message": f"Step {step_id} requested a comparison but output lacks comparative language.",
                "step_id": step_id,
                "evidence": "scalar/raw value without comparative indicators",
            })

        # (5) Missing synthesis sources
        if _looks_like_missing_synthesis_sources(purpose, result_text, source_outputs):
            warnings.append({
                "code": "missing_synthesis_sources",
                "severity": "warning",
                "message": f"Step {step_id} appears to be a synthesis but does not reference expected source outputs.",
                "step_id": step_id,
                "evidence": "source dependency outputs not found in result",
            })

        # (6) Single output when multiple requested
        if _looks_like_single_output_when_multiple_requested(purpose, result_text, source_outputs):
            warnings.append({
                "code": "single_output_when_multiple_requested",
                "severity": "warning",
                "message": f"Step {step_id} requested multiple outputs but result appears to contain only one.",
                "step_id": step_id,
                "evidence": "no list structure or separators detected in short result",
            })

        # (7) Artifact contains instruction
        if _looks_like_artifact_is_instruction(purpose, result_text):
            # Only add if not already caught by instruction_echo
            already_warned = any(w["step_id"] == step_id and w["code"] == "instruction_echo_output" for w in warnings)
            if not already_warned:
                warnings.append({
                    "code": "artifact_contains_instruction",
                    "severity": "warning",
                    "message": f"Step {step_id} artifact appears to contain the task instruction instead of generated content.",
                    "step_id": step_id,
                    "evidence": "output closely matches generation instruction",
                })

    has_warning = len(warnings) > 0
    summary = (
        "possible false success detected"
        if has_warning
        else "no obvious false-success pattern detected"
    )

    return {
        "warning": has_warning,
        "warnings": warnings,
        "summary": summary,
    }


# ── Phase 2A: Narrow Governance Input ─────────────────────────────────────────

def compute_step_governance_input(
    step: Dict[str, Any],
    workflow: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Deterministic governance input for a single step.

    Returns ONLY high-confidence false-success signals that are safe
    for lifecycle/governance influence:
      - unresolved_placeholder
      - instruction_echo_output

    All other warning codes remain advisory-only (Phase 1).

    This function is PURE, DETERMINISTIC, and ABSENT-SAFE.
    It does NOT mutate step, workflow, execution_result, or lifecycle state.
    It does NOT call LLMs. It does NOT perform broad semantic scoring.

    Args:
        step: The step dict with fields: purpose, execution_result, etc.
        workflow: Optional workflow dict (unused, reserved for future scope).

    Returns:
        {
            "purpose_met": bool,
            "false_success_detected": bool,
            "governance_reason": str | None,
            "evidence": str | None,
            "severity": str | None,
            "scope": "step",
        }
    """
    try:
        purpose = _normalize(step.get("purpose"))
        exec_res = step.get("execution_result")
        result_value = None
        if isinstance(exec_res, dict):
            result_value = exec_res.get("result")
        result_text = _normalize(result_value)

        if not result_text:
            return {
                "purpose_met": True,
                "false_success_detected": False,
                "governance_reason": None,
                "evidence": None,
                "severity": None,
                "scope": "step",
            }

        # (1) unresolved_placeholder — objective regex match
        if _has_placeholders(result_text):
            return {
                "purpose_met": False,
                "false_success_detected": True,
                "governance_reason": "unresolved_placeholder",
                "evidence": "placeholder pattern detected in result",
                "severity": "lifecycle",
                "scope": "step",
            }

        # (2) instruction_echo_output — exact/near-exact text match
        if _looks_like_instruction_echo(purpose, result_text):
            return {
                "purpose_met": False,
                "false_success_detected": True,
                "governance_reason": "instruction_echo_output",
                "evidence": "output closely matches step purpose text",
                "severity": "lifecycle",
                "scope": "step",
            }

        # No approved Phase 2A signal
        return {
            "purpose_met": True,
            "false_success_detected": False,
            "governance_reason": None,
            "evidence": None,
            "severity": None,
            "scope": "step",
        }

    except Exception:
        # Fail-safe: never raise into governance
        return {
            "purpose_met": True,
            "false_success_detected": False,
            "governance_reason": None,
            "evidence": None,
            "severity": None,
            "scope": "step",
        }
