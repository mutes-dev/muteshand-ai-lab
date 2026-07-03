"""Tests for read_webpage HTML extraction and sanitization (FRT-003A)."""

import sys
import os

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from unittest.mock import patch, MagicMock
import pytest

from tools.read_webpage import run as read_webpage, _is_html_content, _normalize_whitespace


def _make_mock_response(text, status_code=200, content_type="text/html", is_redirect=False, is_permanent_redirect=False):
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = text
    mock.headers = {"content-type": content_type}
    mock.is_redirect = is_redirect
    mock.is_permanent_redirect = is_permanent_redirect
    return mock


# Patch validate_url so tests never touch real DNS
@patch("system.security.url_validator.validate_url", return_value={"status": "success"})
class TestReadWebpageSanitization:
    """HTML extraction and sanitization tests."""

    def test_strips_script_style_noscript(self, mock_val):
        html = """
        <html><head><title>Test</title></head><body>
        <script>alert('xss');</script>
        <style>.red{color:red;}</style>
        <noscript>Enable JS</noscript>
        <p>Hello World</p>
        </body></html>
        """
        with patch("requests.get", return_value=_make_mock_response(html)):
            result = read_webpage("https://example.com")
        assert result["status"] == "success"
        text = result["result"]
        assert "alert" not in text
        assert "xss" not in text
        assert ".red" not in text
        assert "Enable JS" not in text
        assert "Hello World" in text

    def test_strips_iframe_object_embed_svg_canvas(self, mock_val):
        html = """
        <html><body>
        <iframe src="//evil.com"></iframe>
        <object data="movie.swf"></object>
        <embed src="movie.swf">
        <svg><circle/></svg>
        <canvas id="c"></canvas>
        <p>Article text here</p>
        </body></html>
        """
        with patch("requests.get", return_value=_make_mock_response(html)):
            result = read_webpage("https://example.com")
        assert result["status"] == "success"
        text = result["result"]
        assert "evil.com" not in text
        assert "movie.swf" not in text
        assert "circle" not in text
        assert "Article text here" in text

    def test_strips_forms_and_inputs(self, mock_val):
        html = """
        <html><body>
        <form action="/submit">
            <label>Name</label>
            <input type="text" value="John">
            <textarea>Comments</textarea>
            <button>Submit</button>
            <select><option>A</option><option>B</option></select>
        </form>
        <p>Real content</p>
        </body></html>
        """
        with patch("requests.get", return_value=_make_mock_response(html)):
            result = read_webpage("https://example.com")
        assert result["status"] == "success"
        text = result["result"]
        assert "Comments" not in text
        assert "John" not in text
        assert "Submit" not in text
        assert "A" not in text
        assert "Real content" in text

    def test_extracts_title(self, mock_val):
        html = "<html><head><title>My Article</title></head><body><p>Body text</p></body></html>"
        with patch("requests.get", return_value=_make_mock_response(html)):
            result = read_webpage("https://example.com")
        assert result["status"] == "success"
        text = result["result"]
        assert text.startswith("Title: My Article")
        assert "Body text" in text

    def test_no_title_no_prefix(self, mock_val):
        html = "<html><body><p>Only body</p></body></html>"
        with patch("requests.get", return_value=_make_mock_response(html)):
            result = read_webpage("https://example.com")
        assert result["status"] == "success"
        text = result["result"]
        assert "Title:" not in text
        assert "Only body" in text

    def test_malformed_html_fallback(self, mock_val):
        html = "<html><body><p>Unclosed <div>text</body></html>"
        with patch("requests.get", return_value=_make_mock_response(html)):
            result = read_webpage("https://example.com")
        assert result["status"] == "success"
        assert "text" in result["result"]

    def test_non_html_content_type_json(self, mock_val):
        raw = '{"key": "value"}'
        with patch("requests.get", return_value=_make_mock_response(raw, content_type="application/json")):
            result = read_webpage("https://api.example.com/data")
        assert result["status"] == "success"
        text = result["result"]
        assert '"key": "value"' in text
        # Should not contain HTML parser artifacts like "Title:"
        assert "Title:" not in text

    def test_non_html_content_type_plain(self, mock_val):
        raw = "Just plain text\nwith lines"
        with patch("requests.get", return_value=_make_mock_response(raw, content_type="text/plain")):
            result = read_webpage("https://example.com/text")
        assert result["status"] == "success"
        assert result["result"] == raw

    def test_normal_page_whitespace_collapsed(self, mock_val):
        html = """
        <html><body>
        <p>Para one</p>


        <p>Para two</p>

        </body></html>
        """
        with patch("requests.get", return_value=_make_mock_response(html)):
            result = read_webpage("https://example.com")
        assert result["status"] == "success"
        text = result["result"]
        assert "Para one" in text
        assert "Para two" in text
        # Excessive blank lines should be collapsed
        assert "\n\n\n" not in text

    def test_truncation_preserved(self, mock_val):
        long_text = "word " * 2000  # ~12,000 chars
        html = f"<html><body><p>{long_text}</p></body></html>"
        with patch("requests.get", return_value=_make_mock_response(html)):
            result = read_webpage("https://example.com")
        assert result["status"] == "success"
        assert len(result["result"]) <= 5000

    def test_redirect_still_blocked(self, mock_val):
        mock = _make_mock_response("", is_redirect=True, status_code=302)
        mock.headers = {"Location": "http://evil.internal/admin"}
        with patch("requests.get", return_value=mock):
            result = read_webpage("https://example.com/page")
        assert result["status"] == "failure"
        assert result["reason"] == "url_safety_blocked"
        assert "redirect" in result.get("detail", "").lower()

    def test_http_error_taxonomy_preserved(self, mock_val):
        from requests.exceptions import HTTPError
        mock = _make_mock_response("", status_code=404)
        mock.raise_for_status.side_effect = HTTPError(response=mock)
        with patch("requests.get", return_value=mock):
            result = read_webpage("https://example.com/notfound")
        assert result["status"] == "failure"
        assert result["reason"] == "http_error"
        assert "404" in result.get("detail", "")

    def test_timeout_taxonomy_preserved(self, mock_val):
        from requests.exceptions import Timeout
        with patch("requests.get", side_effect=Timeout()):
            result = read_webpage("https://example.com/slow")
        assert result["status"] == "failure"
        assert result["reason"] == "timeout"

    def test_connection_error_taxonomy_preserved(self, mock_val):
        from requests.exceptions import ConnectionError
        with patch("requests.get", side_effect=ConnectionError("refused")):
            result = read_webpage("https://example.com/down")
        assert result["status"] == "failure"
        assert result["reason"] == "connection_error"
        assert "refused" in result.get("detail", "").lower()
