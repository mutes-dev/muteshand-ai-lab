"""Web Read Capability — Deterministic explicit-URL webpage-read compiler.

Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 10B:
- High-confidence explicit-URL read/show/summarize/explain detection only
- No LLM. No system_entry import. No execution.
- Emits explicit candidate workflow/DAG with depends_on.
- Fallback for ambiguous, mutation, mixed-domain, search, multi-source, unsupported final actions.

Supported deterministic DAG shapes:
- read_webpage -> finalize_output  (present mode)
- read_webpage -> finalize_output  (summarize/explain/extract_key_points mode)
- No web_search, no multi-source, no autonomous browsing.
"""

import re
from typing import Any


# === Web-search / autonomous browsing detection — conservative fallback ===
_WEB_SEARCH_KEYWORDS = frozenset([
    "search the web", "search web", "web search", "search online",
    "find online", "find on the web", "look up", "lookup", "google",
    "search then", "search and read", "search and open", "search first",
    "look online", "search for", "query the web", "bing", "duckduckgo",
    "searx", "search results", "first result", "top result",
])

# === Mutation / save / download detection — conservative fallback ===
_MUTATION_KEYWORDS = frozenset([
    "write", "edit", "append", "delete", "remove", "save", "download",
    "update", "modify", "overwrite", "replace", "create file",
])

# === Mixed-domain detection — conservative fallback keywords ===
# Avoid bare "file" because it appears in URLs (e.g. /file.txt).
_MIXED_DOMAIN_KEYWORDS = frozenset([
    "local file", "read file", "read the file", "list files", "list the files",
    "folder", "directory", "email", "calendar", "schedule", "api call",
    "run python", "shell", "execute code", "arithmetic", "add ", "plus ",
    "subtract ", "minus ", "multiply ", "divide ", "calculate", "compute",
    "square root", "factorial", "fibonacci", "and add", "and subtract",
    "and multiply", "and divide", "then add", "then subtract", "then multiply",
    "then divide",
])

# === Explicit read intent verbs ===
_READ_INTENT_VERBS = re.compile(
    r"(?:read|show|open|display|view|fetch|get)",
    re.IGNORECASE,
)

# === Supported transform actions ===
_TRANSFORM_URL_ACTIONS = {
    "summarize": re.compile(
        r"\b(?:summarize|summarise|summary\s+of|give\s+me\s+a\s+summary\s+of)\b",
        re.IGNORECASE,
    ),
    "explain": re.compile(
        r"\b(?:explain|explain\s+what\s+is\s+on)\b",
        re.IGNORECASE,
    ),
    "extract_key_points": re.compile(
        r"\b(?:extract\s+key\s+points\s+from)\b",
        re.IGNORECASE,
    ),
}

# === Unsupported final action detection ===
# compare/analyze/fact-check remain deferred; summarize/explain/extract are now supported.
_UNSUPPORTED_FINAL_ACTION_RE = re.compile(
    r"\b(?:compare|comparison\s+of|analyze|analyse|analysis\s+of|fact-check|fact\s+check)\b",
    re.IGNORECASE,
)

# === URL extraction — literal preservation ===
# Captures http:// or https:// URLs, stopping at whitespace or quote.
_URL_RE = re.compile(r'https?://[^\s"\'<>]+', re.IGNORECASE)

# === Quoted URL extraction (alternative, fallback) ===
# Captures a URL inside matching double or single quotes.
_QUOTED_URL_RE = re.compile(
    r'["\'](https?://[^"\'\s<>]+)["\']',
    re.IGNORECASE,
)

# === URL structural validation ===
_URL_STRUCTURAL_RE = re.compile(
    r'^https?://[^/\s"\'<>]+(/.*)?$',
    re.IGNORECASE,
)

# === Local file path detection for mixed-domain fallback ===
# Matches path-like tokens with an extension and a directory separator or Windows drive.
_LOCAL_FILE_PATH_RE = re.compile(
    r'([a-zA-Z0-9_./\\~:-]+\.[a-zA-Z0-9]{1,10})',
    re.IGNORECASE,
)

# === Vague/ambiguous fallback patterns ===
_AMBIGUOUS_WEB_REFERENCES = frozenset([
    "that page", "that website", "that site", "that article",
    "the page", "the website", "the site", "the article",
    "this page", "this website", "this site", "this article",
    "a page", "a website", "a site", "an article",
])

# === Web-prompt heuristic for router fallback reason codes ===
_WEB_PROMPT_TOKENS = frozenset([
    "http", "https", "webpage", "web page", "website", "web site", "url",
    "site", "page", "article", "web", "internet", "online",
    "browse", "browser", "fetch", "summarize the webpage", "read the webpage",
    "read the website", "read the page", "read the url", "show the webpage",
    "open the webpage", "display the webpage", "view the webpage",
    "search the web", "search web", "web search", "search online",
    "find online", "find on the web", "look up", "lookup", "google",
    "search then", "search and read", "search and open", "search first",
    "search results", "first result", "top result", "query the web",
    "bing", "duckduckgo", "searx",
])


def _has_web_search_intent(text: str) -> bool:
    """Return True if prompt asks for web search or search-then-read."""
    lower = text.lower()
    return any(kw in lower for kw in _WEB_SEARCH_KEYWORDS)


def _has_mutation_intent(text: str) -> bool:
    """Return True if prompt asks for mutation/save/download."""
    lower = text.lower()
    return any(kw in lower for kw in _MUTATION_KEYWORDS)


def _has_local_file_path(text: str) -> bool:
    """Return True if prompt contains a local file path outside of any URL."""
    # Remove URLs so that /path/to/file.txt inside a URL is not counted as local.
    text_without_urls = _URL_RE.sub("", text)
    for match in _LOCAL_FILE_PATH_RE.finditer(text_without_urls):
        path = match.group(1)
        # Must have a directory separator or Windows drive letter to be a local path.
        if "/" in path or "\\" in path or ":" in path or "~" in path:
            return True
    return False


def _is_mixed_domain(text: str) -> bool:
    """Return True if prompt mixes web with other domains."""
    lower = text.lower()
    if any(kw in lower for kw in _MIXED_DOMAIN_KEYWORDS):
        return True
    if _has_local_file_path(text):
        return True
    return False


def _is_ambiguous_web_reference(text: str) -> bool:
    """Return True if prompt contains vague web reference with no explicit URL."""
    lower = text.lower()
    has_ambiguous = any(kw in lower for kw in _AMBIGUOUS_WEB_REFERENCES)
    if not has_ambiguous:
        return False
    return not _extract_url_literal(text)


def _extract_url_literal(text: str) -> str | None:
    """Extract the first explicit http(s) URL, preserving exact literal.

    - Strips only surrounding matching quotes that are not part of the URL.
    - Does not rewrite, normalize, encode, decode, or otherwise clean the URL.
    - Returns None if no valid URL found.
    """
    # Find all URLs matching the literal pattern.
    matches = _URL_RE.findall(text)
    if not matches:
        return None

    # First-slice: only single URL allowed.
    if len(matches) > 1:
        return None

    url = matches[0]

    # Strip surrounding matching quotes if the URL was quoted.
    for quote in ('"', "'"):
        if text.find(f"{quote}{url}{quote}") != -1:
            # If the URL itself ends with a quote character, the quote is part
            # of the URL and must not be stripped.
            if not url.endswith(quote):
                break

    # Structural validation: must have a host after the scheme.
    if not _URL_STRUCTURAL_RE.match(url):
        return None

    return url


def _has_read_intent_verb(text: str) -> bool:
    return bool(_READ_INTENT_VERBS.search(text))


def _has_unsupported_final_action(text: str) -> bool:
    return bool(_UNSUPPORTED_FINAL_ACTION_RE.search(text))


def _unsupported_final_action_reason(text: str) -> str:
    return "fallback_unsupported_final_action"


def _detect_transform_url_action(text: str) -> str | None:
    """Return supported transform action (summarize/explain/extract_key_points) if present."""
    for action, pattern in _TRANSFORM_URL_ACTIONS.items():
        if pattern.search(text):
            return action
    return None


def _build_read_webpage_workflow(user_input: str, url: str) -> dict:
    """Build a read_webpage -> finalize_output candidate workflow."""
    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "Read webpage",
        "purpose": f"Read the webpage at {url}",
        "expected_outcome": "Webpage content retrieved",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "web_read",
        "depends_on": [],
        "capability_metadata": {
            "capability_id": "web_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_explicit_url_read",
            "allowed_tool_family": "web_read",
            "allowed_tool": "read_webpage",
        },
        # Do not prepopulate tool_call: read_webpage has route_prepopulation_allowed=false.
        # URL literal is preserved in the purpose and will be resolved by AG1.
    }

    step_2 = {
        "id": "step_2",
        "type": "EXECUTE_API",
        "name": "Present webpage contents",
        "purpose": "Present the webpage contents from step_1",
        "expected_outcome": "Result shown",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "web_read",
        "depends_on": ["step_1"],
        "capability_metadata": {
            "capability_id": "web_read",
            "route_confidence": 1.0,
            "route_reason_code": "accepted_explicit_url_read",
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": "present",
            "intent_mode": "present",
            "transform_required": False,
        },
    }

    return {
        "id": None,
        "name": "web_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1, step_2],
        "approval_required": False,
    }


def _build_transform_webpage_workflow(
    user_input: str,
    url: str,
    final_action: str,
    intent_mode: str,
    purpose_template: str,
) -> dict:
    """Build a read_webpage -> finalize_output candidate workflow for a transform final action."""
    route_reason_code = f"accepted_explicit_url_{final_action}"
    step_1 = {
        "id": "step_1",
        "type": "EXECUTE_API",
        "name": "Read webpage",
        "purpose": f"Read the webpage at {url}",
        "expected_outcome": "Webpage content retrieved",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "web_read",
        "depends_on": [],
        "capability_metadata": {
            "capability_id": "web_read",
            "route_confidence": 1.0,
            "route_reason_code": route_reason_code,
            "allowed_tool_family": "web_read",
            "allowed_tool": "read_webpage",
        },
    }

    step_2 = {
        "id": "step_2",
        "type": "EXECUTE_API",
        "name": f"{final_action.replace('_', ' ').title()} webpage contents",
        "purpose": purpose_template,
        "expected_outcome": "Result shown",
        "risk": "LOW",
        "importance": "LOW",
        "resource_targets": [],
        "agent": "web_read",
        "depends_on": ["step_1"],
        "capability_metadata": {
            "capability_id": "web_read",
            "route_confidence": 1.0,
            "route_reason_code": route_reason_code,
            "allowed_tool_family": "text_finalization",
            "allowed_tool": "finalize_output",
            "final_action": final_action,
            "intent_mode": intent_mode,
            "transform_required": True,
        },
    }

    return {
        "id": None,
        "name": "web_read_workflow",
        "status": "QUEUED",
        "goal": user_input,
        "steps": [step_1, step_2],
        "approval_required": False,
    }


def is_web_prompt(user_input: str) -> bool:
    """Return True if prompt is plausibly web-related (for router fallback labeling)."""
    if not user_input or not isinstance(user_input, str):
        return False
    lower = user_input.lower()
    if _URL_RE.search(lower):
        return True
    return any(kw in lower for kw in _WEB_PROMPT_TOKENS)


def detect_web_read_fallback_reason(user_input: str) -> str:
    """Return a specific fallback reason code for a non-routed web prompt.

    This is advisory metadata only; the route decision remains the authority.
    """
    if not user_input or not isinstance(user_input, str):
        return "fallback_missing_explicit_url"

    if _has_web_search_intent(user_input):
        return "fallback_web_search_requested"

    if _has_mutation_intent(user_input):
        return "fallback_unsupported_operation"

    if _is_ambiguous_web_reference(user_input):
        return "fallback_ambiguous_web_reference"

    if _is_mixed_domain(user_input):
        return "fallback_mixed_domain"

    if _has_unsupported_final_action(user_input):
        return _unsupported_final_action_reason(user_input)

    if not _extract_url_literal(user_input):
        return "fallback_missing_explicit_url"

    return "fallback_unsupported_operation"


def compile_web_read_workflow(user_input: str, route_metadata: dict | None = None) -> dict | None:
    """
    Compile a high-confidence explicit-URL webpage-read prompt into a candidate workflow.

    Returns workflow dict compatible with validate_workflow,
    or None if prompt should fall back to planner.

    Per AGENT_CAPABILITY_ROUTING_CONTRACT_V1 Section 10B:
    - No LLM calls
    - No system_entry import
    - Explicit DAG emission with depends_on
    - Exact URL literal preservation
    """
    if not user_input or not isinstance(user_input, str):
        return None

    # === FAIL-SAFE CHECKS ===
    if _has_web_search_intent(user_input):
        return None
    if _has_mutation_intent(user_input):
        return None
    if _is_mixed_domain(user_input):
        return None
    if _is_ambiguous_web_reference(user_input):
        return None
    if _has_unsupported_final_action(user_input):
        return None

    # === Detect final action (present or transform) ===
    final_action = _detect_transform_url_action(user_input)
    if not final_action and not _has_read_intent_verb(user_input):
        return None
    if not final_action:
        final_action = "present"

    # === Extract and validate single URL ===
    url = _extract_url_literal(user_input)
    if not url:
        return None

    purpose_templates = {
        "present": "Present the webpage contents from step_1",
        "summarize": "Summarize the webpage contents from step_1",
        "explain": "Explain the webpage contents from step_1",
        "extract_key_points": "Extract key points from the webpage contents from step_1",
    }

    if final_action == "present":
        return _build_read_webpage_workflow(user_input, url)

    return _build_transform_webpage_workflow(
        user_input, url, final_action, final_action, purpose_templates[final_action]
    )
