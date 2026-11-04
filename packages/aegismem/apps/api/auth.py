"""API-key authentication, tenant resolution and scope authorization.

Keys look like ``aem_<id8>_<secret>``. Only a peppered HMAC-SHA256 of the full key is stored,
and the plaintext is shown once at creation. Every request resolves to a ``Principal``
(tenant + scopes). Authorization is a single router-level dependency that looks the route up in
``ROUTE_SCOPES`` and **fails closed** when a route is unmapped, so new endpoints cannot ship
unprotected.

Scopes:
    memory:read   retrieve, read memories, handoff, learning/trust views, receipts
    memory:write  ingest, update, feedback, corrections, confirmations, reflection, scans
    review        quarantine queue and decisions
    privacy       erasure (/forget), memory deletion, learning resets
    admin         API-key management and evaluation; implies every scope
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from adapters.relational_store.control_models import ApiKeyRecord
from adapters.relational_store.control_store import ControlStore
from apps.api.control import get_control_store
from core.config.settings import settings
from core.observability.metrics import AUTH_FAILURES, RATE_LIMITED
from apps.api.ratelimit import get_limiter, limits_for
from apps.api.routing import route_template

logger = logging.getLogger(__name__)

SCOPES = ("memory:read", "memory:write", "review", "privacy", "admin")
KEY_PREFIX = "aem_"

# (method, route path template) -> required scope. Paths are relative to /api/v1.
ROUTE_SCOPES: dict[tuple[str, str], str] = {
    ("POST", "/ingest"): "memory:write",
    ("POST", "/ingest/batch"): "memory:write",
    ("POST", "/retrieve"): "memory:read",
    ("GET", "/memories/{memory_id}"): "memory:read",
    ("POST", "/memories/list"): "memory:read",
    ("DELETE", "/memories/{memory_id}"): "privacy",
    ("POST", "/update"): "memory:write",
    ("POST", "/reflect"): "memory:write",
    ("POST", "/contradictions/scan"): "memory:write",
    ("GET", "/contradictions"): "memory:read",
    ("POST", "/handoff"): "memory:read",
    ("POST", "/feedback"): "memory:write",
    ("GET", "/learning/{user_id}"): "memory:read",
    ("DELETE", "/learning/{user_id}"): "privacy",
    ("POST", "/forget"): "privacy",
    ("GET", "/receipts/{receipt_id}"): "memory:read",
    ("POST", "/receipts/verify"): "memory:read",
    ("GET", "/quarantine/{user_id}"): "review",
    ("POST", "/quarantine/{memory_id}/release"): "review",
    ("POST", "/quarantine/{memory_id}/reject"): "review",
    ("POST", "/corrections"): "memory:write",
    ("POST", "/memories/{memory_id}/confirm"): "memory:write",
    ("GET", "/trust/sources"): "memory:read",
    ("GET", "/risk-model"): "memory:read",
    ("GET", "/stats"): "memory:read",
    ("GET", "/admin/audit"): "admin",
    ("POST", "/admin/keys"): "admin",
    ("GET", "/admin/keys"): "admin",
    ("DELETE", "/admin/keys/{key_id}"): "admin",
}
API_PREFIX = "/api/v1"


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    key_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    name: str = ""

    def has(self, scope: str) -> bool:
        return "admin" in self.scopes or scope in self.scopes


def hash_key(raw_key: str) -> str:
    pepper = (settings.api_key_pepper or settings.app_secret_key).encode("utf-8")
    return hmac.new(pepper, raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_key() -> tuple[str, str, str]:
    """Returns (key_id, plaintext_key, display_prefix)."""
    key_id = str(uuid.uuid4())
    raw = f"{KEY_PREFIX}{key_id[:8]}_{secrets.token_urlsafe(32)}"
    return key_id, raw, raw[:13]


async def issue_key(
    store: ControlStore, tenant_id: str, scopes: list[str], name: str = "",
) -> tuple[ApiKeyRecord, str]:
    unknown = set(scopes) - set(SCOPES)
    if unknown or not scopes:
        raise ValueError(f"invalid scopes: {sorted(unknown) or 'none given'}")
    key_id, raw, prefix = generate_key()
    record = ApiKeyRecord(key_id=key_id, tenant_id=tenant_id, name=name, key_prefix=prefix,
                          key_hash=hash_key(raw), scopes=sorted(set(scopes)))
    await store.create_api_key(record)
    return record, raw


def _extract_key(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key")


_last_touch: dict[str, float] = {}


async def get_principal(
    request: Request, store: Annotated[ControlStore, Depends(get_control_store)],
) -> Principal:
    if not settings.auth_enabled:
        return Principal(tenant_id=settings.default_tenant, key_id="dev", scopes=frozenset(SCOPES),
                         name="auth-disabled")
    raw = _extract_key(request)
    if not raw or not raw.startswith(KEY_PREFIX):
        AUTH_FAILURES.labels("missing_or_malformed").inc()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or malformed API key",
                            headers={"WWW-Authenticate": "Bearer"})
    record = await store.find_api_key(hash_key(raw))
    if record is None or record.revoked_at is not None:
        AUTH_FAILURES.labels("invalid_or_revoked").inc()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or revoked API key",
                            headers={"WWW-Authenticate": "Bearer"})
    now = time.monotonic()
    if now - _last_touch.get(record.key_id, 0) > 60:  # bound write amplification
        _last_touch[record.key_id] = now
        await store.touch_api_key(record.key_id)
    return Principal(tenant_id=record.tenant_id, key_id=record.key_id,
                     scopes=frozenset(record.scopes or []), name=record.name)


async def authorize(
    request: Request, principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    path = route_template(request) or request.url.path
    rel = path[len(API_PREFIX):] if path.startswith(API_PREFIX) else path
    scope = ROUTE_SCOPES.get((request.method, rel))
    if scope is None:
        logger.error(f"Unmapped route {request.method} {rel}: denied (fail closed)")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "route has no authorization policy")
    if not principal.has(scope):
        AUTH_FAILURES.labels("insufficient_scope").inc()
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"API key lacks scope '{scope}'")
    limiter = get_limiter()
    if limiter is not None:
        cls, rate, burst = limits_for(scope)
        decision = await limiter.hit(f"{principal.tenant_id}:{cls}", rate, burst)
        if not decision.allowed:
            RATE_LIMITED.labels(cls).inc()
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"rate limit exceeded ({cls})",
                                headers={"Retry-After": str(decision.retry_after_s),
                                         "X-RateLimit-Limit": str(rate)})
    request.state.principal = principal
    return principal


async def require_admin(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
    if not principal.has("admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin scope required")
    return principal
