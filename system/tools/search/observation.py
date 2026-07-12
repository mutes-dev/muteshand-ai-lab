"""
Pure helper for building bounded web_search observations.

No network side effects. No lifecycle or governance authority.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .core import SearchResult
from .providers import DuckDuckGoProvider, SearXNGProvider


OBSERVATION_TYPE = "web_search"
EVIDENCE_STATUS = "observation_only"
MAX_QUERY_LEN = 8192
MAX_RESULT_ENTRIES = 5
MAX_TITLE_LEN = 200
MAX_URL_LEN = 2048
MAX_SNIPPET_LEN = 1000
MAX_PROVIDER_REASON_LEN = 200
MAX_WARNINGS = 5
MAX_WARNING_LEN = 200
MAX_LIMITATIONS = 5
MAX_LIMITATION_LEN = 200

# Outcome vocabulary for web_search observations.
OUTCOME_RESULTS = "results"
OUTCOME_ZERO_RESULTS = "zero_results"
OUTCOME_EMPTY_QUERY = "empty_query"
OUTCOME_PROVIDER_UNAVAILABLE = "provider_unavailable"
OUTCOME_PROVIDER_FAILURE = "provider_failure"
OUTCOME_PROVIDER_EXCEPTION = "provider_exception"
OUTCOME_ENDPOINT_SAFETY_BLOCKED = "endpoint_safety_blocked"
OUTCOME_WRAPPER_IMPORT_FAILURE = "wrapper_import_failure"
OUTCOME_WRAPPER_EXCEPTION = "wrapper_exception"
OUTCOME_UNKNOWN = "unknown"

_REASON_TO_OUTCOME = {
    "empty_query": OUTCOME_EMPTY_QUERY,
    "search_no_provider_configured": OUTCOME_PROVIDER_UNAVAILABLE,
    "url_safety_blocked": OUTCOME_ENDPOINT_SAFETY_BLOCKED,
    "search_provider_timeout": OUTCOME_PROVIDER_UNAVAILABLE,
    "search_provider_unavailable": OUTCOME_PROVIDER_UNAVAILABLE,
    "search_parse_error": OUTCOME_PROVIDER_FAILURE,
    "search_no_results": OUTCOME_ZERO_RESULTS,
}


def _truncate(text: Any, max_len: int) -> str:
    if text is None:
        return ""
    text = str(text)
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _hostname_from_url(url: str) -> Optional[str]:
    try:
        from urllib.parse import urlparse

        parsed = urlparse(str(url))
        if parsed.hostname:
            return parsed.hostname.lower()
    except Exception:
        pass
    return None


def _provider_host(provider_name: Optional[str]) -> Optional[str]:
    if provider_name == "duckduckgo":
        return _hostname_from_url(DuckDuckGoProvider._ENDPOINT)
    if provider_name == "searxng":
        base = SearXNGProvider()._base_url()
        if base:
            return _hostname_from_url(base)
    return None


def _build_limitations(
    result_count: int,
    displayed_count: int,
    fallback_used: bool,
    provider_reason: str,
) -> List[str]:
    limitations: List[str] = []
    if result_count > displayed_count:
        limitations.append(
            f"only first {displayed_count} of {result_count} results displayed to user"
        )
    limitations.append("no source-quality classification")
    limitations.append("no grounding validation")
    if fallback_used:
        limitations.append("fallback provider was used")
    if provider_reason:
        limitations.append(f"provider reason: {_truncate(provider_reason, MAX_LIMITATION_LEN - 16)}")
    return limitations[:MAX_LIMITATIONS]


def _build_results(results: List[SearchResult]) -> List[Dict[str, Any]]:
    bounded: List[Dict[str, Any]] = []
    for i, item in enumerate(results[:MAX_RESULT_ENTRIES], start=1):
        bounded.append(
            {
                "rank": i,
                "title": _truncate(item.title, MAX_TITLE_LEN),
                "url": _truncate(item.url, MAX_URL_LEN),
                "snippet": _truncate(item.snippet, MAX_SNIPPET_LEN),
            }
        )
    return bounded


def build_web_search_observation(
    query: str,
    search_result: Dict[str, Any],
    displayed_count: int = 0,
) -> Dict[str, Any]:
    """
    Build a bounded raw web_search observation from the search() result dict.

    Args:
        query: The exact query sent to the provider.
        search_result: The dict returned by system.tools.search.core.search().
        displayed_count: Number of results included in the human-facing output.

    Returns:
        A dictionary conforming to the Stage A observation shape.
    """
    if not isinstance(search_result, dict):
        search_result = {}

    status = search_result.get("status")
    provider = search_result.get("provider") or "unknown"
    fallback_used = bool(search_result.get("fallback_used"))
    results: List[SearchResult] = search_result.get("results") or []
    if results and not all(isinstance(r, SearchResult) for r in results):
        results = []

    provider_reason = ""
    detail = ""
    if status == "failure":
        provider_reason = str(search_result.get("reason") or "")
        detail = str(search_result.get("detail") or "")

    outcome_kind = _REASON_TO_OUTCOME.get(provider_reason, OUTCOME_UNKNOWN)
    if status == "success" and results:
        outcome_kind = OUTCOME_RESULTS
    elif status == "success" and not results:
        outcome_kind = OUTCOME_ZERO_RESULTS

    query_truncated = False
    stored_query = query
    if query and len(query) > MAX_QUERY_LEN:
        stored_query = query[:MAX_QUERY_LEN]
        query_truncated = True

    result_count = len(results)
    displayed_count = min(displayed_count, result_count, MAX_RESULT_ENTRIES)

    observation: Dict[str, Any] = {
        "observation_id": f"obs_{uuid.uuid4()}",
        "observation_type": OBSERVATION_TYPE,
        "query": stored_query,
        "provider": provider,
        "provider_host": _provider_host(provider),
        "fallback_used": fallback_used,
        "outcome_kind": outcome_kind,
        "provider_reason": _truncate(provider_reason, MAX_PROVIDER_REASON_LEN),
        "result_count": result_count,
        "returned_result_count": displayed_count,
        "results": _build_results(results),
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "warnings": [],
        "limitations": _build_limitations(
            result_count, displayed_count, fallback_used, provider_reason
        ),
        "evidence_status": EVIDENCE_STATUS,
    }
    if query_truncated:
        observation["query_truncated"] = True

    return observation


def build_web_search_observation_for_failure(
    query: str,
    outcome_kind: str,
    provider: Optional[str] = None,
    provider_reason: Optional[str] = None,
    detail: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a bounded observation for cases where search() was not reached or failed early.

    Args:
        query: The query string (may be empty).
        outcome_kind: One of the bounded outcome vocabulary values.
        provider: Provider name, if known.
        provider_reason: Short provider reason code, if known.
        detail: Optional detail string (not persisted unbounded).

    Returns:
        A Stage A observation dictionary.
    """
    query_truncated = False
    stored_query = query or ""
    if stored_query and len(stored_query) > MAX_QUERY_LEN:
        stored_query = stored_query[:MAX_QUERY_LEN]
        query_truncated = True

    observation: Dict[str, Any] = {
        "observation_id": f"obs_{uuid.uuid4()}",
        "observation_type": OBSERVATION_TYPE,
        "query": stored_query,
        "provider": provider or "unknown",
        "provider_host": _provider_host(provider),
        "fallback_used": False,
        "outcome_kind": outcome_kind,
        "provider_reason": _truncate(provider_reason or "", MAX_PROVIDER_REASON_LEN),
        "result_count": 0,
        "returned_result_count": 0,
        "results": [],
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "warnings": [],
        "limitations": _build_limitations(0, 0, False, provider_reason or ""),
        "evidence_status": EVIDENCE_STATUS,
    }
    if query_truncated:
        observation["query_truncated"] = True

    return observation
