# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""MCP server bridge: local (stdio) and remote (Streamable HTTP) servers.

Trust model:
- An MCP server is untrusted. Its tool names, descriptions, annotations
  (e.g. readOnlyHint), schemas, and results are data, never authority.
- A tool is exposed only if an administrator mapped it in McpServerConfig,
  with a platform-assigned risk class. Unmapped tools are invisible.
- The input schema is pinned by digest at approval time. If the server later
  advertises a different schema (a "rug pull"), the tool is disabled.
- Local servers: each call uses a fresh server process with an explicit,
  minimal environment.
- Remote servers: the URL is administrator configuration, never model
  input. HTTPS only (plain HTTP only for loopback with an explicit dev flag);
  link-local/metadata addresses are always refused and private networks only
  when allowed per server; redirects never leave the endpoint's origin.
- Credentials: AegisTrace and caller credentials are never forwarded (no
  token passthrough). Per-server credentials come from the platform's secret
  store: `credential_env` (local) or OAuth 2.1 client credentials (remote).
  OAuth discovers the server's authorization server (RFC 9728), only accepts
  the configured issuer, and requests tokens bound to that one server with a
  resource indicator (RFC 8707), so a token for one server is useless to any
  other. See docs/security/MCP_SECURITY.md.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import anyio
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from mcp import ClientSession, StdioServerParameters
from mcp.client.auth.extensions.client_credentials import ClientCredentialsOAuthProvider
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from mcp.types import TextContent
from opentelemetry.trace import SpanKind
from pydantic import BaseModel, ConfigDict, RootModel, model_validator

from aegistrace import tracing
from aegistrace.evidence.events import payload_digest
from aegistrace.tools.registry import RiskClass, ToolContext, ToolRegistry, ToolSpec

MAX_RESULT_CHARS = 64 * 1024
MAX_DESCRIPTION_CHARS = 1024
SAFE_ENV = ("PATH", "LANG", "LC_ALL", "TZ")


@dataclass(frozen=True)
class McpToolMapping:
    risk_class: RiskClass
    schema_digest: str  # pinned at approval time
    retry_safe: bool = False


@dataclass(frozen=True)
class McpOAuth:
    """OAuth 2.1 client credentials for a remote server (values from the platform secret store)."""

    issuer: str  # the only authorization server whose tokens we request
    client_id: str
    client_secret: str
    scope: str | None = None


@dataclass(frozen=True)
class McpServerConfig:
    server_id: str  # e.g. "notes"; tools are exposed as "mcp.<server_id>.<tool>"
    command: str = ""  # local server (stdio) ...
    args: tuple[str, ...] = ()
    tools: dict[str, McpToolMapping] = field(default_factory=dict)
    credential_env: dict[str, str] = field(default_factory=dict)  # resolved by the platform, never the caller
    timeout_seconds: float = 20.0
    cwd: str | None = None
    url: str = ""  # ... or remote server (Streamable HTTP endpoint); exactly one of command/url
    oauth: McpOAuth | None = None  # remote only
    allow_private_network: bool = False  # remote only: permit RFC 1918 / loopback destinations
    allow_insecure_http: bool = False  # remote only, development: plain http to a loopback address

    def __post_init__(self) -> None:
        if bool(self.command) == bool(self.url):
            raise ValueError("configure exactly one of command (local) or url (remote)")
        if self.oauth is not None and not self.url:
            raise ValueError("oauth applies to remote servers only")


class McpDestinationDenied(Exception):
    pass


def check_remote_url(cfg: McpServerConfig, resolve: Callable[[str], list[str]] | None = None) -> None:
    """Refuse destinations a remote MCP server must never be: wrong scheme, metadata/link-local, and
    (unless allowed for this server) private or loopback networks. Re-checked before every connection.
    The authoritative boundary is network egress control; this is defence in depth (see tools/egress.py)."""
    parts = urlsplit(cfg.url)
    host = (parts.hostname or "").rstrip(".").lower()
    if not host or parts.username or parts.password:
        raise McpDestinationDenied("invalid MCP server URL")
    addrs = (resolve or _resolve)(host)
    if not addrs:
        raise McpDestinationDenied(f"cannot resolve {host}")
    for raw in addrs:
        ip = ipaddress.ip_address(raw.split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise McpDestinationDenied(f"MCP server address not allowed: {ip}")
        if (ip.is_private or ip.is_loopback) and not (
            cfg.allow_private_network or (cfg.allow_insecure_http and ip.is_loopback)
        ):
            raise McpDestinationDenied(f"private address {ip} not allowed for server {cfg.server_id}")
    loopback_only = all(ipaddress.ip_address(a.split("%")[0]).is_loopback for a in addrs)
    if parts.scheme != "https" and not (parts.scheme == "http" and cfg.allow_insecure_http and loopback_only):
        raise McpDestinationDenied("remote MCP servers must use https")


def _resolve(host: str) -> list[str]:
    try:
        return list({ai[4][0] for ai in socket.getaddrinfo(host, None)})  # type: ignore[misc]
    except socket.gaierror:
        return []


class _MemoryTokens:
    """Per-server OAuth token cache (process memory only; never persisted or shared)."""

    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client = client_info


_token_stores: dict[str, _MemoryTokens] = {}


def _oauth(cfg: McpServerConfig) -> ClientCredentialsOAuthProvider | None:
    if cfg.oauth is None:
        return None
    store = _token_stores.setdefault(f"{cfg.server_id}|{cfg.url}|{cfg.oauth.client_id}", _MemoryTokens())
    return ClientCredentialsOAuthProvider(
        server_url=cfg.url,
        storage=store,
        client_id=cfg.oauth.client_id,
        client_secret=cfg.oauth.client_secret,
        scope=cfg.oauth.scope,
        issuer=cfg.oauth.issuer,
    )


@asynccontextmanager
async def _session(cfg: McpServerConfig) -> AsyncIterator[ClientSession]:
    if cfg.command:
        async with stdio_client(_params(cfg)) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            yield session
        return
    check_remote_url(cfg)
    async with (
        create_mcp_http_client(auth=_oauth(cfg)) as http,
        streamable_http_client(cfg.url, http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


class McpOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str
    truncated: bool


class McpToolError(Exception):
    pass


@dataclass(frozen=True)
class DiscoveredTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    schema_digest: str
    annotations: dict[str, Any] | None


def schema_digest(schema: dict[str, Any]) -> str:
    return payload_digest(schema)


def _env(cfg: McpServerConfig) -> dict[str, str]:
    env = {k: os.environ[k] for k in SAFE_ENV if k in os.environ}
    env.update(cfg.credential_env)
    return env


def _params(cfg: McpServerConfig) -> StdioServerParameters:
    return StdioServerParameters(command=cfg.command, args=list(cfg.args), env=_env(cfg), cwd=cfg.cwd)


async def _discover(cfg: McpServerConfig) -> list[DiscoveredTool]:
    with anyio.fail_after(cfg.timeout_seconds):
        async with _session(cfg) as session:
            result = await session.list_tools()
    out = []
    for t in result.tools:
        schema = dict(t.input_schema or {})
        ann = t.annotations.model_dump() if t.annotations is not None else None
        out.append(
            DiscoveredTool(t.name, (t.description or "")[:MAX_DESCRIPTION_CHARS], schema, schema_digest(schema), ann)
        )
    return out


def discover(cfg: McpServerConfig) -> list[DiscoveredTool]:
    return anyio.run(_discover, cfg)


async def _call(cfg: McpServerConfig, tool: str, arguments: dict[str, Any]) -> McpOutput:
    attrs = {
        "aegis.mcp.server": cfg.server_id,
        "aegis.mcp.tool": tool,
        "aegis.mcp.transport": "http" if cfg.url else "stdio",
    }
    with tracing.span("mcp.call_tool", attrs, kind=SpanKind.CLIENT):
        return await _call_inner(cfg, tool, arguments)


async def _call_inner(cfg: McpServerConfig, tool: str, arguments: dict[str, Any]) -> McpOutput:
    with anyio.fail_after(cfg.timeout_seconds):
        async with _session(cfg) as session:
            result = await session.call_tool(tool, arguments)
    text = "\n".join(c.text for c in result.content if isinstance(c, TextContent))
    if result.is_error:
        raise McpToolError("mcp tool reported an error")
    return McpOutput(text=text[:MAX_RESULT_CHARS], truncated=len(text) > MAX_RESULT_CHARS)


def _args_model(schema: dict[str, Any]) -> type[BaseModel]:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError("invalid tool input schema") from exc
    # Hardening: unless the pinned schema explicitly allows extra properties,
    # reject arguments the schema does not declare, so a model cannot smuggle
    # undeclared parameters to the server.
    if schema.get("type") == "object" and "additionalProperties" not in schema:
        schema = {**schema, "additionalProperties": False}
    validator = Draft202012Validator(schema)

    class Args(RootModel[dict[str, Any]]):
        @model_validator(mode="after")
        def _validate(self) -> Args:
            if next(validator.iter_errors(self.root), None) is not None:
                raise ValueError("arguments do not match the pinned schema")
            return self

    return Args


def _server_resource(server_id: str) -> Callable[[Any], dict[str, Any]]:
    return lambda _args: {"mcp_server": server_id}


@dataclass
class RegistrationReport:
    registered: list[str] = field(default_factory=list)
    ignored_unmapped: list[str] = field(default_factory=list)
    disabled_schema_changed: list[str] = field(default_factory=list)
    missing_on_server: list[str] = field(default_factory=list)


def register_server(
    registry: ToolRegistry, cfg: McpServerConfig, discovered: list[DiscoveredTool] | None = None
) -> RegistrationReport:
    tools = discovered if discovered is not None else discover(cfg)
    report = RegistrationReport()
    by_name = {t.name: t for t in tools}
    for name in sorted(by_name):
        if name not in cfg.tools:
            report.ignored_unmapped.append(name)
    for name, mapping in sorted(cfg.tools.items()):
        t = by_name.get(name)
        if t is None:
            report.missing_on_server.append(name)
            continue
        if t.schema_digest != mapping.schema_digest:
            report.disabled_schema_changed.append(name)
            continue

        def execute(ctx: ToolContext, args: Any, _tool: str = name) -> McpOutput:
            return anyio.run(_call, cfg, _tool, args.model_dump(mode="json"))

        registry.register(
            ToolSpec(
                name=f"mcp.{cfg.server_id}.{name}",
                description=f"[untrusted MCP description] {t.description}",
                risk_class=mapping.risk_class,
                args_model=_args_model(t.input_schema),
                output_model=McpOutput,
                execute=execute,
                retry_safe=mapping.retry_safe,
                resource_of=_server_resource(cfg.server_id),
            )
        )
        report.registered.append(name)
    return report
