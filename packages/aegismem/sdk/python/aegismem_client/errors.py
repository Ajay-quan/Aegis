"""Typed errors mapped from HTTP status codes."""
from __future__ import annotations

from typing import Any


class AegisMemError(Exception):
    def __init__(self, message: str, status: int | None = None, body: Any = None,
                 request_id: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.request_id = request_id

    def __str__(self) -> str:
        rid = f" (request_id={self.request_id})" if self.request_id else ""
        return f"{self.args[0]}{rid}"


class AuthenticationError(AegisMemError):
    """401: missing, malformed or revoked API key."""


class PermissionDeniedError(AegisMemError):
    """403: the key lacks the scope this call requires."""


class NotFoundError(AegisMemError):
    """404: does not exist, or belongs to another tenant (indistinguishable by design)."""


class ValidationError(AegisMemError):
    """409/422: the request was understood but rejected."""


class RateLimitedError(AegisMemError):
    """429: slow down; retried automatically for idempotent calls."""


class ServerError(AegisMemError):
    """5xx: retried automatically for idempotent calls."""


def error_for(status: int, message: str, body: Any, request_id: str | None) -> AegisMemError:
    cls = {401: AuthenticationError, 403: PermissionDeniedError, 404: NotFoundError,
           409: ValidationError, 422: ValidationError, 429: RateLimitedError}.get(status)
    if cls is None:
        cls = ServerError if status >= 500 else AegisMemError
    return cls(message, status=status, body=body, request_id=request_id)
