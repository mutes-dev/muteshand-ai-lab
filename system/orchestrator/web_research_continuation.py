"""
F3 WebResearchProfile — bounded web-search-result URL handoff continuation.

Deterministic observe/resolve/apply pipeline that turns a pending step like
"Read the top search result" into a concrete URL read after a prior web_search
step has produced structured results.

Boundaries:
- Only activates for workflow-level WebResearchProfile.
- Only observes completed web_search steps with result observations.
- Only resolves bounded references: top/first/result N/ordinal result.
- Does not execute tools, bypass system_entry, bypass approval, or mutate lifecycle.
- Does not prompt the planner or AG1.
- Does not expose web_search to GeneralFallbackProfile.
"""

import re
from typing import Any, Dict, List, Optional

_WEB_RESEARCH_PROFILE = "WebResearchProfile"

# Maximum result index we will resolve (0-based). Keeps the feature bounded.
_MAX_RESULT_INDEX = 4

_ORDINAL_WORDS = {
    "first": 0,
    "second": 1,
    "third": 2,
    "fourth": 3,
    "fifth": 4,
}

# Action verbs that legitimize a read of a search result.
_ACTION_VERB_RE = re.compile(
    r"\b(?:read|open|fetch|get|load|view|visit)\b",
    re.IGNORECASE,
)

# Explicit URL check — if the step already has a URL, WebReadProfile/existing
# read_webpage handling takes over.
_URL_RE = re.compile(r"https?://", re.IGNORECASE)

# Web-search intent for pre-runtime dependency binding. Used to identify
# which prior steps are search-acquisition steps in a WebResearchProfile plan.
_WEB_SEARCH_INTENT_RE = re.compile(
    r"\b(?:search\s+the\s+web|web\s+search|search\s+online|internet\s+search|"
    r"online\s+search|search\s+for|google\s+for|look\s+up|lookup)\b",
    re.IGNORECASE,
)

# "result 1", "result 2nd", "result 3" etc.
_RESULT_NUMBER_RE = re.compile(
    r"\bresult\s+(\d+)(?:\s*(?:st|nd|rd|th))?\b",
    re.IGNORECASE,
)

# "first result", "second search result", etc.
_ORDINAL_RESULT_RE = re.compile(
    r"\b(first|second|third|fourth|fifth)\s+(?:search\s+)?result\b",
    re.IGNORECASE,
)

# "top search result", "top result", "first search result", "first result"
_TOP_RESULT_RE = re.compile(
    r"\b(?:top|first)\s+(?:search\s+)?result\b",
    re.IGNORECASE,
)

# Explicit prior-step reference like "from step_1" or "step_1"
_EXPLICIT_STEP_REF_RE = re.compile(
    r"\b(?:from|of)\s+step[_\s]?(\d+)\b",
    re.IGNORECASE,
)
_GENERIC_STEP_REF_RE = re.compile(
    r"\bstep[_\s]?(\d+)\b",
    re.IGNORECASE,
)

_UNSAFE_STEP_STATUSES = frozenset(("COMPLETED", "FAILED", "ACTIVE", "CANCELLED"))


# =============================================================================
# Public API
# =============================================================================

def observe_web_research_after_completion(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Observe a completed step and detect pending WebResearchProfile steps that
    reference one of its search results.

    Pure/advisory: no plan mutation, no tool execution, no lifecycle change.
    """
    try:
        return _observe(workflow, completed_step)
    except Exception as exc:  # pragma: no cover - defensive fallback
        return _safe_error_observation(workflow, completed_step, str(exc))


def resolve_web_research_continuation(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    observation: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Resolve detected web-search-result references to concrete URLs."""
    try:
        return _resolve_continuation_candidates(workflow, completed_step, observation)
    except Exception as exc:
        return _safe_error_resolution(workflow, completed_step, observation, str(exc))


def apply_web_research_continuation(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    resolutions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Apply resolved web-search-result URLs to pending downstream steps."""
    try:
        return _apply_resolved_continuations(workflow, completed_step, resolutions)
    except Exception as exc:
        return _safe_error_application(workflow, completed_step, resolutions, str(exc))


def apply_web_search_result_reference_binding(
    workflow: Dict[str, Any],
    user_input: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pre-runtime deterministic repair for WebResearchProfile plans.

    Binds pending read-top-result steps to the nearest prior web_search step
    so that execution scheduling does not run them in parallel before the
    search URL is available. No tool execution, no lifecycle change, no prompt
    change. Failure-isolated: returns the workflow unchanged on error.
    """
    try:
        return _apply_web_search_result_reference_binding(workflow, user_input)
    except Exception as exc:
        return workflow


# =============================================================================
# Internal observation
# =============================================================================

def _observe(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
) -> Dict[str, Any]:
    workflow_id = workflow.get("id", "unknown_workflow")
    completed_step_id = completed_step.get("id", "unknown_step")

    notes: List[str] = []
    matched_patterns: List[str] = []
    unresolved_refs_detected: List[Dict[str, Any]] = []
    continue_candidates: List[Dict[str, Any]] = []
    resolver_candidates: List[Dict[str, Any]] = []

    if not _is_web_research_workflow(workflow):
        notes.append("Workflow profile is not WebResearchProfile; skipping web-research continuation.")
        return _make_observation(
            workflow_id, completed_step_id, "none",
            unresolved_refs_detected, continue_candidates, resolver_candidates,
            False, None, notes,
            {"source_tool": "web_research_continuation", "downstream_step_count_scanned": 0},
        )

    if not _is_completed_web_search_with_results(completed_step):
        notes.append("Completed step is not a web_search with results; no web-research continuation.")
        return _make_observation(
            workflow_id, completed_step_id, "none",
            unresolved_refs_detected, continue_candidates, resolver_candidates,
            False, None, notes,
            {
                "source_tool": "web_research_continuation",
                "downstream_step_count_scanned": _count_downstream_steps(workflow, completed_step_id),
            },
        )

    steps = workflow.get("steps", [])
    completed_index = next(
        (i for i, s in enumerate(steps) if s.get("id") == completed_step_id),
        None,
    )
    if completed_index is None:
        notes.append("Completed step not found in workflow steps.")
        return _make_observation(
            workflow_id, completed_step_id, "none",
            unresolved_refs_detected, continue_candidates, resolver_candidates,
            False, None, notes,
            {"source_tool": "web_research_continuation", "downstream_step_count_scanned": 0},
        )

    downstream_steps = [
        s
        for s in steps[completed_index + 1 :]
        if isinstance(s, dict)
        and s.get("id") != completed_step_id
        and s.get("status", "PENDING") not in _UNSAFE_STEP_STATUSES
    ]

    for step in downstream_steps:
        text = _combine_text(step)
        if not text.strip():
            continue

        ref = _detect_web_search_result_reference(text)
        if not ref:
            continue

        explicit_step_id = _extract_explicit_step_reference(text)
        source_step, candidates = _find_source_web_search_step(
            workflow, step, explicit_step_id
        )
        if source_step is None:
            continue

        # Only accept the source if it is the completed step or a step that is
        # already completed before the target. This keeps the observer bounded
        # to evidence that already exists.
        if source_step.get("id") != completed_step_id and source_step.get("status") != "COMPLETED":
            continue

        step_id = step.get("id", "unknown_step")
        reference_text = ref["reference_text"]
        result_index = ref["result_index"]

        ambiguity_metadata: Dict[str, Any] = {"multiple_candidate_search_steps": False}
        if len(candidates) > 1 and explicit_step_id is None:
            ambiguity_metadata = {
                "multiple_candidate_search_steps": True,
                "candidate_search_step_ids": [s.get("id") for s in candidates],
                "selected_step_id": source_step.get("id"),
                "selected_by": "nearest_prior_completed_web_search",
                "warning": "multiple_prior_completed_web_search_steps_found; selected nearest prior",
            }

        detail = {
            "type": "web_search_result_reference",
            "match": reference_text,
            "step_id": step_id,
            "step_purpose": step.get("purpose"),
            "result_index": result_index,
            "explicit_step_id": explicit_step_id,
            "source_step_id": source_step.get("id"),
            "ambiguity_metadata": ambiguity_metadata,
        }
        unresolved_refs_detected.append(detail)
        matched_patterns.append("web_search_result_reference")

        continue_candidates.append({
            "step_id": step_id,
            "purpose": step.get("purpose"),
            "reason": "downstream_step_contains_web_search_result_reference",
            "reference_text": reference_text,
            "result_index": result_index,
            "source_step_id": source_step.get("id"),
        })

        resolver_candidates.append({
            "resolver_tool": "web_research_result_reference",
            "source_step_id": source_step.get("id"),
            "target_step_id": step_id,
            "reference_text": reference_text,
            "suggested_result_index": result_index,
            "ambiguity_metadata": ambiguity_metadata,
            "confidence": "candidate",
        })

    observation_type = (
        "web_search_result_reference_detected"
        if unresolved_refs_detected
        else "none"
    )

    if unresolved_refs_detected:
        notes.append(
            f"Detected {len(unresolved_refs_detected)} web-search-result reference(s) "
            f"across {len({d['step_id'] for d in unresolved_refs_detected})} downstream step(s)."
        )
    else:
        notes.append("No web-search-result references detected.")

    if continue_candidates:
        notes.append(f"{len(continue_candidates)} continuation candidate(s) identified.")

    return _make_observation(
        workflow_id, completed_step_id, observation_type,
        unresolved_refs_detected, continue_candidates, resolver_candidates,
        False, None, notes,
        {
            "source_tool": "web_research_continuation.observe_web_research_after_completion",
            "completed_step_tool": _extract_completed_tool_name(completed_step),
            "downstream_step_count_scanned": len(downstream_steps),
            "matched_patterns": list(dict.fromkeys(matched_patterns)),
        },
    )


def _combine_text(step: Dict[str, Any]) -> str:
    parts = [step.get("purpose") or "", step.get("expected_outcome") or ""]
    return " ".join(parts)


def _is_web_research_workflow(workflow: Dict[str, Any]) -> bool:
    if workflow.get("profile_name") == _WEB_RESEARCH_PROFILE:
        return True
    meta = workflow.get("_profile_metadata") or {}
    if meta.get("profile_name") == _WEB_RESEARCH_PROFILE:
        return True
    return False


def _detect_web_search_result_reference(text: str) -> Optional[Dict[str, Any]]:
    """
    Detect bounded web-search-result reference phrases.

    Returns dict with result_index (0-based) and reference_text, or None.
    """
    if not text or not isinstance(text, str):
        return None

    combined = text.lower()

    # Must express an action to read/open the result.
    if not _ACTION_VERB_RE.search(combined):
        return None

    # If an explicit URL is already present, existing WebReadProfile handling
    # should take over; do not interfere.
    if _URL_RE.search(combined):
        return None

    # Numeric result: "result 1", "result 2"
    m = _RESULT_NUMBER_RE.search(text)
    if m:
        idx = int(m.group(1)) - 1
        if idx < 0 or idx > _MAX_RESULT_INDEX:
            return None
        return {"result_index": idx, "reference_text": m.group(0)}

    # Ordinal result: "first result", "second search result"
    m = _ORDINAL_RESULT_RE.search(text)
    if m:
        idx = _ORDINAL_WORDS.get(m.group(1).lower(), 0)
        if idx > _MAX_RESULT_INDEX:
            return None
        return {"result_index": idx, "reference_text": m.group(0)}

    # Top/first result: "top search result", "top result", "first search result"
    m = _TOP_RESULT_RE.search(text)
    if m:
        return {"result_index": 0, "reference_text": m.group(0)}

    return None


def _extract_explicit_step_reference(text: str) -> Optional[str]:
    if not text or not isinstance(text, str):
        return None
    m = _EXPLICIT_STEP_REF_RE.search(text)
    if m:
        return f"step_{int(m.group(1))}"
    m = _GENERIC_STEP_REF_RE.search(text)
    if m:
        return f"step_{int(m.group(1))}"
    return None


def _find_source_web_search_step(
    workflow: Dict[str, Any],
    target_step: Dict[str, Any],
    explicit_step_id: Optional[str],
) -> tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Return the selected source web_search step and the full candidate list.

    Explicit step reference wins. Otherwise, nearest prior completed web_search
    step is selected. If multiple exist, the candidates list is returned for
    ambiguity metadata.
    """
    steps = workflow.get("steps", [])
    target_index = next(
        (i for i, s in enumerate(steps) if s.get("id") == target_step.get("id")),
        None,
    )
    if target_index is None:
        return None, []

    if explicit_step_id:
        source = next(
            (s for s in steps if s.get("id") == explicit_step_id),
            None,
        )
        if source and _is_completed_web_search_with_results(source):
            return source, [source]
        return None, []

    candidates = []
    for i in range(target_index - 1, -1, -1):
        s = steps[i]
        if _is_completed_web_search_with_results(s):
            candidates.append(s)
    if not candidates:
        return None, []
    return candidates[0], candidates


def _is_completed_web_search_with_results(step: Dict[str, Any]) -> bool:
    if step.get("status") != "COMPLETED":
        return False
    obs = _get_web_search_observation(step)
    if not obs:
        return False
    results = obs.get("results") or []
    return bool(results)


def _get_web_search_observation(step: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the structured web_search observation for a step, if any."""
    history = step.get("_web_search_observations") or []
    if history:
        obs = history[-1]
        if isinstance(obs, dict) and obs.get("observation_type") == "web_search":
            return obs
    er = step.get("execution_result") or {}
    obs = er.get("observation")
    if isinstance(obs, dict) and obs.get("observation_type") == "web_search":
        return obs
    return None


def _extract_completed_tool_name(completed_step: Dict[str, Any]) -> Optional[str]:
    execution_result = completed_step.get("execution_result")
    if isinstance(execution_result, dict):
        return execution_result.get("tool_name") or execution_result.get("tool")
    return None


def _count_downstream_steps(workflow: Dict[str, Any], completed_step_id: str) -> int:
    steps = workflow.get("steps", [])
    completed_index = next(
        (i for i, s in enumerate(steps) if s.get("id") == completed_step_id),
        None,
    )
    if completed_index is None:
        return 0
    return len(
        [
            s
            for s in steps[completed_index + 1 :]
            if isinstance(s, dict)
            and s.get("id") != completed_step_id
            and s.get("status", "PENDING") not in _UNSAFE_STEP_STATUSES
        ]
    )


def _make_observation(
    workflow_id: str,
    completed_step_id: str,
    observation_type: str,
    unresolved_refs_detected: List[Dict[str, Any]],
    continue_candidates: List[Dict[str, Any]],
    resolver_candidates: List[Dict[str, Any]],
    replan_needed: bool,
    blocked_reason: Optional[str],
    notes: List[str],
    metadata: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "completed_step_id": completed_step_id,
        "observation_type": observation_type,
        "unresolved_refs_detected": unresolved_refs_detected,
        "continue_candidates": continue_candidates,
        "resolver_candidates": resolver_candidates,
        "replan_needed": replan_needed,
        "blocked_reason": blocked_reason,
        "notes": notes,
        "metadata": metadata,
    }


def _safe_error_observation(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    error_message: str,
) -> Dict[str, Any]:
    workflow_id = workflow.get("id", "unknown_workflow") if isinstance(workflow, dict) else "unknown_workflow"
    completed_step_id = completed_step.get("id", "unknown_step") if isinstance(completed_step, dict) else "unknown_step"
    return {
        "workflow_id": workflow_id,
        "completed_step_id": completed_step_id,
        "observation_type": "none",
        "unresolved_refs_detected": [],
        "continue_candidates": [],
        "resolver_candidates": [],
        "replan_needed": False,
        "blocked_reason": None,
        "notes": [f"Web-research continuation observation failed safely: {error_message}"],
        "metadata": {
            "source_tool": "web_research_continuation",
            "error": error_message,
            "downstream_step_count_scanned": 0,
        },
    }


# =============================================================================
# Internal resolution
# =============================================================================

def _resolve_continuation_candidates(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    observation: Dict[str, Any],
) -> List[Dict[str, Any]]:
    candidates = observation.get("resolver_candidates") or []
    if not candidates:
        return []
    return [_resolve_candidate(workflow, c) for c in candidates]


def _resolve_candidate(
    workflow: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    reference_text = candidate.get("reference_text", "")
    source_step_id = candidate.get("source_step_id")
    target_step_id = candidate.get("target_step_id")
    result_index = candidate.get("suggested_result_index", 0)
    ambiguity_metadata = candidate.get("ambiguity_metadata") or {}

    source_step = next(
        (s for s in workflow.get("steps", []) if s.get("id") == source_step_id),
        None,
    )
    if source_step is None:
        return _make_resolution_result(
            source_step_id, target_step_id, reference_text, None,
            "unresolved", None, None, "source_step_not_found",
            ambiguity_metadata,
        )

    obs = _get_web_search_observation(source_step)
    if obs is None:
        return _make_resolution_result(
            source_step_id, target_step_id, reference_text, None,
            "unresolved", None, None, "source_observation_not_found",
            ambiguity_metadata,
        )

    results = obs.get("results") or []
    if not isinstance(results, list) or result_index < 0 or result_index >= len(results):
        return _make_resolution_result(
            source_step_id, target_step_id, reference_text,
            {"result_index": result_index, "available_count": len(results)},
            "unresolved", None, None, "result_index_out_of_range",
            ambiguity_metadata,
        )

    result = results[result_index]
    if isinstance(result, dict):
        url = result.get("url")
        title = result.get("title")
    else:
        url = getattr(result, "url", None)
        title = getattr(result, "title", None)

    if not url or not isinstance(url, str):
        return _make_resolution_result(
            source_step_id, target_step_id, reference_text,
            {"result_index": result_index, "result": result},
            "unresolved", None, None, "result_url_missing",
            ambiguity_metadata,
        )

    if not url.startswith(("http://", "https://")):
        return _make_resolution_result(
            source_step_id, target_step_id, reference_text,
            {"result_index": result_index, "url": url},
            "unresolved", None, None, "result_url_invalid",
            ambiguity_metadata,
        )

    resolver_input = {
        "source_step_id": source_step_id,
        "target_step_id": target_step_id,
        "result_index": result_index,
        "result_rank": result_index + 1,
        "reference_text": reference_text,
    }

    data_ref = {
        "source_step_id": source_step_id,
        "target_step_id": target_step_id,
        "result_rank": result_index + 1,
        "result_title": title,
        "resolved_url": url,
        "observation_id": obs.get("observation_id"),
        "provider": obs.get("provider"),
        "provider_host": obs.get("provider_host"),
        "ambiguity_metadata": ambiguity_metadata,
    }

    ambiguity = None
    if ambiguity_metadata.get("multiple_candidate_search_steps"):
        ambiguity = "multiple_prior_search_steps"

    return _make_resolution_result(
        source_step_id,
        target_step_id,
        reference_text,
        resolver_input,
        "resolved",
        url,
        data_ref,
        None,
        ambiguity_metadata,
        ambiguity=ambiguity,
    )


def _make_resolution_result(
    source_step_id: Optional[str],
    target_step_id: Optional[str],
    reference_text: str,
    resolver_input: Optional[Dict[str, Any]],
    status: str,
    resolved_value: Any,
    data_ref: Optional[Dict[str, Any]],
    blocked_reason: Optional[str],
    ambiguity_metadata: Optional[Dict[str, Any]] = None,
    ambiguity: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "f3_slice": "F3-WEBRESEARCH",
        "source_step_id": source_step_id,
        "target_step_id": target_step_id,
        "reference_text": reference_text,
        "resolver": "web_research_result_reference",
        "resolver_input": resolver_input,
        "status": status,
        "resolved_value": resolved_value,
        "resolved_url": resolved_value,
        "data_ref": data_ref,
        "confidence": "deterministic",
        "ambiguity": ambiguity,
        "ambiguity_metadata": ambiguity_metadata or {},
        "blocked_reason": blocked_reason,
    }


def _safe_error_resolution(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    observation: Dict[str, Any],
    error_message: str,
) -> List[Dict[str, Any]]:
    workflow_id = workflow.get("id", "unknown_workflow") if isinstance(workflow, dict) else "unknown_workflow"
    completed_step_id = completed_step.get("id", "unknown_step") if isinstance(completed_step, dict) else "unknown_step"
    return [
        {
            "f3_slice": "F3-WEBRESEARCH",
            "source_step_id": completed_step_id,
            "target_step_id": None,
            "reference_text": None,
            "resolver": "web_research_result_reference",
            "resolver_input": None,
            "status": "unresolved",
            "resolved_value": None,
            "resolved_url": None,
            "data_ref": None,
            "confidence": "deterministic",
            "ambiguity": None,
            "ambiguity_metadata": {},
            "blocked_reason": f"web_research_continuation_driver_error: {error_message}",
            "metadata": {
                "workflow_id": workflow_id,
                "observation_type": observation.get("observation_type") if isinstance(observation, dict) else None,
            },
        }
    ]


# =============================================================================
# Internal application
# =============================================================================

def _apply_resolved_continuations(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    resolutions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    applications: List[Dict[str, Any]] = []
    if not resolutions:
        return applications

    steps = workflow.get("steps", [])
    current_plan_version = workflow.get("plan_version")

    for resolution in resolutions:
        application = _try_apply_resolution(steps, resolution, current_plan_version)
        if application is not None:
            applications.append(application)
    return applications


def _try_apply_resolution(
    steps: List[Dict[str, Any]],
    resolution: Dict[str, Any],
    current_plan_version: Any,
) -> Optional[Dict[str, Any]]:
    if resolution.get("status") != "resolved":
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "resolution_not_resolved",
        )

    resolved_url = resolution.get("resolved_value") or resolution.get("resolved_url")
    if not resolved_url:
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "resolved_url_empty",
        )

    target_step_id = resolution.get("target_step_id")
    target_step = next(
        (s for s in steps if s.get("id") == target_step_id),
        None,
    )
    if target_step is None:
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "target_step_not_found",
        )

    step_status = target_step.get("status")
    if step_status in _UNSAFE_STEP_STATUSES:
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", f"target_step_status_{step_status}",
        )

    if target_step.get("_web_research_continuation_applied"):
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "already_continued",
        )

    # Keep existing F4 continuation metadata separate. If F4 already applied,
    # do not overwrite its state.
    if target_step.get("_continuation_applied"):
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "f4_continuation_already_applied",
        )

    old_purpose = target_step.get("purpose") or target_step.get("input") or ""
    if not old_purpose:
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "target_step_purpose_empty",
        )

    reference_text = resolution.get("reference_text", "")
    if reference_text and reference_text.lower() not in old_purpose.lower():
        if not _detect_web_search_result_reference(old_purpose):
            return _make_application_record(
                resolution, None, None,
                current_plan_version, current_plan_version,
                "skipped", "reference_text_not_present",
            )

    new_purpose = _rewrite_purpose_for_url(old_purpose, resolved_url, reference_text)
    if not new_purpose or new_purpose == old_purpose:
        return _make_application_record(
            resolution, old_purpose, None,
            current_plan_version, current_plan_version,
            "skipped", "rewrite_failed_or_unchanged",
        )

    # Apply the rewrite.
    target_step["purpose"] = new_purpose
    if "input" in target_step:
        target_step["input"] = new_purpose

    # Add dependency on the source web_search step if missing.
    source_step_id = resolution.get("source_step_id")
    if source_step_id:
        deps = target_step.get("depends_on") or []
        if not isinstance(deps, list):
            deps = []
        if source_step_id not in deps:
            target_step["depends_on"] = deps + [source_step_id]

    # Remove stale tool-selection artifacts so the next dispatch reclassifies.
    target_step["tool_call"] = None
    target_step["executed_input"] = None
    _agent_metadata = target_step.get("_agent_metadata")
    if isinstance(_agent_metadata, dict):
        _agent_metadata["selected_tool"] = None
        _agent_metadata["selected_agent_type"] = None
        _agent_metadata["selected_agent"] = None

    # Record continuation metadata on the step, separate from F4 markers.
    data_ref = resolution.get("data_ref") or {}
    target_step["_web_research_continuation_applied"] = True
    target_step["_web_research_continuation_source_step_id"] = source_step_id
    target_step["_web_research_continuation_resolved_url"] = resolved_url
    target_step["_web_research_continuation_reference_text"] = reference_text
    target_step["_web_research_continuation_result_rank"] = data_ref.get("result_rank")
    target_step["_web_research_continuation_result_title"] = data_ref.get("result_title")
    target_step["_web_research_continuation_observation_id"] = data_ref.get("observation_id")
    target_step["_web_research_continuation_resolver"] = "web_research_result_reference"
    target_step["_web_research_continuation_ambiguity_metadata"] = data_ref.get("ambiguity_metadata")

    return _make_application_record(
        resolution, old_purpose, new_purpose,
        current_plan_version, current_plan_version,
        "applied", None,
    )


def _rewrite_purpose_for_url(
    old_purpose: str,
    resolved_url: str,
    reference_text: str,
) -> str:
    """
    Rewrite the step purpose to use the concrete resolved URL.

    Tries to replace the matched reference phrase; falls back to a clean
    "Read <url>" style purpose.
    """
    new_purpose = old_purpose

    if reference_text:
        # Match an optional leading "the " so "Read the top result" becomes
        # "Read https://..." rather than "Read the https://...".
        pattern = r"(?<!\w)(?:the\s+)?" + re.escape(reference_text) + r"(?!\w)"
        new_purpose = re.sub(pattern, resolved_url, new_purpose, count=1, flags=re.IGNORECASE)

    if not new_purpose or new_purpose == old_purpose:
        # Preserve the original action verb if deterministically present.
        verb = "Read"
        m = re.search(r"\b(read|open|fetch|get|load|view|visit)\b", old_purpose, re.IGNORECASE)
        if m:
            verb = m.group(1).capitalize()
        new_purpose = f"{verb} {resolved_url}"

    # Normalize whitespace.
    new_purpose = re.sub(r"\s{2,}", " ", new_purpose).strip()
    return new_purpose


def _make_application_record(
    resolution: Dict[str, Any],
    old_purpose: Optional[str],
    new_purpose: Optional[str],
    plan_version_before: Any,
    plan_version_after: Any,
    status: str,
    blocked_reason: Optional[str],
) -> Dict[str, Any]:
    data_ref = resolution.get("data_ref") or {}
    return {
        "f3_slice": "F3-WEBRESEARCH",
        "source_step_id": resolution.get("source_step_id"),
        "target_step_id": resolution.get("target_step_id"),
        "resolution_ref": {
            "resolver": resolution.get("resolver"),
            "reference_text": resolution.get("reference_text"),
            "resolved_value": resolution.get("resolved_value"),
            "resolved_url": resolution.get("resolved_url"),
            "result_rank": data_ref.get("result_rank"),
            "result_title": data_ref.get("result_title"),
            "observation_id": data_ref.get("observation_id"),
        },
        "status": status,
        "old_purpose": old_purpose,
        "new_purpose": new_purpose,
        "plan_version_before": plan_version_before,
        "plan_version_after": plan_version_after,
        "authority": "web_research_continuation",
        "confidence": resolution.get("confidence"),
        "ambiguity": resolution.get("ambiguity"),
        "ambiguity_metadata": data_ref.get("ambiguity_metadata"),
        "blocked_reason": blocked_reason,
    }


def _safe_error_application(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    resolutions: List[Dict[str, Any]],
    error_message: str,
) -> List[Dict[str, Any]]:
    workflow_id = workflow.get("id", "unknown_workflow") if isinstance(workflow, dict) else "unknown_workflow"
    completed_step_id = completed_step.get("id", "unknown_step") if isinstance(completed_step, dict) else "unknown_step"
    return [
        {
            "f3_slice": "F3-WEBRESEARCH",
            "source_step_id": completed_step_id,
            "target_step_id": None,
            "resolution_ref": None,
            "status": "error",
            "old_purpose": None,
            "new_purpose": None,
            "plan_version_before": workflow.get("plan_version"),
            "plan_version_after": workflow.get("plan_version"),
            "authority": "web_research_continuation",
            "confidence": None,
            "ambiguity": None,
            "ambiguity_metadata": {},
            "blocked_reason": f"web_research_continuation_driver_error: {error_message}",
            "metadata": {
                "workflow_id": workflow_id,
            },
        }
    ]


# =============================================================================
# Pre-runtime dependency binding (no URL yet available)
# =============================================================================

def _has_web_search_intent(text: str) -> bool:
    """Return True if the step text expresses a web-search acquisition intent."""
    if not text or not isinstance(text, str):
        return False
    return bool(_WEB_SEARCH_INTENT_RE.search(text.lower()))


def _apply_web_search_result_reference_binding(
    workflow: Dict[str, Any],
    user_input: Optional[str],
) -> Dict[str, Any]:
    """
    Deterministic pre-runtime repair that adds explicit dependencies for
    pending WebResearchProfile read-top-result steps to the nearest prior
    web_search step. This prevents unsafe parallel execution before the
    search URL is observed.
    """
    if not _is_web_research_workflow(workflow):
        return workflow

    steps = workflow.get("steps", [])
    if not steps:
        return workflow

    # Identify prior web_search steps by deterministic plan intent. We do not
    # yet have execution_result at this point, so we rely on the planner's
    # bounded web-search wording.
    web_search_step_ids = set()
    for step in steps:
        step_id = step.get("id")
        if not step_id:
            continue
        if _has_web_search_intent(_combine_text(step)):
            web_search_step_ids.add(step_id)

    if not web_search_step_ids:
        return workflow

    for i, step in enumerate(steps):
        status = step.get("status", "PENDING")
        if status not in ("PENDING", None):
            # Only repair pending steps before execution begins.
            continue

        text = _combine_text(step)
        if _URL_RE.search(text):
            # Already a concrete URL read; let WebReadProfile handling take over.
            continue

        ref = _detect_web_search_result_reference(text)
        if not ref:
            continue

        explicit_step_id = _extract_explicit_step_reference(text)
        source_id = None
        if explicit_step_id:
            if explicit_step_id in web_search_step_ids:
                source_id = explicit_step_id
        else:
            # Nearest prior web_search step in plan order.
            for prior in reversed(steps[:i]):
                if prior.get("id") in web_search_step_ids:
                    source_id = prior.get("id")
                    break

        if not source_id:
            continue

        deps = step.get("depends_on") or []
        if not isinstance(deps, list):
            deps = []
        if source_id not in deps:
            step["depends_on"] = deps + [source_id]

        # Record that the dependency was bound pre-runtime (URL resolved later).
        step["_web_research_continuation_bound"] = True
        step["_web_research_continuation_source_step_id"] = source_id
        step["_web_research_continuation_reference_text"] = ref.get("reference_text")
        step["_web_research_continuation_result_index"] = ref.get("result_index")

    return workflow
