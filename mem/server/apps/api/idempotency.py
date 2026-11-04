"""Idempotency-Key support for state-creating endpoints (Stripe semantics).

* First request with a key: executed; its response (2xx or 4xx) is stored.
* Same key + same request: the stored response is returned with ``Idempotent-Replayed: true``.
* Same key + different request: 422.
* Same key while the first is still executing: 409 with ``Retry-After``.
* Server errors (5xx / unexpected exceptions) release the key so the client can retry.
"""
from __future__ import annotations

import hashlib
from typing import Any, Awaitable, Callable

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from adapters.relational_store.control_store import ControlStore
from apps.api.routing import route_template

HEADER = "idempotency-key"


async def run_idempotent(
    request: Request, tenant_id: str, control: ControlStore,
    handler: Callable[[], Awaitable[Any]], status_code: int = 200,
) -> Any:
    key = request.headers.get(HEADER)
    if not key:
        return await handler()
    if len(key) > 255:
        raise HTTPException(422, "Idempotency-Key too long (max 255)")

    route = route_template(request) or request.url.path
    body_hash = hashlib.sha256(await request.body() + request.url.query.encode()).hexdigest()
    outcome, rec = await control.claim_idempotency(tenant_id, key, route, body_hash)

    if outcome == "replay":
        return JSONResponse(rec.response, status_code=rec.status_code,
                            headers={"Idempotent-Replayed": "true"})
    if outcome == "conflict":
        raise HTTPException(422, "Idempotency-Key was already used with a different request")
    if outcome == "in_flight":
        raise HTTPException(409, "A request with this Idempotency-Key is in progress",
                            headers={"Retry-After": "1"})

    try:
        result = await handler()
    except HTTPException as e:
        if e.status_code >= 500:
            await control.release_idempotency(tenant_id, key)
        else:  # deterministic client error: replay it too
            await control.complete_idempotency(tenant_id, key, e.status_code, {"detail": e.detail})
        raise
    except Exception:
        await control.release_idempotency(tenant_id, key)
        raise
    content = jsonable_encoder(result)
    await control.complete_idempotency(tenant_id, key, status_code, content)
    return JSONResponse(content, status_code=status_code)
