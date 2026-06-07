"""
Search provider implementations.

Odysseus search modules used as provider-abstraction reference only;
no Odysseus runtime or search code was copied.
"""

from __future__ import annotations

import os
import sys
from typing import List

from .core import SearchProvider, SearchResult

# Import URL validator (relative import from system root)
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
from system.security.url_validator import validate_url


class DuckDuckGoProvider(SearchProvider):
    """DuckDuckGo HTML scraping provider."""

    name = "duckduckgo"
    _ENDPOINT = "https://html.duckduckgo.com/html/"

    def search(self, query: str, max_results: int = 5) -> dict:
        import requests
        from bs4 import BeautifulSoup

        # Validate endpoint URL
        validation = validate_url(self._ENDPOINT)
        if validation.get("status") == "failure":
            return {
                "status": "failure",
                "reason": "url_safety_blocked",
                "detail": validation.get("detail", "DuckDuckGo endpoint blocked"),
            }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        params = {"q": query}

        try:
            response = requests.post(
                self._ENDPOINT, data=params, headers=headers, timeout=15
            )
            response.raise_for_status()
        except requests.exceptions.Timeout:
            return {
                "status": "failure",
                "reason": "search_provider_timeout",
                "detail": "DuckDuckGo request timed out",
            }
        except requests.exceptions.RequestException as exc:
            return {
                "status": "failure",
                "reason": "search_provider_unavailable",
                "detail": f"DuckDuckGo request failed: {exc}",
            }

        # Parse HTML
        soup = BeautifulSoup(response.text, "html.parser")
        result_divs = soup.find_all("div", class_="result")

        results: List[SearchResult] = []
        for div in result_divs[:max_results]:
            title_link = div.find("a", class_="result__a")
            if not title_link:
                continue

            title = title_link.get_text(strip=True)
            href = title_link.get("href", "")

            snippet_elem = div.find("a", class_="result__snippet")
            if not snippet_elem:
                snippet_elem = div.find("div", class_="result__snippet")

            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

            if title and href:
                results.append(SearchResult(title=title, url=href, snippet=snippet))

        if not results:
            return {
                "status": "failure",
                "reason": "search_no_results",
                "detail": "no results found from DuckDuckGo",
            }

        return {
            "status": "success",
            "results": results,
        }


class SearXNGProvider(SearchProvider):
    """SearXNG JSON API provider. Configured via SEARXNG_BASE_URL environment variable."""

    name = "searxng"

    def is_configured(self) -> bool:
        return bool(os.environ.get("SEARXNG_BASE_URL", "").strip())

    def _base_url(self) -> str:
        url = os.environ.get("SEARXNG_BASE_URL", "").strip()
        # Ensure trailing slash for join safety
        if url and not url.endswith("/"):
            url += "/"
        return url

    def search(self, query: str, max_results: int = 5) -> dict:
        import requests

        base = self._base_url()
        if not base:
            return {
                "status": "failure",
                "reason": "search_no_provider_configured",
                "detail": "SEARXNG_BASE_URL environment variable is not set",
            }

        search_url = f"{base}search"
        validation = validate_url(search_url)
        if validation.get("status") == "failure":
            return {
                "status": "failure",
                "reason": "url_safety_blocked",
                "detail": validation.get("detail", "SearXNG endpoint blocked"),
            }

        params = {
            "q": query,
            "format": "json",
            "safesearch": 1,
        }

        try:
            response = requests.get(search_url, params=params, timeout=15)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            return {
                "status": "failure",
                "reason": "search_provider_timeout",
                "detail": "SearXNG request timed out",
            }
        except requests.exceptions.RequestException as exc:
            return {
                "status": "failure",
                "reason": "search_provider_unavailable",
                "detail": f"SearXNG request failed: {exc}",
            }

        try:
            data = response.json()
        except Exception as exc:
            return {
                "status": "failure",
                "reason": "search_parse_error",
                "detail": f"could not parse SearXNG response: {exc}",
            }

        raw_results = data.get("results", []) if isinstance(data, dict) else []
        results: List[SearchResult] = []
        for item in raw_results[:max_results]:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "")
            url = item.get("url", "")
            snippet = item.get("content", "")
            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet))

        if not results:
            return {
                "status": "failure",
                "reason": "search_no_results",
                "detail": "no results found from SearXNG",
            }

        return {
            "status": "success",
            "results": results,
        }
