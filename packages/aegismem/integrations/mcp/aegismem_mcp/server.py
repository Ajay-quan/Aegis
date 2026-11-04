"""AegisMem MCP server (stdio transport, JSON-RPC 2.0).

Exposes governed memory as MCP tools. Every call goes through the AegisMem API, so auth,
tenant isolation, quarantine and the read-time integrity guard all apply.

    {"mcpServers": {"aegismem": {
        "command": "python", "args": ["-m", "aegismem_mcp"],
        "env": {"AEGISMEM_BASE_URL": "https://...", "AEGISMEM_API_KEY": "aem_...",
                "AEGISMEM_USER_ID": "user-123"}}}}

Logs go to stderr; stdout carries protocol messages only.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

from aegismem_client import AegisMem, AegisMemError
from aegismem_client.tools import TOOL_NAMES, TOOLS, ToolExecutor

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
log = logging.getLogger("aegismem_mcp")

class McpServer(ToolExecutor):
    """MCP protocol handling on top of the shared ToolExecutor."""

    async def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:  # notification (e.g. notifications/initialized): never answered
            return None
        try:
            if method == "initialize":
                requested = (msg.get("params") or {}).get("protocolVersion")
                version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
                result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "aegismem", "version": "0.1.0"},
                          "instructions": "Governed long-term memory. Call 'handoff' at session start, "
                                          "'recall' before answering personal questions, and mark tool "
                                          "or web content with source='tool' when remembering it."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = msg.get("params") or {}
                name, args = params.get("name"), params.get("arguments") or {}
                if name not in TOOL_NAMES:
                    return _error(mid, -32602, f"unknown tool: {name}")
                try:
                    text, is_error = await self.call_tool(name, args), False
                except (AegisMemError, ValueError, KeyError) as e:
                    text, is_error = f"{type(e).__name__}: {e}", True  # tool-level error, visible to the model
                result = {"content": [{"type": "text", "text": text}], "isError": is_error}
            else:
                return _error(mid, -32601, f"method not found: {method}")
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except Exception as e:  # noqa: BLE001
            log.exception("internal error")
            return _error(mid, -32603, f"internal error: {type(e).__name__}")


def _error(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


async def serve_stdio(server: McpServer) -> None:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    while line := await reader.readline():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = _error(None, -32700, "parse error")
        else:
            resp = await server.handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=os.environ.get("AEGISMEM_LOG_LEVEL", "WARNING"))

    async def run() -> None:
        async with AegisMem() as client:  # reads AEGISMEM_BASE_URL / AEGISMEM_API_KEY
            await serve_stdio(McpServer(client, os.environ.get("AEGISMEM_USER_ID")))
    asyncio.run(run())
