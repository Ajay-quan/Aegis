# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
from __future__ import annotations


class AegisError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message


class AuthenticationError(AegisError): ...


class PermissionDeniedError(AegisError): ...


class NotFoundError(AegisError): ...


class ConflictError(AegisError): ...


class ValidationError(AegisError): ...


class RateLimitedError(AegisError): ...


class ServiceUnavailableError(AegisError): ...


_BY_STATUS: dict[int, type[AegisError]] = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    429: RateLimitedError,
    503: ServiceUnavailableError,
}


def from_response(status: int, body: object) -> AegisError:
    err = body.get("error", {}) if isinstance(body, dict) else {}
    cls = _BY_STATUS.get(status, AegisError)
    return cls(status, str(err.get("code", "error")), str(err.get("message", "request failed")))
