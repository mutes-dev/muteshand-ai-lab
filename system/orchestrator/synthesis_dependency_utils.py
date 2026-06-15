"""
Shared synthesis dependency detection helpers.

Used by:
  - workflow_validator.py (ISSUE-PDIAG-002A fail-safe validation)
  - planning_compiler.py (ISSUE-PDIAG-002B deterministic pre-runtime repair)

These functions perform narrow, deterministic keyword-based detection of
final/all-prior/multi-source synthesis steps per PLANNING_COMPILER_CONTRACT_V1 §10.

They do NOT perform broad semantic inference or natural-language parsing.
"""

import re

# === FINAL SYNTHESIS DETECTION (ISSUE-PDIAG-002A/002B) ===
# Bounded keyword list per PLANNING_COMPILER_CONTRACT_V1 §10.
# Conservative: avoids false positives like "read the report file".

_SYNTHESIS_KEYWORDS = frozenset([
    "final answer", "summarize", "summary", "compare", "combine", "merge",
    "brief", "recommend", "recommendation", "list both results",
    "use all previous results", "create final output",
    "write summary from sources", "synthesize", "synthesis"
])

_SYNTHESIS_CONTEXT = frozenset([
    "final", "all", "previous", "prior", "sources", "findings",
    "results", "summary", "from the", "from all", "combine",
    "consolidate", "compile", "all prior", "all results",
    "all findings", "all sources"
])

_READ_VERBS = frozenset(["read", "fetch", "get", "load", "display", "show"])


def _extract_explicit_step_references(text: str) -> list:
    """
    Extract explicit step_N references from text.
    Supports: result of step_N, result of step N, output of step_N, output of step N, step_N, step N.
    Returns deduplicated canonical references in first-seen order.
    Does NOT infer dependencies from vague prose.
    """
    _PATTERN = re.compile(
        r'(?:result\s+of\s+|output\s+of\s+)?\bstep[_\s]?(\d+)\b',
        re.IGNORECASE
    )
    refs = []
    seen = set()
    for match in _PATTERN.finditer(text or ""):
        canonical = f"step_{int(match.group(1))}"
        if canonical not in seen:
            seen.add(canonical)
            refs.append(canonical)
    return refs


def _is_synthesis_step(purpose: str, expected_outcome: str) -> bool:
    """
    Narrow deterministic detection of final synthesis steps.

    Returns True ONLY when purpose/expected_outcome contains clear
    synthesis indicators per PLANNING_COMPILER_CONTRACT_V1 §10.

    Conservative: ordinary uses of "report" (e.g. "read the report file")
    are NOT treated as synthesis.
    """
    text = ((purpose or "") + " " + (expected_outcome or "")).lower()

    # Tier 1: strong synthesis indicators
    for kw in _SYNTHESIS_KEYWORDS:
        if kw in text:
            return True

    # Tier 2: "report" with synthesis context and read-verb guard
    if "report" in text:
        # Guard: "read the report", "get report", "show report"
        if re.search(r'\b(read|fetch|get|load|display|show)\s+\w*\s*report\b', text):
            return False
        # Guard: "report file"
        if re.search(r'\breport\s+file\b', text):
            return False

        # Require synthesis context to treat "report" as synthesis
        for ctx in _SYNTHESIS_CONTEXT:
            if ctx in text:
                return True

    return False


def _is_structurally_eligible_for_synthesis_check(step: dict, step_index: int, total_steps: int) -> bool:
    """
    Structural guard: only check synthesis dependency completeness where safe.

    - Final step in a multi-step workflow is always eligible.
    - Near-final steps are eligible ONLY if they contain strong multi-source wording.
    - Single-step workflows are never eligible.
    """
    if total_steps <= 1:
        return False

    # Final step: always structurally eligible
    if step_index == total_steps - 1:
        return True

    # Near-final steps: only with very strong multi-source wording
    text = ((step.get("purpose", "") + " " + step.get("expected_outcome", ""))).lower()
    strong_multi_source = [
        "all previous results", "all sources", "all findings",
        "all results", "use all", "from all", "combine all",
        "list both", "list all", "summarize all", "compare all",
        "merge all", "all prior"
    ]
    for phrase in strong_multi_source:
        if phrase in text:
            return True

    return False


def _get_required_synthesis_dependencies(steps: list, step_index: int) -> set:
    """
    Determine which prior steps a synthesis step at step_index MUST depend on.

    Returns step IDs of all prior steps that are NOT themselves synthesis steps.
    Prior synthesis/final-output steps are excluded unless explicitly referenced
    (which PDIAG-001 already validates separately).
    """
    required = set()
    current_step_id = steps[step_index].get("id")

    for i in range(step_index):
        prior = steps[i]
        prior_id = prior.get("id")
        if not prior_id:
            continue
        if prior_id == current_step_id:
            continue

        # Do not blindly require prior synthesis steps as source dependencies
        if _is_synthesis_step(prior.get("purpose", ""), prior.get("expected_outcome", "")):
            continue

        required.add(prior_id)

    return required


def _is_all_prior_synthesis_step(step: dict, step_index: int, total_steps: int) -> bool:
    """
    Determine if this step is a final/all-prior synthesis step that must depend
    on all required prior source steps.

    Steps with explicit single-target references (e.g. "summarize step_1")
    and no universal quantifier are treated as targeted dependencies,
    which PDIAG-001 already validates.
    """
    if not _is_structurally_eligible_for_synthesis_check(step, step_index, total_steps):
        return False

    if not _is_synthesis_step(step.get("purpose", ""), step.get("expected_outcome", "")):
        return False

    text = ((step.get("purpose", "") + " " + step.get("expected_outcome", ""))).lower()

    # Check for universal/multi-source quantifiers
    claims_all = any(phrase in text for phrase in [
        "all previous", "all results", "all findings", "all sources",
        "all prior", "every", "each", "both results", "list both",
        "use all", "from all", "combine all", "merge all"
    ])

    if claims_all:
        return True

    # If explicit references exist but no universal claim, PDIAG-001 handles it
    explicit_refs = []
    seen = set()
    for field in ["purpose", "expected_outcome"]:
        for ref in _extract_explicit_step_references(step.get(field, "")):
            if ref not in seen:
                seen.add(ref)
                explicit_refs.append(ref)

    if explicit_refs:
        # Targeted synthesis: PDIAG-001 validates explicit references
        return False

    # Strong synthesis indicator with no explicit references and no universal claim:
    # treat as all-prior synthesis (the core gap PDIAG-002A/002B addresses)
    return True
