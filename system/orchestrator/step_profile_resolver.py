"""
Step Profile Resolver — D1b Step-Scoped Profile Narrowing for Mixed Workflows.

Deterministically assigns step-level tool profiles to individual steps within
mixed-domain GeneralFallbackProfile workflows so AG1 receives a narrowed tool
view per step instead of the full production tool set.

This module is:
- Deterministic (keyword/regex matching, no LLM calls)
- Conservative (leaves ambiguous steps unset → workflow-level fallback)
- Internal-only (writes _step_profile metadata on step dicts)
- Non-authoritative (does not alter depends_on, purpose, expected_outcome,
  lifecycle, execution_result, projection, or any contract field)

Scope gate:
- Only runs on workflows where profile_name == GeneralFallbackProfile
  AND profile_reason_code == mixed_domain_workflow
- Does NOT run on capability-emitted workflows or non-mixed fallback workflows

Classification priority (first match wins):
1. Resolved web/search intent (no URL) → WebSearchProfile
2. Explicit URL in purpose/resource_targets → WebReadProfile
3. Unresolved-reference web/search intent → leave unset (workflow-level fallback)
4. File mutation intent (write/edit/append/save) → FileMutationProfile
5. Compute intent (arithmetic) → ComputeProfile
6. Document/local read intent → DocumentReadProfile
7. Document summary/transform intent → DocumentSummaryProfile
8. Unknown/ambiguous → leave unset (fall back to workflow-level profile)
"""

import re
from typing import Any, Dict, Optional


# ── Web/search intent keywords ──────────────────────────────────────────────
_WEB_SEARCH_KEYWORDS = [
    "search the web", "web search", "search online", "look up", "lookup",
    "find more info", "find more information", "more info", "more information",
    "related context", "online context", "research", "website", "webpage",
    "internet", "search for more", "search for related",
]

_WEB_SEARCH_RE = re.compile(
    r'\b(?:search\s+the\s+web|web\s+search|search\s+online|look\s+up|lookup|'
    r'find\s+more\s+info|find\s+more\s+information|more\s+info|'
    r'more\s+information|related\s+context|online\s+context|research|'
    r'website|webpage|internet|search\s+for\s+more|search\s+for\s+related)\b',
    re.IGNORECASE,
)

_URL_RE = re.compile(r'https?://', re.IGNORECASE)

# ── File mutation intent keywords ───────────────────────────────────────────
_FILE_MUTATION_RE = re.compile(
    r'\b(?:write|edit|append|save|overwrite|create\s+file|update\s+file)\b',
    re.IGNORECASE,
)

_FILE_MUTATION_PATH_RE = re.compile(
    r'\b(?:write|edit|append|save|overwrite)\b.*\.(?:txt|py|js|json|csv|md|html|xml|yaml|yml|cfg|ini|log|tsv)',
    re.IGNORECASE,
)

# ── Compute intent keywords ─────────────────────────────────────────────────
_COMPUTE_RE = re.compile(
    r'\b(?:add|subtract|multiply|divide|square|cube|square\s+root|factorial|'
    r'fibonacci|calculate|arithmetic)\b',
    re.IGNORECASE,
)

# ── Document read intent keywords ───────────────────────────────────────────
_DOC_READ_RE = re.compile(
    r'\b(?:read|list\s+files|list\s+file)\b.*\.(?:csv|xlsx|xls|pdf|docx|txt|md|json|xml|html|tsv|log)',
    re.IGNORECASE,
)

_DOC_READ_GENERIC_RE = re.compile(
    r'\b(?:read\s+local\s+file|read\s+csv|read\s+spreadsheet|read\s+pdf|read\s+docx|'
    r'read\s+file|list\s+files|read\s+image)\b',
    re.IGNORECASE,
)

# ── Document summary/transform intent keywords ──────────────────────────────
_DOC_SUMMARY_RE = re.compile(
    r'\b(?:summarize|summarise|explain|extract\s+key\s+points)\b',
    re.IGNORECASE,
)

# ── Q&A quarantine keywords (must NOT trigger DocumentSummaryProfile) ────────
_QA_KEYWORDS = [
    "answer", "tell me", "who", "where", "how big", "highest score",
    "what is", "what are", "when", "why", "how many",
]

# ── Local-source / prior-step dependency markers (F3B-FIX3) ─────────────────
# Web-search steps that still reference a local file, spreadsheet, document,
# or prior-step output are NOT resolved enough to be narrowed to WebSearchProfile.
_LOCAL_FILE_EXTENSION_RE = re.compile(
    r"\.(?:csv|xlsx|xls|xlsm|txt|md|pdf|docx|png|jpg|jpeg|json|py)\b",
    re.IGNORECASE,
)

_LOCAL_PATH_PREFIX_RE = re.compile(
    r"\b(?:tmp|project docs|data|docs|reports?|src|assets?)\s*[\\/]",
    re.IGNORECASE,
)

_LOCAL_SOURCE_NOUN_RE = re.compile(
    r"\b(?:csv\s+file|xlsx\s+file|xls\s+file|spreadsheet|workbook|"
    r"document|file|sheet|csv|xlsx|xls)\b",
    re.IGNORECASE,
)

_PRIOR_STEP_REFERENCE_RE = re.compile(
    r"\b(?:step[_\s]?\d+|previous\s+step|prior\s+step|"
    r"result\s+of\s+step|file\s+read\s+by\s+step|"
    r"using\s+(?:the\s+)?result\s+of|from\s+step[_\s]?|"
    r"output\s+of\s+step)\b",
    re.IGNORECASE,
)

_LOCAL_DATA_REFERENCE_RE = re.compile(
    r"\b(?:company|person|value|name|url|entity)\s+in\s+(?:row|cell|"
    r"the\s+(?:file|spreadsheet|csv|xlsx|workbook|document|sheet))",
    re.IGNORECASE,
)


def _has_local_source_reference(text: str) -> bool:
    """Return True if the search text still depends on a local source or prior step."""
    if not text or not isinstance(text, str):
        return False
    if _LOCAL_FILE_EXTENSION_RE.search(text):
        return True
    if _LOCAL_PATH_PREFIX_RE.search(text):
        return True
    if _LOCAL_SOURCE_NOUN_RE.search(text):
        return True
    if _PRIOR_STEP_REFERENCE_RE.search(text):
        return True
    if _LOCAL_DATA_REFERENCE_RE.search(text):
        return True
    return False


def _is_mixed_domain_workflow(workflow: dict) -> bool:
    """Check if this workflow is a mixed-domain GeneralFallbackProfile workflow."""
    profile_name = workflow.get("profile_name", "")
    if profile_name != "GeneralFallbackProfile":
        return False

    profile_meta = workflow.get("_profile_metadata") or {}
    reason_code = profile_meta.get("profile_reason_code", "")

    if reason_code == "mixed_domain_workflow":
        return True

    # Also check capability route metadata for mixed-domain fallback
    route_meta = workflow.get("_capability_route_metadata") or {}
    route_reason = route_meta.get("route_reason_code", "")
    fallback_reason = route_meta.get("fallback_reason", "")

    if route_reason == "fallback_mixed_domain" or fallback_reason == "fallback_mixed_domain":
        return True

    return False


def _classify_step_profile(step: dict) -> Optional[tuple]:
    """
    Classify a single step's intent and return (profile_name, reason_code) or None.

    Priority order: web > URL > mutation > compute > doc_read > doc_summary > unknown
    """
    purpose = (step.get("purpose") or "").strip()
    expected_outcome = (step.get("expected_outcome") or "").strip()
    combined = f"{purpose} {expected_outcome}"

    if not combined.strip():
        return None

    # 1. Bounded web-research intent → WebResearchProfile
    #    Search + read + source-backed synthesis, no explicit URL, no unresolved
    #    or local-source references. Checked before WebSearchProfile/WebReadProfile
    #    so that multi-step research workflows are narrowed correctly.
    try:
        from system.orchestrator.profile_selector import _has_web_research_intent
        if _has_web_research_intent(combined):
            return ("WebResearchProfile", "web_research_intent")
    except Exception:
        pass

    # 2. Explicit URL in purpose or resource_targets → WebReadProfile
    #    Checked before WebSearchProfile so "research https://example.com" routes
    #    to WebReadProfile, not WebSearchProfile.
    if _URL_RE.search(combined):
        return ("WebReadProfile", "explicit_url")

    resource_targets = step.get("resource_targets") or []
    if isinstance(resource_targets, list):
        for rt in resource_targets:
            if isinstance(rt, str) and _URL_RE.search(rt):
                return ("WebReadProfile", "explicit_url_in_resource_targets")

    # 3. Web/search intent → WebSearchProfile when the query is resolved
    #    (must override file path).
    #    Unresolved references (e.g., "person in row 2") are left unset so the
    #    workflow-level profile (GeneralFallbackProfile) prevents web_search use.
    #    F3B-FIX3: local-source / prior-step references also leave the step unset.
    if _WEB_SEARCH_RE.search(combined):
        try:
            from system.orchestrator.profile_selector import _has_unresolved_reference
            if _has_unresolved_reference(combined):
                return None
            if _has_local_source_reference(combined):
                return None
        except Exception:
            pass
        return ("WebSearchProfile", "web_search_intent")

    # 4. File mutation intent → FileMutationProfile
    if _FILE_MUTATION_RE.search(combined) or _FILE_MUTATION_PATH_RE.search(combined):
        # Exclude pure "read" steps that mention "write" in a different context
        # e.g., "Read the file that was written" should not be FileMutationProfile
        # Check if the step is primarily a read step
        purpose_lower = purpose.lower()
        if purpose_lower.startswith("read"):
            pass  # It's a read step, don't classify as mutation
        else:
            return ("FileMutationProfile", "file_mutation_intent")

    # 5. Compute intent → ComputeProfile (only if no mutation or web)
    if _COMPUTE_RE.search(combined):
        # Exclude file-based calculations (e.g., "calculate average from CSV")
        # These remain unsupported/future-owned
        if not _DOC_READ_RE.search(combined) and not _DOC_READ_GENERIC_RE.search(combined):
            return ("ComputeProfile", "compute_intent")

    # 6. Document/local read intent → DocumentReadProfile
    if _DOC_READ_RE.search(combined) or _DOC_READ_GENERIC_RE.search(combined):
        return ("DocumentReadProfile", "document_read_intent")

    # 7. Document summary/transform intent → DocumentSummaryProfile
    if _DOC_SUMMARY_RE.search(combined):
        # Q&A quarantine: do not classify Q&A as summary
        combined_lower = combined.lower()
        if any(qa_kw in combined_lower for qa_kw in _QA_KEYWORDS):
            pass  # Leave unset — Q&A is quarantined
        else:
            return ("DocumentSummaryProfile", "document_summary_intent")

    # 8. Unknown/ambiguous → leave unset
    return None


def resolve_step_profiles_for_workflow(
    workflow: dict,
    user_input: str | None = None,
) -> dict:
    """
    Apply step-level profile narrowing to a mixed-domain GeneralFallbackProfile workflow.

    Writes internal _step_profile metadata on each step dict.
    Does NOT modify depends_on, purpose, expected_outcome, or any lifecycle field.
    Does NOT run on non-mixed workflows.

    Args:
        workflow: The workflow dict with steps list.
        user_input: Optional original user input (unused currently, reserved for future).

    Returns:
        The same workflow dict with step-level profile metadata attached.
    """
    if not isinstance(workflow, dict):
        return workflow

    # Scope gate: only run on mixed-domain GeneralFallbackProfile workflows
    if not _is_mixed_domain_workflow(workflow):
        return workflow

    steps = workflow.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        return workflow

    for step in steps:
        if not isinstance(step, dict):
            continue

        # Skip if already has a step profile (idempotent)
        if step.get("_step_profile"):
            continue

        result = _classify_step_profile(step)
        if result is not None:
            profile_name, reason_code = result
            step["_step_profile"] = profile_name
            step["_step_profile_reason_code"] = reason_code
            step["_step_profile_source"] = "d1b_step_profile_resolver"
        # If None, leave unset — AG1 falls back to workflow-level profile

    return workflow
