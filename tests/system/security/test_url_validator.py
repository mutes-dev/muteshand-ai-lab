"""
Security test suite for system/security/url_validator.py.

Covers:
- Valid http/https accepted
- Blocked schemes rejected
- Private IP blocking
- Loopback blocking
- Link-local blocking
- DNS resolution failure blocked
- IDN/control-character host blocked
- IPv4-mapped IPv6 private address blocked
- block_private=False behavior (except cloud metadata floor)
- Empty/null URL blocked
- Non-string URL blocked
"""

import os
import sys
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from system.security.url_validator import check_url, validate_url


def _mock_resolver(ips):
    """Return a resolver that always returns the given IPs."""
    def resolver(host):
        return list(ips)
    return resolver


class TestUrlValidatorBasic:
    """Basic input validation."""

    def test_empty_url_blocked(self):
        ok, reason = check_url("")
        assert not ok
        assert "required" in reason.lower()

    def test_whitespace_only_blocked(self):
        ok, reason = check_url("   ")
        assert not ok
        assert "required" in reason.lower()

    def test_none_blocked(self):
        ok, reason = check_url(None)
        assert not ok
        assert "string" in reason.lower()

    def test_non_string_blocked(self):
        ok, reason = check_url(12345)
        assert not ok
        assert "string" in reason.lower()


class TestUrlValidatorSchemes:
    """Scheme whitelisting."""

    def test_http_allowed(self):
        ok, _ = check_url("http://example.com/index.html", resolver=_mock_resolver(["93.184.216.34"]))
        assert ok

    def test_https_allowed(self):
        ok, _ = check_url("https://example.com/index.html", resolver=_mock_resolver(["93.184.216.34"]))
        assert ok

    def test_file_scheme_blocked(self):
        ok, reason = check_url("file:///etc/passwd")
        assert not ok
        assert "scheme" in reason.lower()

    def test_javascript_scheme_blocked(self):
        ok, reason = check_url("javascript:alert('xss')")
        assert not ok
        assert "scheme" in reason.lower()

    def test_data_scheme_blocked(self):
        ok, reason = check_url("data:text/html,<script>alert(1)</script>")
        assert not ok
        assert "scheme" in reason.lower()

    def test_chrome_scheme_blocked(self):
        ok, reason = check_url("chrome://settings/")
        assert not ok
        assert "scheme" in reason.lower()

    def test_about_scheme_blocked(self):
        ok, reason = check_url("about:blank")
        assert not ok
        assert "scheme" in reason.lower()

    def test_no_scheme_blocked(self):
        ok, reason = check_url("example.com")
        assert not ok
        assert "scheme" in reason.lower()


class TestUrlValidatorPrivateIps:
    """Private / loopback / link-local IP blocking."""

    def test_private_ipv4_10_blocked(self):
        ok, reason = check_url("http://10.0.0.1/", resolver=_mock_resolver(["10.0.0.1"]))
        assert not ok
        assert "private" in reason.lower()

    def test_private_ipv4_192_168_blocked(self):
        ok, reason = check_url("http://192.168.1.1/", resolver=_mock_resolver(["192.168.1.1"]))
        assert not ok
        assert "private" in reason.lower()

    def test_private_ipv4_172_16_blocked(self):
        ok, reason = check_url("http://172.16.0.1/", resolver=_mock_resolver(["172.16.0.1"]))
        assert not ok
        assert "private" in reason.lower()

    def test_loopback_ipv4_blocked(self):
        ok, reason = check_url("http://127.0.0.1/", resolver=_mock_resolver(["127.0.0.1"]))
        assert not ok
        assert "loopback" in reason.lower()

    def test_loopback_ipv6_blocked(self):
        ok, reason = check_url("http://[::1]/", resolver=_mock_resolver(["::1"]))
        assert not ok
        # ::1 is IPv6 loopback but also classified as reserved/disallowed by ipaddress
        assert "disallowed" in reason.lower() or "loopback" in reason.lower()

    def test_link_local_blocked(self):
        ok, reason = check_url("http://169.254.1.1/", resolver=_mock_resolver(["169.254.1.1"]))
        assert not ok
        assert "link-local" in reason.lower()

    def test_block_private_false_allows_private(self):
        ok, _ = check_url("http://10.0.0.1/", block_private=False, resolver=_mock_resolver(["10.0.0.1"]))
        assert ok

    def test_block_private_false_allows_loopback(self):
        ok, _ = check_url("http://127.0.0.1/", block_private=False, resolver=_mock_resolver(["127.0.0.1"]))
        assert ok


class TestUrlValidatorDnsFailure:
    """DNS resolution failure handling."""

    def test_dns_failure_blocked(self):
        def failing_resolver(host):
            raise Exception("DNS failure")
        ok, reason = check_url("http://nonexistent-domain-12345.local/", resolver=failing_resolver)
        assert not ok
        assert "resolve" in reason.lower()

    def test_empty_resolution_blocked(self):
        ok, reason = check_url("http://example.com/", resolver=_mock_resolver([]))
        assert not ok
        assert "resolve" in reason.lower()


class TestUrlValidatorIdnControlChars:
    """IDN / control character safety."""

    def test_null_byte_in_host_blocked(self):
        ok, reason = check_url("http://exam\x00ple.com/")
        assert not ok
        assert "control" in reason.lower()

    def test_control_char_in_host_blocked(self):
        ok, reason = check_url("http://exam\x01ple.com/")
        assert not ok
        assert "control" in reason.lower()


class TestUrlValidatorIpv4MappedIpv6:
    """IPv4-mapped IPv6 private address blocking."""

    def test_ipv4_mapped_ipv6_private_blocked(self):
        ok, reason = check_url("http://example.com/", resolver=_mock_resolver(["::ffff:192.168.1.1"]))
        assert not ok
        assert "private" in reason.lower()

    def test_ipv4_mapped_ipv6_loopback_blocked(self):
        ok, reason = check_url("http://example.com/", resolver=_mock_resolver(["::ffff:127.0.0.1"]))
        assert not ok
        assert "loopback" in reason.lower()

    def test_ipv4_mapped_ipv6_public_allowed(self):
        ok, _ = check_url("http://example.com/", resolver=_mock_resolver(["::ffff:93.184.216.34"]))
        assert ok


class TestUrlValidatorStructuredWrapper:
    """validate_url() wrapper shape."""

    def test_success_shape(self):
        result = validate_url("http://example.com/", resolver=_mock_resolver(["93.184.216.34"]))
        assert result["status"] == "success"

    def test_failure_shape(self):
        result = validate_url("file:///etc/passwd")
        assert result["status"] == "failure"
        assert result["reason"] == "url_safety_blocked"
        assert "detail" in result


class TestUrlValidatorCloudMetadataFloor:
    """Cloud metadata IP always-block floor (block_private=False should still block)."""

    def test_aws_ec2_metadata_blocked_even_with_block_private_false(self):
        ok, reason = check_url("http://169.254.169.254/latest/meta-data/", block_private=False, resolver=_mock_resolver(["169.254.169.254"]))
        assert not ok
        assert "metadata" in reason.lower()

    def test_aws_ecs_metadata_blocked_even_with_block_private_false(self):
        ok, reason = check_url("http://169.254.170.2/", block_private=False, resolver=_mock_resolver(["169.254.170.2"]))
        assert not ok
        assert "metadata" in reason.lower()

    def test_aws_cloudwatch_metadata_blocked_even_with_block_private_false(self):
        ok, reason = check_url("http://169.254.169.253/", block_private=False, resolver=_mock_resolver(["169.254.169.253"]))
        assert not ok
        assert "metadata" in reason.lower()

    def test_alibaba_cloud_metadata_blocked_even_with_block_private_false(self):
        ok, reason = check_url("http://100.100.100.200/", block_private=False, resolver=_mock_resolver(["100.100.100.200"]))
        assert not ok
        assert "metadata" in reason.lower()

    def test_cloud_metadata_blocked_with_block_private_true(self):
        ok, reason = check_url("http://169.254.169.254/", block_private=True, resolver=_mock_resolver(["169.254.169.254"]))
        assert not ok
        assert "metadata" in reason.lower()
