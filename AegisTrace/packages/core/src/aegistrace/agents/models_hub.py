# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Model Hub: registered model endpoints per organization.

- Provider keys are stored encrypted (persistence.sealing.seal_secret) and never returned.
- Endpoints are administrator input: HTTPS only, except plain HTTP to a private address
  when the registration explicitly allows private networks (e.g. local Ollama). Link-local
  and metadata addresses are always refused. Redirects are not followed.
- "Test connection" calls the provider's model listing and checks the model is offered.
- Runs: openai-compatible (vLLM, llama.cpp server, hosted APIs), ollama (its OpenAI-compatible
  /v1 API) and mock run agents. Anthropic can be registered and tested; running agents on it
  needs an adapter that is not built yet, and the API says so instead of pretending.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from .model import MockModel, ModelAdapter, OpenAICompatibleModel

RUNNABLE = ("openai-compatible", "ollama", "mock")
DEFAULT_BASE = {"anthropic": "https://api.anthropic.com", "ollama": "http://host.docker.internal:11434"}


@dataclass(frozen=True)
class Registration:
    id: str
    tenant_id: str
    provider: str
    base_url: str | None
    model_id: str
    allow_private_network: bool


class EndpointRefused(Exception):
    pass


class NotRunnable(Exception):
    pass


def _resolve(host: str) -> list[str]:
    try:
        return list({ai[4][0] for ai in socket.getaddrinfo(host, None)})  # type: ignore[misc]
    except socket.gaierror:
        return []


def check_endpoint(url: str, allow_private: bool, resolve: Callable[[str], list[str]] = _resolve) -> None:
    parts = urlsplit(url)
    host = (parts.hostname or "").rstrip(".").lower()
    if parts.scheme not in ("https", "http") or not host or parts.username or parts.password:
        raise EndpointRefused("invalid endpoint URL")
    addrs = resolve(host)
    if not addrs:
        raise EndpointRefused(f"cannot resolve {host}")
    private = False
    for raw in addrs:
        ip = ipaddress.ip_address(raw.split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise EndpointRefused(f"address not allowed: {ip}")
        if ip.is_private or ip.is_loopback:
            private = True
    if private and not allow_private:
        raise EndpointRefused("private network address; enable 'allow private network' for this model")
    if parts.scheme == "http" and not private:
        raise EndpointRefused("public endpoints must use https")


def base_url(reg: Registration) -> str:
    return (reg.base_url or DEFAULT_BASE.get(reg.provider, "")).rstrip("/")


def test_connection(
    reg: Registration,
    secret: str | None,
    client: httpx.Client | None = None,
    resolve: Callable[[str], list[str]] = _resolve,
) -> tuple[bool, str]:
    if reg.provider == "mock":
        return True, "demo model: always available, deterministic"
    url = base_url(reg)
    check_endpoint(url, reg.allow_private_network, resolve)
    http = client or httpx.Client(timeout=5.0, follow_redirects=False)
    headers: dict[str, str]
    if reg.provider == "ollama":
        target, headers, key = url + "/api/tags", {}, "models"
    elif reg.provider == "anthropic":
        target, key = url + "/v1/models", "data"
        headers = {"x-api-key": secret or "", "anthropic-version": "2023-06-01"}
    else:
        target, key = url + "/models", "data"
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    try:
        r = http.get(target, headers=headers)
    except httpx.HTTPError as exc:
        return False, f"could not connect ({type(exc).__name__})"
    if r.status_code in (401, 403):
        return False, f"the provider refused the credentials (HTTP {r.status_code})"
    if r.status_code != 200:
        return False, f"unexpected response (HTTP {r.status_code})"
    try:
        listed = [m.get("id") or m.get("name") or m.get("model") for m in r.json().get(key, [])]
    except (ValueError, AttributeError):
        return False, "the endpoint did not return a model list"
    if reg.model_id not in listed:
        return False, f"connected, but '{reg.model_id}' is not among the {len(listed)} models offered"
    return True, f"connected; '{reg.model_id}' is available ({len(listed)} models offered)"


def adapter_for(reg: Registration, secret: str | None, run_input: dict[str, Any]) -> ModelAdapter:
    if reg.provider == "mock":
        return MockModel(run_input.get("mock_script", []))
    if reg.provider not in RUNNABLE:
        raise NotRunnable(f"agents cannot run on {reg.provider} models yet (connection test only)")
    check_endpoint(base_url(reg), reg.allow_private_network)  # re-checked before every run
    url = base_url(reg) + ("/v1" if reg.provider == "ollama" else "")
    return OpenAICompatibleModel(url, secret or "ollama", reg.model_id)
