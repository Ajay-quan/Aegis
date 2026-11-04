# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""JWT access-token validation.

Issuer, audience, signature (JWKS, asymmetric algorithms only), expiry,
not-before, and required claims are all enforced. The tenant comes only from
a signed claim, never from the request body or path (INV-003).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWK

TENANT_CLAIM = "aegis_tenant"
ALLOWED_ALGORITHMS = ["RS256", "ES256", "EdDSA"]


class AuthError(Exception):
    """Authentication failed. The message is safe to log but not to return."""


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    scopes: frozenset[str]
    kind: str  # "user" | "service"
    token_id: str | None

    def has(self, scope: str) -> bool:
        return scope in self.scopes


class JwksCache:
    """Fetches a JWKS and refreshes on unknown kid, at most once per min_refresh seconds."""

    def __init__(self, source: str | Callable[[], dict[str, Any]], min_refresh: float = 60.0) -> None:
        self._source = source
        self._min_refresh = min_refresh
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        if callable(self._source):
            return self._source()
        if self._source.startswith("https://") or self._source.startswith("http://"):
            r = httpx.get(self._source, timeout=5.0)
            r.raise_for_status()
            return dict(r.json())
        with open(self._source) as fh:
            return dict(json.load(fh))

    def _refresh(self) -> None:
        doc = self._load()
        self._keys = {k["kid"]: PyJWK(k) for k in doc.get("keys", []) if "kid" in k}
        self._fetched_at = time.monotonic()

    def get(self, kid: str) -> PyJWK:
        with self._lock:
            if kid not in self._keys and time.monotonic() - self._fetched_at >= self._min_refresh:
                self._refresh()
            if not self._keys and self._fetched_at == 0.0:
                self._refresh()
            key = self._keys.get(kid)
        if key is None:
            raise AuthError("unknown signing key")
        return key


class TokenValidator:
    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks: JwksCache,
        leeway: int = 30,
        is_revoked: Callable[[str], bool] | None = None,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.jwks = jwks
        self.leeway = leeway
        self.is_revoked = is_revoked or (lambda _jti: False)

    def validate(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise AuthError("malformed token") from exc
        alg = header.get("alg")
        if alg not in ALLOWED_ALGORITHMS:
            raise AuthError(f"algorithm not allowed: {alg}")
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise AuthError("missing kid")
        key = self.jwks.get(kid)
        try:
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=[alg],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid token: {type(exc).__name__}") from exc
        tenant = claims.get(TENANT_CLAIM)
        if not isinstance(tenant, str):
            raise AuthError("missing tenant claim")
        jti = claims.get("jti")
        if isinstance(jti, str) and self.is_revoked(jti):
            raise AuthError("token revoked")
        scope = claims.get("scope", "")
        kind = "service" if claims.get("client_kind") == "service" else "user"
        return Principal(
            str(claims["sub"]), tenant, frozenset(str(scope).split()), kind, jti if isinstance(jti, str) else None
        )
