"""HTTP hardening middleware for the AegisMem API.

Authentication, scopes and rate limits live in ``apps/api/auth.py`` (scoped API keys, Redis-backed
per-tenant buckets). This module adds the transport-level protections around them:

1. **Security headers** on every response; ``Cache-Control: no-store`` on API routes.
2. **Request size limit**: oversized bodies are rejected with 413 before JSON parsing.
3. **Audit trail**: every mutating API call is recorded durably (control plane, tenant-scoped)
   with the resolved principal, method, route template and status.
4. **Error envelope**: ``{"error": {"code", "message", "request_id"}}`` for middleware rejections.
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from apps.api.routing import route_template
from core.config import settings

logger = logging.getLogger("aegismem.audit")

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


def error_json(status_code: int, code: str, message: str, request_id: str = "", **headers: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers={k.replace("_", "-"): v for k, v in headers.items()},
    )


def install_security(app) -> None:
    """Attach hardening middleware (registered inner-to-outer)."""

    @app.middleware("http")
    async def audit_mutations(request: Request, call_next):
        response = await call_next(request)
        principal = getattr(request.state, "principal", None)
        if request.method in _MUTATING and request.url.path.startswith("/api/") and principal is not None:
            route = route_template(request) or request.url.path
            entry = {"tenant_id": principal.tenant_id, "key_id": principal.key_id,
                     "principal": principal.name, "method": request.method, "route": route,
                     "status": response.status_code}
            logger.info("audit", extra=entry)
            try:
                from apps.api.control import get_control_store
                provider = app.dependency_overrides.get(get_control_store, get_control_store)
                store = provider()
                if hasattr(store, "__await__"):
                    store = await store
                await store.record_audit(**entry)
            except Exception as e:  # auditing must never fail the request
                logger.error(f"audit write failed: {e}")
        return response

    @app.middleware("http")
    async def limit_body_size(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_request_bytes:
            return error_json(413, "payload_too_large",
                              f"request body exceeds {settings.max_request_bytes} bytes")
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
