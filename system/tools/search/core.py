"""
Search provider abstraction core.

Odysseus search modules used as provider-abstraction reference only;
no Odysseus runtime or search code was copied.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SearchResult:
    """Normalized search result shape."""
    title: str
    url: str
    snippet: str


class SearchProvider(ABC):
    """Abstract base for search providers."""

    name: str = "abstract"

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> dict:
        """
        Execute a search query.

        Returns:
            {"status": "success", "results": [SearchResult, ...]}
          OR
            {"status": "failure", "reason": <str>, "detail": <str>}
        """


def _get_provider(name: Optional[str] = None) -> Optional[SearchProvider]:
    """Resolve a provider by name, or auto-select default."""
    from .providers import DuckDuckGoProvider, SearXNGProvider

    if name == "duckduckgo":
        return DuckDuckGoProvider()
    if name == "searxng":
        return SearXNGProvider()

    # Auto-select: prefer configured searxng if available, else duckduckgo
    searxng = SearXNGProvider()
    if searxng.is_configured():
        return searxng
    return DuckDuckGoProvider()


def _get_fallback(primary: SearchProvider) -> Optional[SearchProvider]:
    """Determine fallback provider given the primary."""
    from .providers import DuckDuckGoProvider, SearXNGProvider

    # If primary is searxng, fallback to duckduckgo
    if isinstance(primary, SearXNGProvider):
        return DuckDuckGoProvider()

    # If primary is duckduckgo, no built-in fallback unless searxng is configured
    searxng = SearXNGProvider()
    if searxng.is_configured():
        return searxng
    return None


def search(
    query: str,
    provider: Optional[str] = None,
    fallback: bool = True,
    max_results: int = 5,
) -> dict:
    """
    Execute a search with provider abstraction and optional fallback.

    Args:
        query: Search query string.
        provider: Provider name ("duckduckgo", "searxng", or None for auto).
        fallback: Whether to try fallback provider on primary failure.
        max_results: Maximum results to return.

    Returns:
        {
            "status": "success",
            "results": [SearchResult, ...],
            "provider": <str>,
            "fallback_used": <bool>,
        }
      OR
        {
            "status": "failure",
            "reason": <str>,
            "detail": <str>,
            "provider": <str>,
            "fallback_used": <bool>,
        }
    """
    if not query or not query.strip():
        return {
            "status": "failure",
            "reason": "empty_query",
            "detail": "search query is empty",
            "provider": provider or "auto",
            "fallback_used": False,
        }

    primary = _get_provider(provider)
    if primary is None:
        return {
            "status": "failure",
            "reason": "search_no_provider_configured",
            "detail": "No enabled search provider is available",
            "provider": provider or "auto",
            "fallback_used": False,
        }

    # Try primary provider
    result = primary.search(query.strip(), max_results=max_results)
    result["provider"] = primary.name
    result["fallback_used"] = False

    if result["status"] == "success":
        return result

    # Try fallback if enabled
    if fallback:
        fb = _get_fallback(primary)
        if fb is not None:
            fb_result = fb.search(query.strip(), max_results=max_results)
            fb_result["provider"] = fb.name
            fb_result["fallback_used"] = True
            if fb_result["status"] == "success":
                return fb_result
            # If fallback also fails, return primary failure with fallback metadata
            result["fallback_used"] = True
            result["fallback_provider"] = fb.name
            result["fallback_detail"] = fb_result.get("detail", fb_result.get("reason", "unknown"))

    return result
