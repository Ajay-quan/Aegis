# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Outbound HTTP for network tools: allowlisted destinations only, private
and metadata addresses blocked, every redirect hop re-validated, bounded
time and size.

Limitation: resolution happens here, then httpx resolves again when it
connects, so a DNS-rebinding race remains possible. The authoritative egress
boundary must be network-level (egress proxy / NetworkPolicy / security
groups) that the worker cannot modify; this module is defence in depth.
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
        _check_ip(ip)
    return host


def fetch(
    url: str,
    allowed_hosts: set[str],
    resolver: Resolver = system_resolver,
    client: httpx.Client | None = None,
    timeout: float = 5.0,
) -> tuple[int, bytes]:
    client = client or httpx.Client(timeout=timeout, follow_redirects=False, verify=True)
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url, allowed_hosts, resolver)
        with client.stream("GET", url) as resp:
            if resp.is_redirect:
                loc = resp.headers.get("location")
                if not loc:
                    raise EgressDenied("redirect without location")
                url = urljoin(url, loc)
                continue
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) > MAX_RESPONSE_BYTES:
                    raise EgressDenied("response too large")
            return resp.status_code, body
    raise EgressDenied("too many redirects")
