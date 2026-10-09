"""Optional real-network fetchers for citation-verifier.

These are kept OUT of the pure ``citations.py`` core so that the core logic
stays fully testable offline. Importing this module never requires any third
party package — it uses only Python standard-library HTTP, TLS and socket modules.

A fetcher has the signature ``(url) -> status_code | None`` where ``None``
means the host was unreachable. This matches what ``citations.classify`` and
``citations.audit`` expect.
"""
from __future__ import annotations

import urllib.parse
import http.client
import ipaddress
import socket
import ssl
import time
from typing import Optional

DEFAULT_TIMEOUT = 8.0
_USER_AGENT = "citation-verifier/1.0 (+https://github.com/agent-toolforge)"


class UnsafeURL(ValueError):
    """The URL is outside the public-web boundary."""


def _public_target(url):
    if not isinstance(url, str) or any(ord(c) < 33 for c in url) or len(url) > 8192:
        raise UnsafeURL("Invalid URL")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise UnsafeURL("Only public HTTP(S) URLs without credentials are allowed")
    host = parsed.hostname.encode("idna").decode("ascii")
    if "%" in host:
        raise UnsafeURL("Scoped addresses are not allowed")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise UnsafeURL("No public address")
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if (ip.version == 6 and (ip in ipaddress.ip_network("64:ff9b::/96") or ip in ipaddress.ip_network("64:ff9b:1::/48"))) or not ip.is_global or ip.is_multicast or ip.is_reserved or getattr(ip, "ipv4_mapped", None) or getattr(ip, "sixtofour", None) or getattr(ip, "teredo", None):
            raise UnsafeURL("Non-public address")
    # Connect to this exact numeric address: never resolve the hostname twice.
    return parsed, host, port, addresses[0]


def _request(url, method, timeout, body_limit=0):
    deadline = time.monotonic() + timeout
    for _ in range(6):
        parsed, host, port, address = _public_target(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Request budget exhausted")
        family, socktype, protocol, _, sockaddr = address
        conn = http.client.HTTPConnection(host, port, timeout=remaining)
        sock = socket.socket(family, socktype, protocol)
        try:
            sock.settimeout(remaining)
            sock.connect(sockaddr)
            if parsed.scheme == "https":
                context = ssl.create_default_context()
                context.set_alpn_protocols(["http/1.1"])
                sock = context.wrap_socket(sock, server_hostname=host)
            conn.sock = sock
            target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            conn.request(method, target, headers={"User-Agent": _USER_AGENT, "Connection": "close"})
            response = conn.getresponse()
            status = response.status
            location = response.getheader("Location")
            if status in (301, 302, 303, 307, 308) and location:
                url = urllib.parse.urljoin(url, location)
                continue
            body = response.read(body_limit + 1) if body_limit else b""
            if len(body) > body_limit:
                raise ValueError("Response too large")
            return status, body
        finally:
            conn.close()
            sock.close()
    raise UnsafeURL("Too many redirects")


def http_fetcher(url: str, timeout: float = DEFAULT_TIMEOUT) -> Optional[int]:
    """Return the HTTP status code for *url*, or ``None`` if unreachable.

    Tries a lightweight HEAD request first, falling back to GET for the many
    servers that reject HEAD. Any network-level failure yields ``None`` so the
    URL is classified as ``unreachable`` rather than ``dead``.
    """
    deadline = time.monotonic() + timeout
    for method in ("HEAD", "GET"):
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            status, _ = _request(url, method, remaining)
            if method == "HEAD" and status in (405, 501):
                continue
            return status
        except UnsafeURL:
            return None
        except (http.client.HTTPException, OSError, ValueError):
            # HEAD may be refused; try GET. If GET also fails, fall through.
            continue
    return None


def wayback_fetcher(url: str, timeout: float = DEFAULT_TIMEOUT) -> Optional[int]:
    """Status via the Wayback Machine as a fallback for dead links.

    Queries the Internet Archive availability API. Returns 200 if a snapshot
    exists, 404 if none was archived, or ``None`` on a network failure.
    """
    import json

    try:
        parsed = urllib.parse.urlsplit(url)
        # Query strings can carry signed URLs, reset tokens or private searches.
        # A fragment is local to the browser and must never be sent to an archive.
        if parsed.query:
            return None
        public_url = urllib.parse.urlunsplit(parsed._replace(fragment=""))
        api = "https://archive.org/wayback/available?url=" + urllib.parse.quote(public_url, safe="")
        _public_target(url)  # Never send rejected/private URLs to a third party.
        status, body = _request(api, "GET", timeout, body_limit=1024 * 1024)
        if status != 200:
            return None
        data = json.loads(body.decode("utf-8", "replace"))
        if not isinstance(data, dict):
            return None
    except (http.client.HTTPException, OSError, ValueError):
        return None
    snapshots = data.get("archived_snapshots") or {}
    return 200 if isinstance(snapshots, dict) and snapshots.get("closest") else 404


def resilient_fetcher(url: str, timeout: float = DEFAULT_TIMEOUT) -> Optional[int]:
    """Live HTTP check, with a Wayback fallback when the link looks dead.

    If the direct request reports a dead (4xx/5xx) or unreachable result, we
    consult the Wayback Machine; a successful archive promotes the link back to
    ``live`` so an archived-but-rotted citation is not penalized as fabricated.
    """
    deadline = time.monotonic() + timeout
    status = http_fetcher(url, timeout=timeout)
    if status is not None and 200 <= status < 400:
        return status
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return status
    wb = wayback_fetcher(url, timeout=remaining)
    if wb == 200:
        return 200
    return status
