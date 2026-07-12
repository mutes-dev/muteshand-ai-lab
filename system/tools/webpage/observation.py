"""
Pure helper for building bounded read_webpage observations.

No network side effects. No lifecycle or governance authority.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


OBSERVATION_TYPE = "read_webpage"
EVIDENCE_STATUS = "observation_only"
MAX_URL_LEN = 2048
MAX_TITLE_LEN = 200
MAX_REASON_LEN = 200
MAX_DETAIL_LEN = 500
MAX_LIMITATIONS = 5
MAX_LIMITATION_LEN = 200
TRUNCATION_LIMIT = 5000


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


def _build_limitations(
    truncated: bool,
    failure_reason: Optional[str],
    detail: Optional[str],
) -> List[str]:
    limitations: List[str] = []
    if truncated:
        limitations.append(
            f"extracted content truncated to {TRUNCATION_LIMIT} characters"
        )
    if failure_reason:
        limitations.append(
            f"fetch failed: {_truncate(failure_reason, MAX_LIMITATION_LEN - 12)}"
        )
    if detail:
        limitations.append(
            f"detail: {_truncate(detail, MAX_LIMITATION_LEN - 8)}"
        )
    if not limitations:
        limitations.append("no source-quality classification")
        limitations.append("no grounding validation")
    return limitations[:MAX_LIMITATIONS]


def build_read_webpage_observation(
    requested_url: str,
    status: str,
    result_text: str = "",
    title: Optional[str] = None,
    final_url: Optional[str] = None,
    content_length: Optional[int] = None,
    extracted_length: Optional[int] = None,
    failure_reason: Optional[str] = None,
    detail: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a bounded read_webpage observation.

    Args:
        requested_url: The URL supplied to read_webpage.
        status: "success" or "failure".
        result_text: The user-facing text returned (empty on failure).
        title: Extracted page title, if any.
        final_url: Final URL if safely known; otherwise None or requested_url.
        content_length: Raw/extracted content length if available.
        extracted_length: Length of the returned result text.
        failure_reason: Short reason code on failure.
        detail: Optional detail string.

    Returns:
        Stage A observation dictionary.
    """
    stored_url = _truncate(requested_url or "", MAX_URL_LEN)
    stored_final = _truncate(final_url, MAX_URL_LEN) if final_url else None
    stored_title = _truncate(title, MAX_TITLE_LEN) if title else None

    if extracted_length is None:
        extracted_length = len(result_text) if result_text else 0

    truncated = False
    if status == "success" and extracted_length > TRUNCATION_LIMIT:
        truncated = True

    observation: Dict[str, Any] = {
        "observation_id": f"obs_{uuid.uuid4()}",
        "observation_type": OBSERVATION_TYPE,
        "evidence_status": EVIDENCE_STATUS,
        "tool_name": "read_webpage",
        "requested_url": stored_url,
        "final_url": stored_final,
        "source_domain": _hostname_from_url(stored_url),
        "title": stored_title,
        "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "content_length": content_length,
        "extracted_length": extracted_length,
        "truncated": truncated,
        "truncation_limit": TRUNCATION_LIMIT,
        "status": status,
        "failure_reason": _truncate(failure_reason, MAX_REASON_LEN) if failure_reason else None,
        "limitations": _build_limitations(truncated, failure_reason, detail),
        "privacy_classification": "external_url_fetch",
    }

    return observation
