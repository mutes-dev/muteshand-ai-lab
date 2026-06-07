"""
Search Provider Abstraction Tests (ADOPT-006)

Tests cover:
- Provider normalization and interface
- DuckDuckGo provider parsing and failure handling
- SearXNG provider (configured and not-configured)
- Core search() function with fallback logic
- web_search tool backward compatibility
- URL safety integration
- Plan mode integration
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from system.tools.search.core import search, SearchResult, SearchProvider
from system.tools.search.providers import DuckDuckGoProvider, SearXNGProvider


class TestProviderNormalization(unittest.TestCase):
    """Test SearchResult dataclass and provider interface."""

    def test_search_result_shape(self):
        sr = SearchResult(title="T", url="http://example.com", snippet="S")
        self.assertEqual(sr.title, "T")
        self.assertEqual(sr.url, "http://example.com")
        self.assertEqual(sr.snippet, "S")

    def test_provider_interface(self):
        class DummyProvider(SearchProvider):
            name = "dummy"

            def search(self, query, max_results=5):
                return {"status": "success", "results": [SearchResult(title="T", url="U", snippet="S")]}

        p = DummyProvider()
        result = p.search("test")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["results"]), 1)


class TestDuckDuckGoProvider(unittest.TestCase):
    """Test DuckDuckGo provider behavior with mocked HTTP."""

    _DDG_HTML = """
    <html>
      <div class="result">
        <a class="result__a" href="https://example.com/1">Title One</a>
        <a class="result__snippet">Snippet one text</a>
      </div>
      <div class="result">
        <a class="result__a" href="https://example.com/2">Title Two</a>
        <div class="result__snippet">Snippet two text</div>
      </div>
    </html>
    """

    def test_parses_results(self):
        mock_resp = MagicMock()
        mock_resp.text = self._DDG_HTML
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp):
            provider = DuckDuckGoProvider()
            result = provider.search("test query", max_results=5)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0].title, "Title One")
        self.assertEqual(result["results"][0].url, "https://example.com/1")
        self.assertEqual(result["results"][0].snippet, "Snippet one text")

    def test_no_results(self):
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>no results</body></html>"
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp):
            provider = DuckDuckGoProvider()
            result = provider.search("test query", max_results=5)

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "search_no_results")

    def test_timeout(self):
        import requests
        with patch("requests.post", side_effect=requests.exceptions.Timeout):
            provider = DuckDuckGoProvider()
            result = provider.search("test query", max_results=5)

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "search_provider_timeout")

    def test_request_exception(self):
        import requests
        with patch("requests.post", side_effect=requests.exceptions.RequestException("boom")):
            provider = DuckDuckGoProvider()
            result = provider.search("test query", max_results=5)

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "search_provider_unavailable")

    def test_respects_max_results(self):
        # Build HTML with 5 results
        html_parts = ["<html>"]
        for i in range(5):
            html_parts.append(
                f'<div class="result"><a class="result__a" href="https://example.com/{i}">Title {i}</a>'
                f'<a class="result__snippet">Snippet {i}</a></div>'
            )
        html_parts.append("</html>")
        html = "".join(html_parts)

        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp):
            provider = DuckDuckGoProvider()
            result = provider.search("test query", max_results=2)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["results"]), 2)


class TestSearXNGProvider(unittest.TestCase):
    """Test SearXNG provider behavior."""

    def test_not_configured_returns_failure(self):
        # Ensure env var is not set
        with patch.dict(os.environ, {}, clear=False):
            if "SEARXNG_BASE_URL" in os.environ:
                del os.environ["SEARXNG_BASE_URL"]
            provider = SearXNGProvider()
            self.assertFalse(provider.is_configured())
            result = provider.search("test", max_results=5)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["reason"], "search_no_provider_configured")

    def test_configured_parses_json(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"title": "T1", "url": "https://a.com", "content": "C1"},
                {"title": "T2", "url": "https://b.com", "content": "C2"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.dict(os.environ, {"SEARXNG_BASE_URL": "https://searx.example.com/"}):
            with patch("system.tools.search.providers.validate_url", return_value={"status": "success"}):
                with patch("requests.get", return_value=mock_resp):
                    provider = SearXNGProvider()
                    self.assertTrue(provider.is_configured())
                    result = provider.search("test", max_results=5)

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0].title, "T1")

    def test_timeout(self):
        import requests
        with patch.dict(os.environ, {"SEARXNG_BASE_URL": "https://searx.example.com/"}):
            with patch("system.tools.search.providers.validate_url", return_value={"status": "success"}):
                with patch("requests.get", side_effect=requests.exceptions.Timeout):
                    provider = SearXNGProvider()
                    result = provider.search("test", max_results=5)

        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "search_provider_timeout")


class TestSearchFunction(unittest.TestCase):
    """Test the core search() orchestration function."""

    def test_empty_query(self):
        result = search("")
        self.assertEqual(result["status"], "failure")
        self.assertEqual(result["reason"], "empty_query")

    def test_fallback_to_duckduckgo_when_searxng_fails(self):
        # Mock searxng as configured but failing; duckduckgo succeeds
        ddg_html = """
        <html>
          <div class="result">
            <a class="result__a" href="https://example.com/1">Title</a>
            <a class="result__snippet">Snippet</a>
          </div>
        </html>
        """
        ddg_resp = MagicMock()
        ddg_resp.text = ddg_html
        ddg_resp.raise_for_status = MagicMock()

        searxng_resp = MagicMock()
        searxng_resp.json.return_value = {"results": []}
        searxng_resp.raise_for_status = MagicMock()

        with patch.dict(os.environ, {"SEARXNG_BASE_URL": "https://searx.example.com/"}):
            with patch("system.tools.search.providers.validate_url", return_value={"status": "success"}):
                with patch("requests.get", return_value=searxng_resp):
                    with patch("requests.post", return_value=ddg_resp):
                        result = search("test query", provider=None, fallback=True, max_results=5)

        # Primary is searxng (configured), fallback is duckduckgo
        self.assertEqual(result["status"], "success")
        self.assertTrue(result.get("fallback_used", False))
        self.assertEqual(result["provider"], "duckduckgo")

    def test_no_fallback_when_primary_succeeds(self):
        ddg_html = """
        <html>
          <div class="result">
            <a class="result__a" href="https://example.com/1">Title</a>
            <a class="result__snippet">Snippet</a>
          </div>
        </html>
        """
        ddg_resp = MagicMock()
        ddg_resp.text = ddg_html
        ddg_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=ddg_resp):
            result = search("test query", provider="duckduckgo", fallback=True, max_results=5)

        self.assertEqual(result["status"], "success")
        self.assertFalse(result.get("fallback_used", True))
        self.assertEqual(result["provider"], "duckduckgo")

    def test_explicit_provider_selection(self):
        ddg_html = """
        <html>
          <div class="result">
            <a class="result__a" href="https://example.com/1">Title</a>
            <a class="result__snippet">Snippet</a>
          </div>
        </html>
        """
        ddg_resp = MagicMock()
        ddg_resp.text = ddg_html
        ddg_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=ddg_resp):
            result = search("test query", provider="duckduckgo", fallback=False, max_results=5)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider"], "duckduckgo")


class TestWebSearchIntegration(unittest.TestCase):
    """Test web_search tool backward compatibility via system_entry."""

    def test_web_search_backward_compatible_success(self):
        ddg_html = """
        <html>
          <div class="result">
            <a class="result__a" href="https://example.com/1">Python Docs</a>
            <a class="result__snippet">Official Python documentation</a>
          </div>
        </html>
        """
        ddg_resp = MagicMock()
        ddg_resp.text = ddg_html
        ddg_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=ddg_resp):
            from tools import web_search
            result = web_search.run("python documentation")

        # Should return the backward-compatible string format
        self.assertIsInstance(result, str)
        self.assertIn("Top results:", result)
        self.assertIn("Python Docs", result)
        self.assertIn("https://example.com/1", result)

    def test_web_search_backward_compatible_failure(self):
        import requests
        with patch("requests.post", side_effect=requests.exceptions.RequestException("fail")):
            from tools import web_search
            result = web_search.run("something")

        # Should return the backward-compatible failure string
        self.assertEqual(result, "no results found")

    def test_web_search_empty_query(self):
        from tools import web_search
        result = web_search.run("")
        self.assertEqual(result, "no results found")

    def test_web_search_routes_through_system_entry(self):
        from system.entry.system_entry import system_entry
        ddg_html = """
        <html>
          <div class="result">
            <a class="result__a" href="https://example.com/1">Title</a>
            <a class="result__snippet">Snippet</a>
          </div>
        </html>
        """
        ddg_resp = MagicMock()
        ddg_resp.text = ddg_html
        ddg_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=ddg_resp):
            result = system_entry('web_search "hello world"', mode="normal")

        self.assertEqual(result["status"], "success")
        self.assertIn("result", result)
        self.assertIsInstance(result["result"], str)
        self.assertIn("Top results:", result["result"])


class TestPlanModeIntegration(unittest.TestCase):
    """Test that web_search remains allowed in plan/read-only mode."""

    def test_web_search_allowed_in_plan_mode(self):
        from system.security.tool_policy import check_tool_policy
        result = check_tool_policy("web_search", mode="plan")
        self.assertTrue(result.allowed)

    def test_web_search_allowed_in_read_only_mode(self):
        from system.security.tool_policy import check_tool_policy
        result = check_tool_policy("web_search", mode="read_only")
        self.assertTrue(result.allowed)

    def test_web_search_is_external_call(self):
        from system.security.tool_policy import TOOL_METADATA
        meta = TOOL_METADATA.get("web_search", {})
        self.assertTrue(meta.get("external_call"))
        self.assertTrue(meta.get("read_only"))
        self.assertFalse(meta.get("mutating"))


class TestUrlSafetyIntegration(unittest.TestCase):
    """Test URL validator is consulted for provider endpoints."""

    def test_duckduckgo_endpoint_validated(self):
        # If we mock validate_url to block, provider should fail with url_safety_blocked
        with patch("system.tools.search.providers.validate_url", return_value={"status": "failure", "reason": "url_safety_blocked", "detail": "test block"}):
            provider = DuckDuckGoProvider()
            result = provider.search("test", max_results=5)
            self.assertEqual(result["status"], "failure")
            self.assertEqual(result["reason"], "url_safety_blocked")

    def test_no_secrets_exposed(self):
        ddg_html = """
        <html>
          <div class="result">
            <a class="result__a" href="https://example.com/1">Title</a>
            <a class="result__snippet">Snippet</a>
          </div>
        </html>
        """
        ddg_resp = MagicMock()
        ddg_resp.text = ddg_html
        ddg_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=ddg_resp):
            result = search("test query", provider="duckduckgo", max_results=5)

        self.assertEqual(result["status"], "success")
        # Result should not contain any API keys or secrets
        result_str = str(result)
        self.assertNotIn("api_key", result_str.lower())
        self.assertNotIn("secret", result_str.lower())
        self.assertNotIn("token", result_str.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
