# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""A remote (Streamable HTTP) MCP server protected by OAuth 2.1, and the
authorization server that issues its tokens, served on loopback for tests.

The MCP server only accepts tokens issued for its own resource URL (RFC 8707),
so a token for any other server is refused. The authorization server records
every token request so tests can check caching, the resource indicator, and
that client secrets never reach the MCP server."""

from __future__ import annotations

import base64
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class AuthServer:
    issuer: str
    clients: dict[str, str]  # client_id -> secret
    tokens: dict[str, dict[str, Any]] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)

    def app(self) -> Starlette:
        async def metadata(_: Request) -> JSONResponse:
            return JSONResponse(
                {
                    "issuer": self.issuer,
                    "token_endpoint": self.issuer + "/token",
                    "grant_types_supported": ["client_credentials"],
                    "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
                    "response_types_supported": ["code"],
                    "authorization_endpoint": self.issuer + "/authorize",
                }
            )

        async def token(req: Request) -> JSONResponse:
            form = dict(await req.form())
            cid, secret = form.get("client_id"), form.get("client_secret")
            auth = req.headers.get("authorization", "")
            if auth.startswith("Basic "):
                from urllib.parse import unquote

                cid, _, secret = base64.b64decode(auth[6:]).decode().partition(":")
                cid, secret = unquote(cid), unquote(secret)
            self.requests.append({**form, "client_id": cid})
            if form.get("grant_type") != "client_credentials" or self.clients.get(str(cid)) != secret:
                return JSONResponse({"error": "invalid_client"}, status_code=401)
            if not form.get("resource"):
                return JSONResponse({"error": "invalid_target", "error_description": "resource required"}, 400)
            tok = "at_" + secrets.token_urlsafe(24)
            self.tokens[tok] = {
                "resource": form["resource"],
                "client_id": cid,
                "scopes": str(form.get("scope", "")).split(),
                "exp": int(time.time()) + 300,
            }
            return JSONResponse({"access_token": tok, "token_type": "Bearer", "expires_in": 300})

        return Starlette(
            routes=[
                Route("/.well-known/oauth-authorization-server", metadata),
                Route("/token", token, methods=["POST"]),
            ]
        )


class Verifier:
    def __init__(self, auth: AuthServer) -> None:
        self.auth = auth

    async def verify_token(self, token: str) -> AccessToken | None:
        t = self.auth.tokens.get(token)
        if t is None or t["exp"] < time.time():
            return None
        return AccessToken(
            token=token, client_id=t["client_id"], scopes=t["scopes"], expires_at=t["exp"], resource=t["resource"]
        )


def mcp_app(auth: AuthServer, resource: str) -> Any:
    server = MCPServer(
        "remote-notes",
        token_verifier=Verifier(auth),
        auth=AuthSettings(
            issuer_url=auth.issuer,
            resource_server_url=resource,
            required_scopes=["notes:read"],
            validate_token_resource=True,
        ),
    )

    @server.tool(description="Read team notes")
    def read_notes(topic: str) -> str:
        return f"Remote notes on {topic}: ship on Friday."

    return server.streamable_http_app()


class Served:
    """Run an ASGI app with uvicorn in a background thread on 127.0.0.1."""

    def __init__(self, app: Any, port: int) -> None:
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> Served:
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("server did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *_: Any) -> None:
        self.server.should_exit = True
        self.thread.join(5)
