# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Outbound HTTP for network tools: allowlisted destinations only, private
and metadata addresses blocked, every redirect hop re-validated, bounded
time and size.

DNS pinning: each hop is resolved once, every address is checked, and the
connection goes to the checked address itself (an IP-literal URL) while TLS
still verifies the certificate against the real hostname (SNI + Host header).
A second, different DNS answer at connect time (DNS rebinding) therefore
cannot redirect the request to an internal address.

Network-level egress control (an egress proxy, NetworkPolicy or security
groups the worker cannot modify) remains the authoritative boundary in
production; this module is defence in depth. See docs/security/EGRESS.md.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urljoin, urlsplit

import httpx

MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 256 * 1024

Resolver = Callable[[str], list[str]]


class EgressDenied(Exception):
    pass


def system_resolver(host: str) -> list[str]:
    return list({ai[4][0] for ai in socket.getaddrinfo(host, None)})  # type: ignore[misc]


def _check_ip(ip: str) -> None:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or not addr.is_global
    ):
        raise EgressDenied(f"destination address not allowed: {addr}")


def check_url(url: str, allowed_hosts: set[str], resolver: Resolver) -> str:
    return resolve_checked(url, allowed_hosts, resolver)[0]


def resolve_checked(url: str, allowed_hosts: set[str], resolver: Resolver) -> tuple[str, str]:
    """Validate the URL and its DNS answers; return (hostname, the address to connect to)."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise EgressDenied("only https is allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or parts.username or parts.password:
        raise EgressDenied("invalid host")
    if host not in allowed_hosts:
        raise EgressDenied(f"host not allowlisted: {host}")
    try:
        ips = resolver(host)
    except OSError as exc:
        raise EgressDenied("dns resolution failed") from exc
    if not ips:
        raise EgressDenied("no addresses")
    for ip in ips:
        _check_ip(ip)  # every answer must be acceptable, not just the one we use
    return host, sorted(ips)[0]


def pinned_request(client: httpx.Client, url: str, host: str, ip: str) -> httpx.Request:
    """A GET to `ip` (no second DNS lookup) that presents and verifies `host` over TLS."""
    parts = urlsplit(url)
    literal = f"[{ip}]" if ":" in ip else ip
    netloc = literal + (f":{parts.port}" if parts.port else "")
    target = parts._replace(netloc=netloc).geturl()
    host_header = host + (f":{parts.port}" if parts.port else "")
    return client.build_request("GET", target, headers={"Host": host_header}, extensions={"sni_hostname": host})


def fetch(
    url: str,
    allowed_hosts: set[str],
    resolver: Resolver = system_resolver,
    client: httpx.Client | None = None,
    timeout: float = 5.0,
) -> tuple[int, bytes]:
    client = client or httpx.Client(timeout=timeout, follow_redirects=False, verify=True)
    for _ in range(MAX_REDIRECTS + 1):
        host, ip = resolve_checked(url, allowed_hosts, resolver)
        resp = client.send(pinned_request(client, url, host, ip), stream=True)
        try:
            if resp.is_redirect:
                loc = resp.headers.get("location")
                if not loc:
                    raise EgressDenied("redirect without location")
                url = urljoin(url, loc)  # relative to the hostname URL, so the next hop is checked by name
                continue
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) > MAX_RESPONSE_BYTES:
                    raise EgressDenied("response too large")
            return resp.status_code, body
        finally:
            resp.close()
    raise EgressDenied("too many redirects")
