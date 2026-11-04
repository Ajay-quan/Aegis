# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""AegisTrace Python SDK."""

from .client import AegisClient, AsyncAegisClient
from .errors import (
    AegisError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    ServiceUnavailableError,
    ValidationError,
)

__all__ = [
    "AegisClient",
    "AsyncAegisClient",
    "AegisError",
    "AuthenticationError",
    "ConflictError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitedError",
    "ServiceUnavailableError",
    "ValidationError",
]
__version__ = "0.1.0"
