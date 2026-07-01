"""URL safety validation tests — adapted from Odysseus (MIT License).

Tests for system/security/url_validator.py, with integration checks for
tools that perform outbound URL fetches (read_webpage, web_search).

A stub resolver is injected so these tests never touch real DNS.
"""

import pytest

from system.security.url_validator import check_url, validate_url


# ── Stub resolvers (injected so tests avoid real DNS) ──────────────────────

def _resolver(mapping):
    def resolve(host):
        if host in mapping:
            return mapping[host]
        raise OSError(f"unresolvable: {host}")
    return resolve


PUBLIC = _resolver({"example.com": ["93.184.216.34"]})
LOOPBACK = _resolver({"localhost": ["127.0.0.1"], "127.0.0.1": ["127.0.0.1"]})
LAN = _resolver({"nas.local": ["192.168.1.50"]})
METADATA = _resolver({"evil.example": ["169.254.169.254"]})
MAPPED_METADATA = _resolver({"evil6.example": ["::ffff:169.254.169.254"]})
IPV6_LOOPBACK = _resolver({"ipv6.localhost": ["::1"], "::1": ["::1"]})
ZERO = _resolver({"zero.example": ["0.0.0.0"], "0.0.0.0": ["0.0.0.0"]})


# ── Unit tests: check_url ──────────────────────────────────────────────────

def test_public_url_allowed():
    ok, reason = check_url("https://example.com/v1/embeddings", resolver=PUBLIC)
    assert ok is True, reason


def test_http_url_allowed():
    ok, reason = check_url("http://example.com/page", resolver=PUBLIC)
    assert ok is True, reason


def test_non_http_scheme_blocked():
    for url in (
        "file:///etc/passwd",
        "ftp://x/y",
        "gopher://h",
        "redis://h:6379",
        "javascript:alert(1)",
    ):
        ok, reason = check_url(url, resolver=PUBLIC)
        assert ok is False, url
        assert "scheme" in reason.lower(), f"expected scheme error for {url}: {reason}"


def test_missing_host_or_empty_blocked():
    assert check_url("", resolver=PUBLIC)[0] is False
    assert check_url("http://", resolver=PUBLIC)[0] is False
    assert check_url("   ", resolver=PUBLIC)[0] is False


def test_none_blocked():
    ok, reason = check_url(None, resolver=PUBLIC)
    assert ok is False
    assert "string" in reason.lower()


def test_localhost_blocked():
    ok, reason = check_url("http://localhost:8080/v1", resolver=LOOPBACK)
    assert ok is False
    assert "private" in reason.lower() or "loopback" in reason.lower()


def test_127_0_0_1_blocked():
    ok, reason = check_url("http://127.0.0.1:8080/v1", resolver=LOOPBACK)
    assert ok is False
    assert "private" in reason.lower() or "loopback" in reason.lower()


def test_0_0_0_0_blocked():
    ok, reason = check_url("http://zero.example/", resolver=ZERO)
    assert ok is False
    assert "unspecified" in reason.lower() or "disallowed" in reason.lower()


def test_private_ipv4_blocked():
    ok, reason = check_url("http://nas.local:1234/v1", resolver=LAN)
    assert ok is False
    assert "private" in reason.lower()


def test_cloud_metadata_blocked():
    ok, reason = check_url("http://evil.example/latest/meta-data/", resolver=METADATA)
    assert ok is False
    assert "link-local" in reason.lower()


def test_ipv4_mapped_metadata_blocked():
    ok, reason = check_url("http://evil6.example/", resolver=MAPPED_METADATA)
    assert ok is False
    assert "link-local" in reason.lower()


def test_ipv6_loopback_blocked():
    ok, reason = check_url("http://ipv6.localhost/", resolver=IPV6_LOOPBACK)
    assert ok is False
    assert "private" in reason.lower() or "loopback" in reason.lower() or "disallowed" in reason.lower()


def test_unresolvable_host_blocked():
    ok, reason = check_url("http://does-not-resolve.invalid", resolver=PUBLIC)
    assert ok is False
    assert "resolve" in reason.lower()


def test_malformed_url_blocked():
    ok, reason = check_url("not-a-url-at-all", resolver=PUBLIC)
    assert ok is False
    assert "scheme" in reason.lower() or "unparseable" in reason.lower()


def test_control_chars_in_host_blocked():
    ok, reason = check_url("http://exam\x00ple.com/", resolver=PUBLIC)
    assert ok is False
    assert "control" in reason.lower()


# ── Unit tests: validate_url (structured wrapper) ────────────────────────────

def test_validate_url_success():
    result = validate_url("https://example.com/", resolver=PUBLIC)
    assert result == {"status": "success"}


def test_validate_url_failure_shape():
    result = validate_url("http://localhost/", resolver=LOOPBACK)
    assert result["status"] == "failure"
    assert result["reason"] == "url_safety_blocked"
    assert "detail" in result
    assert "loopback" in result["detail"].lower() or "private" in result["detail"].lower()


# ── Unit tests: block_private toggle ─────────────────────────────────────────

def test_private_allowed_when_block_private_false():
    ok, reason = check_url("http://nas.local/", block_private=False, resolver=LAN)
    assert ok is True, reason


def test_loopback_allowed_when_block_private_false():
    ok, reason = check_url("http://localhost/", block_private=False, resolver=LOOPBACK)
    assert ok is True, reason


# ── Integration: read_webpage tool ─────────────────────────────────────────

def test_read_webpage_blocks_localhost():
    import sys
    import os
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.read_webpage import run as read_webpage

    result = read_webpage("http://localhost/secret")
    assert isinstance(result, dict)
    assert result.get("status") == "failure"
    assert result.get("reason") == "url_safety_blocked"
    assert "detail" in result


def test_read_webpage_blocks_file_scheme():
    import sys
    import os
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.read_webpage import run as read_webpage

    result = read_webpage("file:///etc/passwd")
    assert isinstance(result, dict)
    assert result.get("status") == "failure"
    assert result.get("reason") == "url_safety_blocked"


def test_read_webpage_blocks_private_ip():
    import sys
    import os
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.read_webpage import run as read_webpage

    result = read_webpage("http://192.168.1.1/admin")
    assert isinstance(result, dict)
    assert result.get("status") == "failure"
    assert result.get("reason") == "url_safety_blocked"


# ── Integration: read_webpage redirect safety ────────────────────────────────

def test_read_webpage_blocks_redirects():
    import sys
    import os
    from unittest.mock import patch, MagicMock
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.read_webpage import run as read_webpage

    mock_response = MagicMock()
    mock_response.is_redirect = True
    mock_response.status_code = 302
    mock_response.headers = {"Location": "http://evil.internal/admin"}
    with patch("requests.get", return_value=mock_response):
        result = read_webpage("https://example.com/page")
    assert isinstance(result, dict)
    assert result.get("status") == "failure"
    assert result.get("reason") == "url_safety_blocked"
    assert "redirect" in result.get("detail", "").lower()


# ── Integration: web_search tool (hardcoded URL — defense-in-depth) ──────────

def test_web_search_hardcoded_url_passes():
    import sys
    import os
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from tools.web_search import run as web_search

    # Hardcoded DuckDuckGo URL should pass validation and proceed to network
    # (network may fail in CI, but validation must not block it)
    result = web_search("python programming")
    # Result is either a string with results or "no results found" on network failure
    assert isinstance(result, str)
