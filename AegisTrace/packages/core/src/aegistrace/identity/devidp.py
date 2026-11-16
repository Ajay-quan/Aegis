# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Development-only OpenID Connect provider, so the dashboard's real sign-in
flow (authorization code + PKCE) can be exercised locally without an external
identity provider. Production deployments point the dashboard at their own
provider (Okta, Entra ID, Google Workspace, Keycloak, ...) instead.

Never run in production: it signs tokens with the dev issuer key and lets
anyone pick a dev user. It enforces the parts of the protocol a client could
get wrong, so the dashboard is tested against them: exact redirect URIs,
PKCE S256, single-use codes that expire, and client id binding.

Run: aegistrace-dev-idp (env below), or uvicorn aegistrace.identity.devidp:app.
"""

from __future__ import annotations

import base64
import hashlib
import html
import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .devissuer import DevIssuer

CODE_TTL = 60
TOKEN_TTL = 8 * 3600
ADMIN_SCOPES = [
    "agents:read",
    "agents:write",
    "runs:read",
    "runs:write",
    "runs:reconcile",
    "policies:write",
    "receipts:export",
    "approvals:read",
    "approvals:decide",
    "replay:read",
    "replay:fork",
    "payloads:read",
    "data:erase",
    "audit:read",
]
AUDITOR_SCOPES = ["runs:read", "receipts:export", "replay:read", "audit:read"]
USERS: dict[str, tuple[str, list[str]]] = {
    "usr_dev_admin": ("Dev admin (full access)", ADMIN_SCOPES),
    "usr_dev_auditor": ("Dev auditor (read-only evidence)", AUDITOR_SCOPES),
}


@dataclass(frozen=True)
class Config:
    issuer: DevIssuer
    public_url: str  # what the browser uses (authorization endpoint)
    client_id: str
    redirect_uris: frozenset[str]
    tenant_id: str


@dataclass(frozen=True)
class _Code:
    sub: str
    client_id: str
    redirect_uri: str
    challenge: str
    expires: float


_CSS = """
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0d12;color:#e8eaef;
  font:15px system-ui,sans-serif}
main{width:min(380px,92vw)}h1{font-size:20px;margin:0 0 6px}p{color:#a3a9b6;margin:0 0 18px}
.warn{background:#3a2a0b;color:#f5c66b;border-radius:8px;padding:8px 12px;font-size:13px;margin-bottom:18px}
button{display:flex;flex-direction:column;align-items:flex-start;gap:2px;width:100%;margin-bottom:10px;
  padding:12px 14px;border-radius:10px;border:1px solid #262a33;background:#161920;color:#e8eaef;
  font:600 15px system-ui;cursor:pointer}
button:hover{border-color:#3ecf8e}small{font:12px ui-monospace,monospace;color:#a3a9b6}
"""


def _s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="AegisTrace dev identity provider (development only)", docs_url=None, redoc_url=None)
    codes: dict[str, _Code] = {}
    lock = threading.Lock()

    def check_client(client_id: str, redirect_uri: str) -> None:
        # Never redirect to an unregistered URI: show the error here instead.
        if client_id != cfg.client_id or redirect_uri not in cfg.redirect_uris:
            raise HTTPException(400, "unknown client or redirect_uri")

    @app.get("/.well-known/openid-configuration")
    def discovery(request: Request) -> dict[str, Any]:
        # The browser reaches /authorize at the public URL; servers reach /token
        # at whatever address they fetched this document from (e.g. a compose
        # service name), so back-channel endpoints follow the request.
        here = str(request.base_url).rstrip("/")
        return {
            "issuer": cfg.issuer.issuer,
            "authorization_endpoint": cfg.public_url + "/authorize",
            "token_endpoint": here + "/token",
            "jwks_uri": here + "/jwks",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
        }

    @app.get("/jwks")
    def jwks() -> dict[str, Any]:
        return cfg.issuer.jwks()

    @app.get("/authorize", response_class=HTMLResponse)
    def authorize(
        client_id: str,
        redirect_uri: str,
        state: str = Query(min_length=16, max_length=256),
        code_challenge: str = Query(min_length=43, max_length=128),
        code_challenge_method: str = "plain",
        response_type: str = "code",
    ) -> str:
        check_client(client_id, redirect_uri)
        if response_type != "code" or code_challenge_method != "S256":
            raise HTTPException(400, "only response_type=code with PKCE S256 is supported")
        hidden = "".join(
            f'<input type="hidden" name="{k}" value="{html.escape(v)}">'
            for k, v in {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": code_challenge,
            }.items()
        )
        buttons = "".join(
            f'<button name="sub" value="{sub}">{html.escape(label)}<small>{sub}</small></button>'
            for sub, (label, _) in USERS.items()
        )
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Dev sign-in</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{_CSS}</style></head><body><main>
<h1>Sign in to AegisTrace</h1><p>Tenant <code>{html.escape(cfg.tenant_id)}</code></p>
<div class="warn">Development identity provider. In production this is your company's sign-in.</div>
<form method="post" action="/authorize">{hidden}{buttons}</form></main></body></html>"""

    @app.post("/authorize")
    def approve(
        client_id: str = Form(),
        redirect_uri: str = Form(),
        state: str = Form(),
        code_challenge: str = Form(),
        sub: str = Form(),
    ) -> RedirectResponse:
        check_client(client_id, redirect_uri)
        if sub not in USERS:
            raise HTTPException(400, "unknown user")
        code = secrets.token_urlsafe(32)
        with lock:
            now = time.time()
            for k in [k for k, v in codes.items() if v.expires < now]:
                del codes[k]
            codes[code] = _Code(sub, client_id, redirect_uri, code_challenge, now + CODE_TTL)
        return RedirectResponse(redirect_uri + "?" + urlencode({"code": code, "state": state}), status_code=303)

    @app.post("/token")
    def token(
        grant_type: str = Form(),
        code: str = Form(),
        redirect_uri: str = Form(),
        client_id: str = Form(),
        code_verifier: str = Form(min_length=43, max_length=128),
    ) -> JSONResponse:
        with lock:
            c = codes.pop(code, None)  # single use, even when the exchange below fails
        if (
            grant_type != "authorization_code"
            or c is None
            or c.expires < time.time()
            or c.client_id != client_id
            or c.redirect_uri != redirect_uri
            or not secrets.compare_digest(_s256(code_verifier), c.challenge)
        ):
            return JSONResponse({"error": "invalid_grant"}, status_code=400, headers={"Cache-Control": "no-store"})
        _, scopes = USERS[c.sub]
        access = cfg.issuer.mint(c.sub, cfg.tenant_id, scopes, ttl=TOKEN_TTL)
        return JSONResponse(
            {"access_token": access, "token_type": "Bearer", "expires_in": TOKEN_TTL, "scope": " ".join(scopes)},
            headers={"Cache-Control": "no-store"},
        )

    return app


def config_from_env() -> Config:
    e = os.environ
    return Config(
        issuer=DevIssuer.load(Path(e.get("AEGIS_DEV_IDP_KEYS", "/run/aegis"))),
        public_url=e.get("AEGIS_DEV_IDP_PUBLIC_URL", "http://localhost:9000").rstrip("/"),
        client_id=e.get("AEGIS_DEV_IDP_CLIENT_ID", "aegistrace-dashboard"),
        redirect_uris=frozenset(
            u for u in e.get("AEGIS_DEV_IDP_REDIRECT_URIS", "http://localhost:3000/auth/callback").split(",") if u
        ),
        tenant_id=e.get("AEGIS_DEV_IDP_TENANT", "tnt_demo"),
    )


def main() -> None:
    import uvicorn

    # Listens on all interfaces inside its container; compose publishes it on 127.0.0.1 only.
    host = os.environ.get("AEGIS_DEV_IDP_HOST", "0.0.0.0")  # noqa: S104
    uvicorn.run(create_app(config_from_env()), host=host, port=int(os.environ.get("AEGIS_DEV_IDP_PORT", "9000")))
