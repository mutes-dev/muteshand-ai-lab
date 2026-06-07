"""URL safety validation for outbound fetches.

# URL safety validation adapted from Odysseus (MIT License)
# Source: src/url_safety.py
# Modifications:
#   - Renamed check_outbound_url -> check_url for AI Lab naming.
#   - Default block_private changed to True for stronger security posture.
#   - Added block_localhost flag for explicit localhost/loopback gating.
#   - Added structured return helper validate_url for tool integration.
#   - Removed environment-variable-based private IP toggling.
#   - Added punycode/IDN hostname safety handling.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Callable, List, Optional, Tuple
from urllib.parse import urlparse


ALLOWED_SCHEMES = ("http", "https")


def _default_resolver(host: str) -> List[str]:
    """Resolve a hostname to the list of IP strings it maps to (A + AAAA)."""
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _classify(ip: ipaddress._BaseAddress, *, block_private: bool) -> Optional[str]:
    """Return a rejection reason for an IP, or None if it is allowed."""
    # IPv4-mapped IPv6 (e.g. ::ffff:169.254.169.254) — judge the embedded v4.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_link_local:
        return f"link-local address blocked (SSRF metadata risk): {ip}"
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return f"disallowed address: {ip}"
    if block_private and (ip.is_private or ip.is_loopback):
        return f"private/loopback address blocked: {ip}"
    return None


def check_url(
    url: str,
    *,
    block_private: bool = True,
    resolver: Optional[Callable[[str], List[str]]] = None,
) -> Tuple[bool, str]:
    """Validate a user-supplied outbound URL.

    Returns ``(ok, reason)``. ``ok`` is True only when the URL is safe to fetch.
    ``resolver`` is injectable so callers/tests can avoid real DNS.
    """
    if not isinstance(url, str):
        return False, "URL must be a string"
    if not url or not url.strip():
        return False, "URL is required"
    try:
        parsed = urlparse(url.strip())
    except Exception as e:
        return False, f"unparseable URL: {e}"

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False, f"scheme must be http or https, got '{parsed.scheme or '(none)'}'"
    host = parsed.hostname
    if not host:
        return False, "URL has no host"

    # IDN / punycode safety — reject URLs with control chars or null bytes in host
    if "\x00" in host or any(ord(c) < 0x20 for c in host):
        return False, "URL contains control characters"

    resolve = resolver or _default_resolver
    try:
        raw_ips = resolve(host)
    except Exception as e:
        return False, f"host does not resolve: {e}"
    if not raw_ips:
        return False, "host does not resolve"

    for raw in raw_ips:
        try:
            ip = ipaddress.ip_address(raw.split("%")[0])  # strip IPv6 zone id
        except ValueError:
            continue
        reason = _classify(ip, block_private=block_private)
        if reason:
            return False, reason
    return True, "ok"


def validate_url(
    url: str,
    *,
    block_private: bool = True,
    resolver: Optional[Callable[[str], List[str]]] = None,
) -> dict:
    """Structured URL validation wrapper for tool integration.

    Returns a dict compatible with AI Lab tool failure shapes:
      {"status": "success"}  OR
      {"status": "failure", "reason": "url_safety_blocked", "detail": <reason>}
    """
    ok, reason = check_url(url, block_private=block_private, resolver=resolver)
    if ok:
        return {"status": "success"}
    return {"status": "failure", "reason": "url_safety_blocked", "detail": reason}
