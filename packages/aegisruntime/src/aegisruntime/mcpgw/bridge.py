# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""MCP server bridge (stdio transport).

Trust model:
- An MCP server is untrusted. Its tool names, descriptions, annotations
  (e.g. readOnlyHint), schemas, and results are data, never authority.
- A tool is exposed only if an administrator mapped it in McpServerConfig,
  with a platform-assigned risk class. Unmapped tools are invisible.
- The input schema is pinned by digest at approval time. If the server later
  advertises a different schema (a "rug pull"), the tool is disabled.
- Each call uses a fresh server process with an explicit, minimal
  environment. AegisTrace and caller credentials are never forwarded (no
  token passthrough); per-server credentials, if any, come from the
  platform's secret store via `credential_env`.

Not yet supported: remote (Streamable HTTP) MCP servers and their OAuth
flows. See docs/security/MCP_SECURITY.md.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import anyio
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent
from pydantic import BaseModel, ConfigDict, RootModel, model_validator

from aegisruntime.tools.registry import RiskClass, ToolContext, ToolRegistry, ToolSpec
from aegistrace.evidence.events import payload_digest

MAX_RESULT_CHARS = 64 * 1024
MAX_DESCRIPTION_CHARS = 1024
SAFE_ENV = ("PATH", "LANG", "LC_ALL", "TZ")


@dataclass(frozen=True)
class McpToolMapping:
    risk_class: RiskClass
    schema_digest: str  # pinned at approval time
    retry_safe: bool = False


@dataclass(frozen=True)
class McpServerConfig:
    server_id: str  # e.g. "notes"; tools are exposed as "mcp.<server_id>.<tool>"
    command: str
    args: tuple[str, ...] = ()
    tools: dict[str, McpToolMapping] = field(default_factory=dict)
    credential_env: dict[str, str] = field(default_factory=dict)  # resolved by the platform, never the caller
    timeout_seconds: float = 20.0
    cwd: str | None = None


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
        async with stdio_client(_params(cfg)) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
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
    with anyio.fail_after(cfg.timeout_seconds):
        async with stdio_client(_params(cfg)) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
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
