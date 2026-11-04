"""Official Python client for AegisMem.

    from aegismem_client import AegisMem

    async with AegisMem(base_url="https://api.aegismem.example", api_key="aem_...") as mem:
        w = await mem.ingest("User prefers aisle seats", user_id="u1")
        r = await mem.retrieve("seat preference", user_id="u1")
        await mem.feedback(r.retrieval_id, user_id="u1", used=[r.results[0].memory_id])
        packet = await mem.handoff(user_id="u1", task="book a flight", token_budget=800)

A blocking wrapper is available as ``AegisMemSync``.
"""
from aegismem_client.client import AegisMem, AegisMemSync
from aegismem_client.errors import (
    AegisMemError, AuthenticationError, NotFoundError, PermissionDeniedError,
    RateLimitedError, ServerError, ValidationError,
)

__all__ = [
    "AegisMem", "AegisMemSync", "AegisMemError", "AuthenticationError", "NotFoundError",
    "PermissionDeniedError", "RateLimitedError", "ServerError", "ValidationError",
]
__version__ = "0.1.0"
