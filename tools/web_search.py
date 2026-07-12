INPUT_SPEC = {
    "query": "string"
}


def run(query):
    """
    Search the web using the AI Lab search provider abstraction.

    Returns real search results with titles, URLs, and snippets.
    Backward-compatible with the previous DuckDuckGo-only implementation.
    """
    import sys
    import os

    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

    try:
        from system.tools.search import search, build_web_search_observation, build_web_search_observation_for_failure
    except Exception:
        return _legacy_failure_envelope(query, outcome_kind="wrapper_import_failure")

    # Handle empty input
    if not query or not query.strip():
        observation = build_web_search_observation_for_failure(
            query or "",
            outcome_kind="empty_query",
        )
        return {
            "status": "success",
            "result": "no results found",
            "observation": observation,
        }

    try:
        result = search(query.strip(), provider=None, fallback=True, max_results=5)
    except Exception:
        return _legacy_failure_envelope(query, outcome_kind="wrapper_exception")

    # Preserve URL-safety-blocked dict shape (backward compatibility)
    if result.get("status") == "failure" and result.get("reason") == "url_safety_blocked":
        observation = build_web_search_observation(
            query.strip(),
            result,
            displayed_count=0,
        )
        return {
            "status": "failure",
            "reason": "url_safety_blocked",
            "detail": result.get("detail", "search endpoint blocked"),
            "observation": observation,
        }

    if result.get("status") != "success":
        observation = build_web_search_observation(
            query.strip(),
            result,
            displayed_count=0,
        )
        return {
            "status": "success",
            "result": "no results found",
            "observation": observation,
        }

    results = result.get("results", [])
    if not results:
        observation = build_web_search_observation(
            query.strip(),
            result,
            displayed_count=0,
        )
        return {
            "status": "success",
            "result": "no results found",
            "observation": observation,
        }

    # Format output identically to previous implementation
    output_lines = ["Top results:"]
    for i, item in enumerate(results[:3], 1):
        output_lines.append(f"\n{i}. {item.title} — {item.url}")
        if item.snippet:
            output_lines.append(f"   {item.snippet}")

    result_text = "\n".join(output_lines)
    observation = build_web_search_observation(
        query.strip(),
        result,
        displayed_count=min(len(results), 3),
    )
    return {
        "status": "success",
        "result": result_text,
        "observation": observation,
    }


def _legacy_failure_envelope(query, outcome_kind="wrapper_exception"):
    """Return the legacy 'no results found' envelope with a failure observation."""
    import sys
    import os

    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

    try:
        from system.tools.search import build_web_search_observation_for_failure
        observation = build_web_search_observation_for_failure(
            query or "",
            outcome_kind=outcome_kind,
        )
    except Exception:
        observation = None

    envelope = {
        "status": "success",
        "result": "no results found",
    }
    if isinstance(observation, dict):
        envelope["observation"] = observation
    return envelope