"""
Security behavior tests for tools/read_webpage.py.

Covers:
- Redirect responses are blocked
- Script tags are stripped
- Style tags are stripped
- 404 response returns failure
- Timeout returns failure

All tests mock requests.get — no real network calls.
"""

import os
import sys
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pytest
from tools.read_webpage import run as read_webpage_run


class TestReadWebpageRedirects:
    """Redirect blocking behavior."""

    @patch("requests.get")
    def test_302_redirect_blocked(self, mock_get):
        """A 302 redirect response must be blocked even if requests returns it."""
        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.is_redirect = True
        mock_response.is_permanent_redirect = False
        mock_response.headers = {"Location": "http://example.com/other"}
        # Explicitly truthy/false for safety; MagicMock defaults are truthy
        mock_get.return_value = mock_response

        result = read_webpage_run("http://example.com/")
        assert result["status"] == "failure"
        assert "redirect" in result["detail"].lower()

    @patch("requests.get")
    def test_301_permanent_redirect_blocked(self, mock_get):
        """A 301 permanent redirect must be blocked."""
        mock_response = MagicMock()
        mock_response.status_code = 301
        mock_response.is_redirect = False
        mock_response.is_permanent_redirect = True
        mock_response.headers = {"Location": "http://example.com/other"}
        # Explicitly truthy/false for safety; MagicMock defaults are truthy
        mock_get.return_value = mock_response

        result = read_webpage_run("http://example.com/")
        assert result["status"] == "failure"
        assert "redirect" in result["detail"].lower()


class TestReadWebpageContentStripping:
    """HTML tag stripping behavior."""

    @patch("requests.get")
    def test_script_tags_stripped(self, mock_get):
        """Script tags must not appear in extracted text."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.is_permanent_redirect = False
        mock_response.text = (
            "<html><body>"
            "<script>alert('xss')</script>"
            "<p>Hello world</p>"
            "</body></html>"
        )
        # Explicitly set redirect flags; MagicMock defaults are truthy
        mock_get.return_value = mock_response

        result = read_webpage_run("http://example.com/")
        assert result["status"] == "success"
        assert "alert" not in result["result"]
        assert "xss" not in result["result"]
        assert "Hello world" in result["result"]

    @patch("requests.get")
    def test_style_tags_stripped(self, mock_get):
        """Style tags must not appear in extracted text."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.is_permanent_redirect = False
        mock_response.text = (
            "<html><head><style>body{color:red}</style></head><body>"
            "<p>Hello world</p>"
            "</body></html>"
        )
        # Explicitly set redirect flags; MagicMock defaults are truthy
        mock_get.return_value = mock_response

        result = read_webpage_run("http://example.com/")
        assert result["status"] == "success"
        assert "color:red" not in result["result"]
        assert "Hello world" in result["result"]

    @patch("requests.get")
    def test_text_extraction_basic(self, mock_get):
        """Readable text is extracted from HTML."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.is_permanent_redirect = False
        mock_response.text = "<html><body><p>Hello world</p></body></html>"
        # Explicitly set redirect flags; MagicMock defaults are truthy
        mock_get.return_value = mock_response

        result = read_webpage_run("http://example.com/")
        assert result["status"] == "success"
        assert "Hello world" in result["result"]


class TestReadWebpageErrors:
    """Error handling behavior."""

    @patch("requests.get")
    def test_404_returns_failure(self, mock_get):
        """HTTP 404 must return a failure result."""
        from requests.exceptions import HTTPError

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.is_redirect = False
        mock_response.is_permanent_redirect = False
        mock_response.raise_for_status.side_effect = HTTPError(response=mock_response)
        # Explicitly set redirect flags; MagicMock defaults are truthy
        mock_get.return_value = mock_response

        result = read_webpage_run("http://example.com/notfound")
        assert result["status"] == "failure"
        assert "http" in result.get("reason", "").lower() or "404" in result.get("detail", "")

    @patch("requests.get")
    def test_timeout_returns_failure(self, mock_get):
        """Network timeout must return a failure result."""
        from requests.exceptions import Timeout
        mock_get.side_effect = Timeout("Connection timed out")

        result = read_webpage_run("http://example.com/")
        assert result["status"] == "failure"
        assert result.get("reason") == "timeout"

    @patch("requests.get")
    def test_connection_error_returns_failure(self, mock_get):
        """Connection error must return a failure result."""
        from requests.exceptions import ConnectionError
        mock_get.side_effect = ConnectionError("No route to host")

        result = read_webpage_run("http://example.com/")
        assert result["status"] == "failure"
        assert "connection" in result.get("reason", "").lower()
