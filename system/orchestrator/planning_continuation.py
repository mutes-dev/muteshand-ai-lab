"""
F4-A1 — OBSERVE-ONLY CONTINUATION CANDIDATE DETECTION

This module is advisory-only planning control.

It observes a completed step and the remaining plan to detect downstream
unresolved/local-source/prior-step references that may become resolvable once
new evidence exists.

F4-A1 BOUNDARIES:
- No plan mutation.
- No resolver execution.
- No replan execution.
- No lifecycle transition.
- No governance change.
- No system_entry call.
- No AG1 authority change.
- No web_search unlock.
"""

import re
from typing import Any, Dict, List, Optional

# ── REUSE F3B DETECTION HELPERS (FAILURE-ISOLATED) ───────────────────────────
# These helpers are deterministic regex guards. Importing them avoids duplicating
# the canonical unresolved-reference pattern set and local-source markers.
try:
    from system.orchestrator.profile_selector import _has_unresolved_reference
except Exception:

    def _has_unresolved_reference(text: str) -> bool:  # type: ignore[no-redef]
        return False


try:
    from system.orchestrator.step_profile_resolver import (
        _has_local_source_reference,
        _PRIOR_STEP_REFERENCE_RE,
        _WEB_SEARCH_RE,
    )
except Exception:

    def _has_local_source_reference(text: str) -> bool:  # type: ignore[no-redef]
        return False

    _PRIOR_STEP_REFERENCE_RE = None  # type: ignore[assignment]
    _WEB_SEARCH_RE = None  # type: ignore[assignment]


try:
    import tools.resolve_table_reference as _table_resolver
except Exception:
    _table_resolver = None


# ── LOCAL PATTERNS FOR ROW/CELL/ENTITY/COLUMN EXTRACTION ─────────────────────
# These are intentionally narrower than the F3B guard patterns: they extract
# numeric row/cell references so the resolver candidate can be built.

_ROW_RE = re.compile(
    r'\b(?:row|rows)\s+(\d+)\b',
    re.IGNORECASE,
)

_CELL_RE = re.compile(
    r'\bcell\s+([A-Za-z]\d+)\b',
    re.IGNORECASE,
)

_ENTITY_IN_ROW_RE = re.compile(
    r'\b(?:person|company|name|value|url|entity|item)\s+in\s+(?:row|rows)\s+(\d+)\b',
    re.IGNORECASE,
)

_COLUMN_RE = re.compile(
    r'\b(?:column|col)\s+([A-Za-z][A-Za-z0-9_ ]*?)\b',
    re.IGNORECASE,
)

_COLUMN_IN_PHRASE_RE = re.compile(
    r'\b(?:value|name|person|company|url|entity|item)\s+in\s+(?:the\s+)?(?:([A-Za-z][A-Za-z0-9_ ]+?)\s+)?column\b',
    re.IGNORECASE,
)

_FILE_PATH_RE = re.compile(
    r'\b(?:[\w\\/-]+)?\w+\.(?:csv|xlsx|xls|xlsm)\b',
    re.IGNORECASE,
)

_EXPLICIT_LOCAL_SOURCE_RE = re.compile(
    r'\b(?:[\w\\/-]+)?\w+\.(?:csv|xlsx|xls|xlsm)\b|'
    r'\b(?:csv\s+file|xlsx\s+file|spreadsheet|workbook|csv|xlsx)\b',
    re.IGNORECASE,
)

_ORDINAL_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}

_HEADER_ORDINAL_RE = re.compile(
    r'\b(?:(\d+)(?:st|nd|rd|th)|(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth))\s+(?:header\s+column|column\s+header)\b',
    re.IGNORECASE,
)

_COLUMN_VALUE_ORDINAL_RE = re.compile(
    r'\b(?:(\d+)(?:st|nd|rd|th)|(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth))\s+(?:name|person|company|entity|item)\b',
    re.IGNORECASE,
)

_COLUMN_VALUE_ORDINAL_IN_COLUMN_RE = re.compile(
    r'\b(?:(\d+)(?:st|nd|rd|th)|(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth))\s+value\s+in\s+(?:the\s+)?([A-Za-z][A-Za-z0-9_ ]*?)\s*(?:column)?\b',
    re.IGNORECASE,
)

_FINALIZE_PRESENT_RE = re.compile(
    r'\b(?:present|finalize|show|display)\b',
    re.IGNORECASE,
)


# ── PUBLIC API ───────────────────────────────────────────────────────────────

def observe_step_after_completion(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Observe a completed step and detect downstream continuation candidates.

    This function is pure/advisory:
    - it does not mutate the plan;
    - it does not execute any tool;
    - it does not own lifecycle or governance.

    Args:
        workflow: The internal workflow dict.
        completed_step: The step that just completed.

    Returns:
        Deterministic, serializable ObservationResult dict.
    """
    try:
        return _observe(workflow, completed_step)
    except Exception as exc:  # pragma: no cover - defensive fallback
        return _safe_error_observation(workflow, completed_step, str(exc))


# ── INTERNAL IMPLEMENTATION ──────────────────────────────────────────────────

def _observe(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
) -> Dict[str, Any]:
    workflow_id = workflow.get("id", "unknown_workflow")
    completed_step_id = completed_step.get("id", "unknown_step")
    completed_tool = _extract_completed_tool_name(completed_step)

    downstream_steps = _downstream_steps(workflow, completed_step_id)

    unresolved_refs_detected: List[Dict[str, Any]] = []
    continue_candidates: List[Dict[str, Any]] = []
    resolver_candidates: List[Dict[str, Any]] = []
    matched_patterns: List[str] = []
    notes: List[str] = []

    for step in downstream_steps:
        text = _combine_text(step)
        if not text.strip():
            continue

        details = _detect_reference_details(step, text)
        if not details:
            continue

        step_id = step.get("id", "unknown_step")
        purpose = step.get("purpose", "")
        step_has_web_intent = _has_web_search_intent(text)

        for detail in details:
            detail["step_id"] = step_id
            detail["step_purpose"] = purpose
            unresolved_refs_detected.append(detail)
            matched_patterns.append(detail["type"])

        is_relevant_downstream = _is_relevant_downstream(
            completed_step_id,
            step,
            details,
        )

        if is_relevant_downstream and _has_resolvable_detail(details):
            continue_candidates.append({
                "step_id": step_id,
                "purpose": purpose,
                "reason": "downstream_step_contains_resolvable_reference",
            })

            file_path = _resolve_file_path(text, completed_step)
            resolver_candidates.extend(
                _build_resolver_candidates(
                    completed_step_id,
                    step_id,
                    text,
                    details,
                    file_path,
                )
            )

    observation_type = _classify_observation_type(unresolved_refs_detected)
    replan_needed, blocked_reason = _classify_replan_and_block(
        unresolved_refs_detected,
        continue_candidates,
    )

    if unresolved_refs_detected:
        notes.append(
            f"Detected {len(unresolved_refs_detected)} unresolved reference(s) "
            f"across {len({d['step_id'] for d in unresolved_refs_detected})} downstream step(s)."
        )
    else:
        notes.append("No unresolved downstream references detected.")

    if continue_candidates:
        notes.append(
            f"{len(continue_candidates)} continuation candidate(s) identified."
        )

    if replan_needed:
        notes.append("Advisory replan_needed flagged; no replan executed in F4-A1.")

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
        "metadata": {
            "f4_slice": "F4-A1",
            "source_tool": "planning_continuation.observe_step_after_completion",
            "completed_step_tool": completed_tool,
            "downstream_step_count_scanned": len(downstream_steps),
            "matched_patterns": list(dict.fromkeys(matched_patterns)),
        },
    }


def _safe_error_observation(
    workflow: Any,
    completed_step: Any,
    error_message: str,
) -> Dict[str, Any]:
    """Return a no-op observation when the observer itself fails."""
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
        "notes": [f"F4-A1 observation failed safely: {error_message}"],
        "metadata": {
            "f4_slice": "F4-A1",
            "error": error_message,
            "downstream_step_count_scanned": 0,
        },
    }


# ── DETECTION HELPERS ────────────────────────────────────────────────────────

def _combine_text(step: Dict[str, Any]) -> str:
    parts = [step.get("purpose") or "", step.get("expected_outcome") or ""]
    return " ".join(parts)


def _downstream_steps(
    workflow: Dict[str, Any],
    completed_step_id: str,
) -> List[Dict[str, Any]]:
    """Return steps that are not yet terminal and are not the completed step."""
    terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}
    return [
        step
        for step in workflow.get("steps", [])
        if isinstance(step, dict)
        and step.get("id") != completed_step_id
        and step.get("status", "PENDING") not in terminal_statuses
    ]


def _detect_reference_details(
    step: Dict[str, Any], text: str
) -> List[Dict[str, Any]]:
    details: List[Dict[str, Any]] = []
    seen_matches: set = set()

    for match in _ENTITY_IN_ROW_RE.finditer(text):
        token = match.group(0)
        if token not in seen_matches:
            seen_matches.add(token)
            details.append({
                "type": "entity_in_row",
                "match": token,
                "row_number": int(match.group(1)),
            })

    entity_in_row_numbers = {d["row_number"] for d in details if d["type"] == "entity_in_row"}
    for match in _ROW_RE.finditer(text):
        token = match.group(0)
        row_number = int(match.group(1))
        if token not in seen_matches and row_number not in entity_in_row_numbers:
            seen_matches.add(token)
            details.append({
                "type": "row_reference",
                "match": token,
                "row_number": row_number,
            })

    for match in _CELL_RE.finditer(text):
        token = match.group(0)
        if token not in seen_matches:
            seen_matches.add(token)
            details.append({
                "type": "cell_reference",
                "match": token,
                "cell_reference": match.group(1),
            })

    for match in _HEADER_ORDINAL_RE.finditer(text):
        token = match.group(0)
        ordinal = _ordinal_from_match(match)
        if ordinal and token not in seen_matches:
            seen_matches.add(token)
            details.append({
                "type": "header_ordinal",
                "match": token,
                "ordinal": ordinal,
            })

    for match in _COLUMN_VALUE_ORDINAL_IN_COLUMN_RE.finditer(text):
        token = match.group(0)
        ordinal = _ordinal_from_match(match)
        column_name = (match.group(3) or "").strip()
        if ordinal and token not in seen_matches:
            seen_matches.add(token)
            details.append({
                "type": "column_value_ordinal",
                "match": token,
                "ordinal": ordinal,
                "column_name": column_name,
            })

    for match in _COLUMN_VALUE_ORDINAL_RE.finditer(text):
        token = match.group(0)
        ordinal = _ordinal_from_match(match)
        if ordinal and token not in seen_matches:
            seen_matches.add(token)
            details.append({
                "type": "column_value_ordinal",
                "match": token,
                "ordinal": ordinal,
                "column_name": None,
            })

    for match in _COLUMN_RE.finditer(text):
        token = match.group(0)
        col_name = match.group(1).strip()
        if token not in seen_matches and col_name:
            seen_matches.add(token)
            details.append({
                "type": "column_reference",
                "match": token,
                "column_name": col_name,
            })

    for match in _COLUMN_IN_PHRASE_RE.finditer(text):
        token = match.group(0)
        col_name = (match.group(1) or "").strip()
        if token not in seen_matches and col_name:
            seen_matches.add(token)
            details.append({
                "type": "column_reference",
                "match": token,
                "column_name": col_name,
            })

    if (
        _has_web_search_intent(text)
        and _has_local_source_reference(text)
        and _has_explicit_local_source_token(text)
    ):
        details.append({
            "type": "local_source",
            "match": "local_source_marker",
        })

    if _PRIOR_STEP_REFERENCE_RE is not None and _PRIOR_STEP_REFERENCE_RE.search(text):
        if not _is_pure_present_finalize_step(step, text, details):
            details.append({
                "type": "prior_step",
                "match": "prior_step_marker",
            })

    return details


def _has_resolvable_detail(details: List[Dict[str, Any]]) -> bool:
    return any(
        d.get("type")
        in (
            "entity_in_row",
            "row_reference",
            "cell_reference",
            "header_ordinal",
            "column_value_ordinal",
        )
        for d in details
    )


def _ordinal_from_match(match: Any) -> Optional[int]:
    numeric = match.group(1)
    if numeric:
        return int(numeric)
    word = match.group(2)
    if word:
        return _ORDINAL_WORDS.get(word.lower())
    return None


def _has_explicit_local_source_token(text: str) -> bool:
    """Return True if the text contains an explicit CSV/XLSX/spreadsheet/file token."""
    return bool(_EXPLICIT_LOCAL_SOURCE_RE.search(text))


def _is_pure_present_finalize_step(
    step: Dict[str, Any], text: str, details: List[Dict[str, Any]]
) -> bool:
    if any(
        d.get("type")
        in (
            "entity_in_row",
            "row_reference",
            "cell_reference",
            "header_ordinal",
            "column_value_ordinal",
        )
        for d in details
    ):
        return False
    if _has_web_search_intent(text):
        return False
    if _FINALIZE_PRESENT_RE.search(text):
        return True
    cap = step.get("capability_metadata") or {}
    if cap.get("final_action") == "present" or cap.get("intent_mode") == "present":
        return True
    agent_meta = step.get("_agent_metadata") or {}
    if agent_meta.get("selected_tool") == "finalize_output":
        return True
    return False


def _has_web_search_intent(text: str) -> bool:
    """Return True if the text expresses a web-search/research intent."""
    if _WEB_SEARCH_RE is not None:
        return bool(_WEB_SEARCH_RE.search(text))
    # Minimal fallback if the import failed.
    return bool(re.search(
        r'\b(?:search\s+(?:the\s+)?web|web\s+search|search\s+online|look\s+up|lookup|'
        r'find\s+more\s+info(?:rmation)?|more\s+info(?:rmation)?|related\s+context|'
        r'online\s+context|research)\b',
        text,
        re.IGNORECASE,
    ))


def _is_relevant_downstream(
    completed_step_id: str,
    step: Dict[str, Any],
    details: List[Dict[str, Any]],
) -> bool:
    """
    A downstream step is relevant for continuation if it depends on the
    completed step, or explicitly references a prior step / local source.
    """
    depends_on = step.get("depends_on") or []
    if completed_step_id in depends_on:
        return True

    for detail in details:
        if detail["type"] == "prior_step":
            return True

    return False


def _resolve_file_path(
    text: str,
    completed_step: Dict[str, Any],
) -> Optional[str]:
    """Advisory file-path extraction: explicit text first, then completed step resource_targets."""
    explicit = _extract_file_path(text)
    if explicit:
        return explicit

    for target in completed_step.get("resource_targets") or []:
        if isinstance(target, str) and _FILE_PATH_RE.search(target):
            return target

    return None


def _extract_file_path(text: str) -> Optional[str]:
    match = _FILE_PATH_RE.search(text)
    return match.group(0) if match else None


def _extract_completed_tool_name(completed_step: Dict[str, Any]) -> Optional[str]:
    execution_result = completed_step.get("execution_result")
    if isinstance(execution_result, dict):
        return execution_result.get("tool_name") or execution_result.get("tool")
    return None


def _build_resolver_candidates(
    completed_step_id: str,
    target_step_id: str,
    text: str,
    details: List[Dict[str, Any]],
    file_path: Optional[str],
) -> List[Dict[str, Any]]:
    """Advisory resolver candidates only — no tool execution."""
    candidates: List[Dict[str, Any]] = []
    has_entity_word = bool(re.search(
        r'\b(?:person|company|name|value|url|entity|item)\b',
        text,
        re.IGNORECASE,
    ))

    for detail in details:
        dtype = detail.get("type")

        if dtype == "entity_in_row":
            candidates.append({
                "resolver_tool": "resolve_table_reference",
                "source_step_id": completed_step_id,
                "target_step_id": target_step_id,
                "reference_text": detail["match"],
                "suggested_reference_type": "entity_from_row",
                "suggested_row_number": detail.get("row_number"),
                "suggested_entity_column": "__AUTO_NAME_LIKE__",
                "suggested_file_path": file_path,
                "confidence": "candidate",
            })

        elif dtype == "row_reference":
            candidates.append({
                "resolver_tool": "resolve_table_reference",
                "source_step_id": completed_step_id,
                "target_step_id": target_step_id,
                "reference_text": detail["match"],
                "suggested_reference_type": "entity_from_row" if has_entity_word else "row",
                "suggested_row_number": detail.get("row_number"),
                "suggested_entity_column": "__AUTO_NAME_LIKE__" if has_entity_word else None,
                "suggested_file_path": file_path,
                "confidence": "candidate",
            })

        elif dtype == "cell_reference":
            candidates.append({
                "resolver_tool": "resolve_table_reference",
                "source_step_id": completed_step_id,
                "target_step_id": target_step_id,
                "reference_text": detail["match"],
                "suggested_reference_type": "cell",
                "suggested_cell_reference": detail.get("cell_reference"),
                "suggested_file_path": file_path,
                "confidence": "candidate",
            })

        elif dtype == "header_ordinal":
            candidates.append({
                "resolver_tool": "resolve_table_reference",
                "source_step_id": completed_step_id,
                "target_step_id": target_step_id,
                "reference_text": detail["match"],
                "suggested_reference_type": "header",
                "suggested_header_ordinal": detail.get("ordinal"),
                "suggested_file_path": file_path,
                "confidence": "candidate",
            })

        elif dtype == "column_value_ordinal":
            candidates.append({
                "resolver_tool": "resolve_table_reference",
                "source_step_id": completed_step_id,
                "target_step_id": target_step_id,
                "reference_text": detail["match"],
                "suggested_reference_type": "column_value",
                "suggested_row_number": (detail.get("ordinal") or 0) + 1,
                "suggested_entity_column": detail.get("column_name") or "__AUTO_NAME_LIKE__",
                "suggested_file_path": file_path,
                "confidence": "candidate",
            })

    return candidates


def _classify_observation_type(
    unresolved_refs_detected: List[Dict[str, Any]],
) -> str:
    if not unresolved_refs_detected:
        return "none"

    types = {d.get("type") for d in unresolved_refs_detected}
    if types & {"entity_in_row", "row_reference", "cell_reference", "header_ordinal", "column_value_ordinal"}:
        return "unresolved_downstream_reference_detected"
    if "prior_step" in types:
        return "prior_step_reference_detected"
    if "local_source" in types:
        return "local_source_reference_detected"
    return "ambiguous_reference_detected"


def _classify_replan_and_block(
    unresolved_refs_detected: List[Dict[str, Any]],
    continue_candidates: List[Dict[str, Any]],
) -> tuple:
    if not unresolved_refs_detected:
        return False, None

    if continue_candidates:
        # A concrete resolver candidate exists; continuation may be feasible.
        return False, None

    types = {d.get("type") for d in unresolved_refs_detected}
    if "local_source" in types:
        return True, "local_source_reference_requires_resolution"
    if "prior_step" in types:
        return True, "prior_step_reference_requires_resolution"
    return True, "downstream_unresolved_reference"


def resolve_continuation_candidates(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    observation: Dict[str, Any],
) -> List[Dict[str, Any]]:
    try:
        return _resolve_continuation_candidates(workflow, completed_step, observation)
    except Exception as exc:
        return _safe_error_resolution(workflow, completed_step, observation, str(exc))


def _resolve_continuation_candidates(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    observation: Dict[str, Any],
) -> List[Dict[str, Any]]:
    candidates = observation.get("resolver_candidates") or []
    if not candidates:
        return []
    return [_resolve_candidate(completed_step, c) for c in candidates]


def _resolve_candidate(
    completed_step: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    reference_text = candidate.get("reference_text", "")
    source_step_id = candidate.get("source_step_id")
    target_step_id = candidate.get("target_step_id")
    file_path = _resolve_source_file_path(completed_step, candidate)

    if not file_path:
        return _make_resolution_result(
            source_step_id,
            target_step_id,
            reference_text,
            None,
            "unresolved",
            None,
            None,
            "source_file_not_identified",
        )

    resolver_input = _build_resolver_input(candidate, file_path)
    if not resolver_input:
        return _make_resolution_result(
            source_step_id,
            target_step_id,
            reference_text,
            {"file_path": file_path, "reference_text": reference_text},
            "unsupported",
            None,
            None,
            "unsupported_reference_type",
        )

    resolver_result = _run_table_resolver(resolver_input)
    if resolver_result is None:
        return _make_resolution_result(
            source_step_id,
            target_step_id,
            reference_text,
            resolver_input,
            "unresolved",
            None,
            None,
            "resolver_unavailable",
        )

    if resolver_result.get("status") != "success":
        return _make_resolution_result(
            source_step_id,
            target_step_id,
            reference_text,
            resolver_input,
            "unresolved",
            None,
            resolver_result.get("data_ref"),
            resolver_result.get("error_code") or "resolver_error",
        )

    ref_type = resolver_input.get("reference_type")
    value = resolver_result.get("value")
    if ref_type == "row":
        value = resolver_result.get("row")
    elif ref_type == "entity_from_row":
        value = resolver_result.get("value") or resolver_result.get("entity")

    return _make_resolution_result(
        source_step_id,
        target_step_id,
        reference_text,
        resolver_input,
        "resolved",
        value,
        resolver_result.get("data_ref"),
        None,
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
) -> Dict[str, Any]:
    return {
        "f4_slice": "F4-B",
        "source_step_id": source_step_id,
        "target_step_id": target_step_id,
        "reference_text": reference_text,
        "resolver": "resolve_table_reference",
        "resolver_input": resolver_input,
        "status": status,
        "resolved_value": resolved_value,
        "data_ref": data_ref,
        "confidence": "deterministic",
        "ambiguity": "none" if status == "resolved" else "blocked_or_unsupported",
        "blocked_reason": blocked_reason,
    }


def _resolve_source_file_path(
    completed_step: Dict[str, Any],
    candidate: Dict[str, Any],
) -> Optional[str]:
    selected_tool = (
        (completed_step.get("_agent_metadata") or {}).get("selected_tool")
        or (completed_step.get("execution_result") or {}).get("tool_name")
    )
    if selected_tool not in ("read_csv", "read_spreadsheet"):
        return None

    file_path = candidate.get("suggested_file_path")
    if file_path:
        return file_path

    for target in completed_step.get("resource_targets") or []:
        if isinstance(target, str):
            match = _FILE_PATH_RE.search(target)
            if match:
                return match.group(0)

    for field in ("tool_call", "executed_input", "input", "purpose"):
        value = completed_step.get(field)
        if isinstance(value, str):
            match = _FILE_PATH_RE.search(value)
            if match:
                return match.group(0)

    execution_result = completed_step.get("execution_result") or {}
    if isinstance(execution_result, dict):
        result = execution_result.get("result")
        if isinstance(result, str):
            match = _FILE_PATH_RE.search(result)
            if match:
                return match.group(0)
        if isinstance(result, dict):
            for key in ("file_path", "path", "filename"):
                if isinstance(result.get(key), str):
                    return result[key]

    return None


def _build_resolver_input(
    candidate: Dict[str, Any],
    file_path: str,
) -> Optional[Dict[str, Any]]:
    ref_type = candidate.get("suggested_reference_type")
    if ref_type == "entity_from_row":
        return {
            "file_path": file_path,
            "reference_type": "entity_from_row",
            "row_number": candidate.get("suggested_row_number"),
            "entity_column": candidate.get("suggested_entity_column") or "__AUTO_NAME_LIKE__",
        }
    if ref_type == "row":
        return {
            "file_path": file_path,
            "reference_type": "row",
            "row_number": candidate.get("suggested_row_number"),
        }
    if ref_type == "cell":
        return {
            "file_path": file_path,
            "reference_type": "cell",
            "cell_address": candidate.get("suggested_cell_reference"),
        }
    if ref_type == "header":
        ordinal = candidate.get("suggested_header_ordinal")
        if not isinstance(ordinal, int) or ordinal < 1:
            return None
        return {
            "file_path": file_path,
            "reference_type": "cell",
            "cell_address": f"{_column_letter(ordinal)}1",
        }
    if ref_type == "column_value":
        return {
            "file_path": file_path,
            "reference_type": "entity_from_row",
            "row_number": candidate.get("suggested_row_number"),
            "entity_column": candidate.get("suggested_entity_column") or "__AUTO_NAME_LIKE__",
        }
    return None


def _run_table_resolver(resolver_input: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if _table_resolver is None:
        return None
    try:
        return _table_resolver.run(**resolver_input)
    except Exception:
        return None


def _column_letter(n: int) -> str:
    letters = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        letters = chr(65 + r) + letters
    return letters


def _safe_error_resolution(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    observation: Dict[str, Any],
    error_message: str,
) -> List[Dict[str, Any]]:
    workflow_id = workflow.get("id", "unknown_workflow")
    completed_step_id = completed_step.get("id", "unknown_step")
    return [
        {
            "f4_slice": "F4-B",
            "source_step_id": completed_step_id,
            "target_step_id": None,
            "reference_text": None,
            "resolver": "resolve_table_reference",
            "resolver_input": None,
            "status": "unresolved",
            "resolved_value": None,
            "data_ref": None,
            "confidence": "deterministic",
            "ambiguity": "blocked_or_unsupported",
            "blocked_reason": f"resolver_driver_error: {error_message}",
            "metadata": {
                "workflow_id": workflow_id,
                "observation_type": observation.get("observation_type"),
            },
        }
    ]


# =============================================================================
# F4-C — RESOLVED-VALUE CONTINUATION / SAFE DOWNSTREAM STEP REWRITE
# =============================================================================

# Trailing dependency phrases that become stale after the local reference is
# replaced by a concrete value. These are removed only when adjacent to the
# rewritten value, so unrelated text is never mutated.
_DEPENDENCY_PHRASES = [
    r"\s+of\s+the\s+csv\s+file\s+read\s+by\s+step[_\s]?\w+",
    r"\s+of\s+the\s+CSV\s+read\s+by\s+step[_\s]?\w+",
    r"\s+from\s+step[_\s]?\w+",
    r"\s+using\s+(?:the\s+)?result\s+of\s+step[_\s]?\w+",
    r"\s+read\s+by\s+step[_\s]?\w+",
]


# Status values that make a downstream step unsafe to rewrite.
_UNSAFE_STEP_STATUSES = frozenset(("COMPLETED", "FAILED", "ACTIVE", "CANCELLED"))


def apply_resolved_continuations(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    resolutions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Public F4-C entry point.

    Consumes F4-B deterministic resolutions and safely rewrites pending
    downstream step purpose/input to use concrete resolved values. This is
    planning-control metadata mutation only; no step is executed, no
    lifecycle/governance change occurs, and no external tool is invoked.

    Failure-isolated: any unexpected error returns a single blocked application
    record and never propagates an exception to the runtime loop.
    """
    try:
        return _apply_resolved_continuations(workflow, completed_step, resolutions)
    except Exception as exc:
        return _safe_error_application(workflow, completed_step, resolutions, str(exc))


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
        application = _try_apply_resolution(
            steps,
            resolution,
            current_plan_version,
        )
        if application is not None:
            applications.append(application)
    return applications


def _try_apply_resolution(
    steps: List[Dict[str, Any]],
    resolution: Dict[str, Any],
    current_plan_version: Any,
) -> Optional[Dict[str, Any]]:
    """Validate and apply a single F4-B resolution to its target step."""
    # Resolution must be resolved, deterministic, and unambiguous.
    if resolution.get("status") != "resolved":
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "resolution_not_resolved",
        )

    if resolution.get("confidence") != "deterministic":
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "resolution_not_deterministic",
        )

    ambiguity = resolution.get("ambiguity")
    if ambiguity and str(ambiguity).lower() not in ("none", "", "null"):
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "resolution_ambiguous",
        )

    resolved_value = resolution.get("resolved_value")
    if not resolved_value:
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "resolved_value_empty",
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

    # Prevent double-application of the same continuation.
    if target_step.get("_continuation_applied"):
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "already_continued",
        )

    old_purpose = target_step.get("purpose") or target_step.get("input") or ""
    if not old_purpose:
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "target_step_purpose_empty",
        )

    if not _purpose_contains_reference(old_purpose, resolution):
        return _make_application_record(
            resolution, None, None,
            current_plan_version, current_plan_version,
            "skipped", "reference_text_not_present",
        )

    new_purpose = _rewrite_purpose(old_purpose, resolution)
    if not new_purpose or new_purpose == old_purpose:
        return _make_application_record(
            resolution, old_purpose, None,
            current_plan_version, current_plan_version,
            "skipped", "rewrite_failed_or_unchanged",
        )

    # Apply the safe rewrite.
    target_step["purpose"] = new_purpose
    if "input" in target_step:
        target_step["input"] = new_purpose

    # Remove stale tool-selection artifacts so the next dispatch reclassifies
    # the step with the new concrete purpose/profile.
    target_step["tool_call"] = None
    target_step["executed_input"] = None
    _agent_metadata = target_step.get("_agent_metadata")
    if isinstance(_agent_metadata, dict):
        _agent_metadata["selected_tool"] = None
        _agent_metadata["selected_agent_type"] = None
        _agent_metadata["selected_agent"] = None

    # Reclassify step profile for the rewritten concrete purpose.
    _reclassify_step_profile(target_step)

    # Record continuation markers on the step itself.
    target_step["_continuation_applied"] = True
    target_step["_continuation_source_step_id"] = resolution.get("source_step_id")
    target_step["_continuation_resolved_value"] = resolved_value
    target_step["_continuation_reference_text"] = resolution.get("reference_text")

    return _make_application_record(
        resolution, old_purpose, new_purpose,
        current_plan_version, current_plan_version,
        "applied", None,
    )


def _purpose_contains_reference(purpose: str, resolution: Dict[str, Any]) -> bool:
    """Return True if the purpose still contains the resolution's reference."""
    reference_text = resolution.get("reference_text")
    if reference_text and reference_text in purpose:
        return True

    # Also recognize common row/person/name variants derived from the row number.
    resolver_input = resolution.get("resolver_input") or {}
    row_number = resolver_input.get("row_number")
    if row_number is not None:
        patterns = [
            rf"(?:the\s+)?(?:person|name)\s+(?:in|from)\s+row\s+{row_number}",
            rf"row\s+{row_number}\s+(?:person|name)",
        ]
        for pat in patterns:
            if re.search(pat, purpose, re.IGNORECASE):
                return True
    return False


def _rewrite_purpose(old_purpose: str, resolution: Dict[str, Any]) -> str:
    """Replace the local reference with the concrete resolved value and drop stale dependency phrases."""
    reference_text = resolution.get("reference_text") or ""
    resolved_value = resolution.get("resolved_value") or ""
    new_purpose = old_purpose

    if reference_text:
        # Match an optional leading "the " so "the person in row 4" becomes
        # just "Cara", not "the Cara".
        pattern = r"(?<!\w)(?:the\s+)?" + re.escape(reference_text) + r"(?!\w)"
        new_purpose = re.sub(pattern, resolved_value, new_purpose, count=1, flags=re.IGNORECASE)

        # If the literal reference was not present, try canonical row/person/name
        # variants derived from the resolved row number.
        if new_purpose == old_purpose:
            row_number = (resolution.get("resolver_input") or {}).get("row_number")
            if row_number is not None:
                variant_patterns = [
                    rf"(?:the\s+)?(?:person|name)\s+(?:in|from)\s+row\s+{row_number}",
                    rf"row\s+{row_number}\s+(?:person|name)",
                ]
                for pat in variant_patterns:
                    new_purpose = re.sub(
                        pat, resolved_value, new_purpose, count=1, flags=re.IGNORECASE
                    )
                    if new_purpose != old_purpose:
                        break

    # Remove stale trailing dependency phrases.
    for phrase in _DEPENDENCY_PHRASES:
        new_purpose = re.sub(phrase, "", new_purpose, flags=re.IGNORECASE, count=1)

    # Normalize whitespace.
    new_purpose = re.sub(r"\s{2,}", " ", new_purpose).strip()
    return new_purpose


def _reclassify_step_profile(step: Dict[str, Any]) -> None:
    """
    Re-run the deterministic step-profile classifier on the rewritten step.
    Only sets _step_profile when the rewritten purpose is concrete enough to
    receive a narrow profile; otherwise leaves it unset so the workflow-level
    profile remains in effect.
    """
    try:
        from system.orchestrator.step_profile_resolver import _classify_step_profile

        profile_result = _classify_step_profile(step)
        if profile_result:
            step["_step_profile"] = profile_result[0]
            step["_step_profile_reason_code"] = profile_result[1]
            step["_step_profile_source"] = "f4c_step_profile_reclassify"
        else:
            step["_step_profile"] = None
            step.pop("_step_profile_reason_code", None)
            step.pop("_step_profile_source", None)
    except Exception:
        # Step profile reclassification is advisory; failure is not blocking.
        pass


def _make_application_record(
    resolution: Dict[str, Any],
    old_purpose: Optional[str],
    new_purpose: Optional[str],
    plan_version_before: Any,
    plan_version_after: Any,
    status: str,
    blocked_reason: Optional[str],
) -> Dict[str, Any]:
    return {
        "f4_slice": "F4-C",
        "source_step_id": resolution.get("source_step_id"),
        "target_step_id": resolution.get("target_step_id"),
        "resolution_ref": {
            "resolver": resolution.get("resolver"),
            "reference_text": resolution.get("reference_text"),
            "resolved_value": resolution.get("resolved_value"),
        },
        "status": status,
        "old_purpose": old_purpose,
        "new_purpose": new_purpose,
        "plan_version_before": plan_version_before,
        "plan_version_after": plan_version_after,
        "authority": "planning_continuation",
        "confidence": resolution.get("confidence"),
        "blocked_reason": blocked_reason,
    }


def _safe_error_application(
    workflow: Dict[str, Any],
    completed_step: Dict[str, Any],
    resolutions: List[Dict[str, Any]],
    error_message: str,
) -> List[Dict[str, Any]]:
    """Failure-isolated fallback when the continuation driver itself errors."""
    workflow_id = workflow.get("id", "unknown_workflow")
    completed_step_id = completed_step.get("id", "unknown_step") if completed_step else None
    return [
        {
            "f4_slice": "F4-C",
            "source_step_id": completed_step_id,
            "target_step_id": None,
            "resolution_ref": None,
            "status": "error",
            "old_purpose": None,
            "new_purpose": None,
            "plan_version_before": workflow.get("plan_version"),
            "plan_version_after": workflow.get("plan_version"),
            "authority": "planning_continuation",
            "confidence": None,
            "blocked_reason": f"continuation_driver_error: {error_message}",
            "metadata": {
                "workflow_id": workflow_id,
                "resolution_count": len(resolutions or []),
            },
        }
    ]
