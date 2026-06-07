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

    # Handle empty input
    if not query or not query.strip():
        return "no results found"

    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

    try:
        from system.tools.search import search
    except Exception:
        return "no results found"

    try:
        result = search(query.strip(), provider=None, fallback=True, max_results=5)
    except Exception:
        return "no results found"

    # Preserve URL-safety-blocked dict shape (backward compatibility)
    if result.get("status") == "failure" and result.get("reason") == "url_safety_blocked":
        return {
            "status": "failure",
            "reason": "url_safety_blocked",
            "detail": result.get("detail", "search endpoint blocked"),
        }

    if result.get("status") != "success":
        return "no results found"

    results = result.get("results", [])
    if not results:
        return "no results found"

    # Format output identically to previous implementation
    output_lines = ["Top results:"]
    for i, item in enumerate(results[:3], 1):
        output_lines.append(f"\n{i}. {item.title} — {item.url}")
        if item.snippet:
            output_lines.append(f"   {item.snippet}")

    return "\n".join(output_lines)