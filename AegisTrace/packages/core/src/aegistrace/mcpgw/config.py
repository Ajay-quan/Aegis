# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Load administrator-configured MCP servers (AEGIS_MCP_SERVERS_FILE, YAML).

Secrets never appear in the file: it names environment variables, which the
platform's secret store populates (`client_secret_env`, `credential_env`).

    servers:
      - id: notes
        url: https://mcp.example.com/mcp
        oauth: {issuer: https://auth.example.com, client_id: aegistrace, client_secret_env: NOTES_MCP_SECRET,
                scope: notes:read}
        tools:
          read_notes: {risk_class: 1, schema_digest: "sha256:...", retry_safe: true}
      - id: files
        command: /usr/local/bin/files-mcp
        args: [--readonly]
        credential_env: {FILES_TOKEN: FILES_MCP_TOKEN}   # child env name: platform env var holding the value
        tools:
          list_files: {risk_class: 1, schema_digest: "sha256:..."}

Pin schema digests with `aegistrace mcp discover` (prints each tool's digest).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from aegistrace.tools.registry import RiskClass, ToolRegistry

from .bridge import McpOAuth, McpServerConfig, McpToolMapping, register_server

log = logging.getLogger(__name__)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Tool(_Strict):
    risk_class: int = Field(ge=0, le=4)
    schema_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    retry_safe: bool = False


class _OAuth(_Strict):
    issuer: str
    client_id: str
    client_secret_env: str
    scope: str | None = None


class _Server(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    oauth: _OAuth | None = None
    credential_env: dict[str, str] = Field(default_factory=dict)
    allow_private_network: bool = False
    allow_insecure_http: bool = False
    timeout_seconds: float = Field(default=20.0, gt=0, le=300)
    tools: dict[str, _Tool] = Field(default_factory=dict)


class _File(_Strict):
    servers: list[_Server] = Field(default_factory=list)


def _secret(env: Mapping[str, str], name: str, server: str) -> str:
    value = env.get(name)
    if not value:
        raise ValueError(f"MCP server {server}: environment variable {name} is not set")
    return value


def load_servers(path: str, env: Mapping[str, str]) -> list[McpServerConfig]:
    doc = _File.model_validate(yaml.safe_load(Path(path).read_text()) or {})
    out = []
    for s in doc.servers:
        oauth = (
            McpOAuth(s.oauth.issuer, s.oauth.client_id, _secret(env, s.oauth.client_secret_env, s.id), s.oauth.scope)
            if s.oauth
            else None
        )
        out.append(
            McpServerConfig(
                s.id,
                command=s.command,
                args=tuple(s.args),
                tools={
                    n: McpToolMapping(RiskClass(t.risk_class), t.schema_digest, t.retry_safe)
                    for n, t in s.tools.items()
                },
                credential_env={k: _secret(env, v, s.id) for k, v in s.credential_env.items()},
                timeout_seconds=s.timeout_seconds,
                url=s.url,
                oauth=oauth,
                allow_private_network=s.allow_private_network,
                allow_insecure_http=s.allow_insecure_http,
            )
        )
    return out


def register_from_env(registry: ToolRegistry, env: Mapping[str, str]) -> dict[str, Any]:
    """Register every configured server's mapped tools. A server that is down or whose schemas
    changed is reported and skipped; it never prevents startup or exposes unmapped tools."""
    path = env.get("AEGIS_MCP_SERVERS_FILE")
    if not path:
        return {}
    report: dict[str, Any] = {}
    for cfg in load_servers(path, env):
        try:
            rep = register_server(registry, cfg)
            report[cfg.server_id] = rep.__dict__
            if rep.disabled_schema_changed or rep.missing_on_server:
                log.warning("mcp server tools not registered", extra={"server": cfg.server_id, **rep.__dict__})
        except Exception as exc:  # noqa: BLE001 - one bad server must not stop the platform
            log.error("mcp server unavailable", extra={"server": cfg.server_id, "error": type(exc).__name__})
            report[cfg.server_id] = {"error": type(exc).__name__}
    return report
