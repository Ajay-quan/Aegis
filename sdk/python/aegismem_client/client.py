"""Async and sync AegisMem clients.

Retry policy: reads, verification and feedback (de-duplicated by retrieval_id) are retried on
connection errors, 429 and 5xx with exponential backoff and jitter, honouring ``Retry-After``.
State-creating writes (ingest, batch, corrections, forget) carry an auto-generated
``Idempotency-Key`` that stays the same across retries, so the server executes them at most
once and they are retried too. Writes without server-side idempotency (confirm, release,
reject) are retried only when the connection failed before sending.
"""
from __future__ import annotations

import asyncio
import os
import random
import uuid
from typing import Any, Literal

import httpx

from aegismem_client import models as m
from aegismem_client.errors import AegisMemError, error_for

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=3.0)


def _new_key() -> str:
    return f"sdk-{uuid.uuid4()}"
USER_AGENT = "aegismem-python/0.1.0"


class AegisMem:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base = (base_url or os.environ.get("AEGISMEM_BASE_URL", "http://localhost:8000")).rstrip("/")
        key = api_key or os.environ.get("AEGISMEM_API_KEY")
        headers = {"User-Agent": USER_AGENT}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self.max_retries = max_retries
        self._http = httpx.AsyncClient(base_url=f"{self._base}/api/v1", headers=headers,
                                       timeout=timeout, transport=transport)

    async def __aenter__(self) -> "AegisMem":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------
    # transport
    # ------------------------------------------------------------------

    async def _request(self, method: str, path: str, *, idempotent: bool,
                       json: Any = None, params: dict[str, Any] | None = None,
                       idempotency_key: str | None = None) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        idempotent = idempotent or idempotency_key is not None
        attempt = 0
        while True:
            try:
                resp = await self._http.request(method, path, json=json, params=params, headers=headers)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                # Never reached the server: safe to retry any call.
                if attempt >= self.max_retries:
                    raise AegisMemError(f"connection failed: {e}") from e
            except httpx.TransportError as e:
                # May have reached the server: only idempotent calls are retried.
                if not idempotent or attempt >= self.max_retries:
                    raise AegisMemError(f"transport error: {e}") from e
            else:
                if resp.status_code == 409 and idempotency_key and attempt < self.max_retries:
                    await asyncio.sleep(float(resp.headers.get("retry-after", "1")))
                    attempt += 1
                    continue  # same key still executing on the server
                if resp.status_code < 400:
                    return resp.json() if resp.content else None
                retryable = resp.status_code == 429 or resp.status_code >= 500
                if not (retryable and idempotent and attempt < self.max_retries):
                    raise self._error(resp)
                retry_after = resp.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    await asyncio.sleep(min(float(retry_after), 30.0))
                    attempt += 1
                    continue
            await asyncio.sleep(min(8.0, 0.25 * 2 ** attempt) * (0.5 + random.random()))
            attempt += 1

    @staticmethod
    def _error(resp: httpx.Response) -> AegisMemError:
        try:
            body = resp.json()
            detail = body.get("detail", body) if isinstance(body, dict) else body
        except ValueError:
            body, detail = resp.text, resp.text
        return error_for(resp.status_code, f"{resp.status_code}: {detail}", body,
                         resp.headers.get("x-request-id"))

    # ------------------------------------------------------------------
    # memory
    # ------------------------------------------------------------------

    async def ingest(
        self, text: str, user_id: str, *, session_id: str = "", agent_id: str = "",
        memory_type: str = "observation",
        source_type: Literal["user_message", "agent_observation", "tool_output", "ingestion",
                             "reflection", "system"] = "user_message",
        origin: str | None = None, metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None, event_time: str | None = None,
    ) -> m.WriteResult:
        """Store a memory. Pass ``origin`` (e.g. ``"tool:web_search"``, ``"domain:example.com"``)
        so trust can be learned per origin. Check ``result.quarantined``."""
        meta = dict(metadata or {})
        if origin:
            meta["origin"] = origin
        body = {"text": text, "user_id": user_id, "session_id": session_id, "agent_id": agent_id,
                "memory_type": memory_type, "source_type": source_type, "metadata": meta,
                "event_time": event_time}
        return m.WriteResult(**await self._request("POST", "/ingest", json=body, idempotent=False,
                                                   idempotency_key=idempotency_key or _new_key()))

    async def retrieve(self, query: str, user_id: str, *, top_k: int = 5, namespace: str = "",
                       memory_types: list[str] | None = None, min_importance: float = 0.0) -> m.RetrieveResult:
        body = {"query": query, "user_id": user_id, "top_k": top_k, "namespace": namespace,
                "memory_types": memory_types or [], "min_importance": min_importance}
        return m.RetrieveResult(**await self._request("POST", "/retrieve", json=body, idempotent=True))

    async def feedback(self, retrieval_id: str, user_id: str, used: list[str]) -> m.FeedbackResult:
        """Report which retrieved memories the agent used (trains ranking and trust)."""
        body = {"retrieval_id": retrieval_id, "user_id": user_id, "used_memory_ids": used}
        return m.FeedbackResult(**await self._request("POST", "/feedback", json=body, idempotent=True))

    async def handoff(self, user_id: str, *, task: str = "", since: str | None = None,
                      token_budget: int = 1500, namespace: str = "") -> m.HandoffPacket:
        body = {"user_id": user_id, "task": task, "since": since, "token_budget": token_budget,
                "namespace": namespace}
        return m.HandoffPacket(**await self._request("POST", "/handoff", json=body, idempotent=True))

    # ------------------------------------------------------------------
    # outcomes (continual learning)
    # ------------------------------------------------------------------

    async def correct(self, memory_id: str, user_id: str,
                      kind: Literal["wrong", "outdated", "malicious"], *,
                      corrected_text: str = "", note: str = "") -> m.CorrectionResult:
        body = {"memory_id": memory_id, "user_id": user_id, "kind": kind,
                "corrected_text": corrected_text, "note": note}
        return m.CorrectionResult(**await self._request("POST", "/corrections", json=body, idempotent=False,
                                                        idempotency_key=_new_key()))

    async def confirm(self, memory_id: str, user_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/memories/{memory_id}/confirm",
                                   params={"user_id": user_id}, idempotent=False)

    # ------------------------------------------------------------------
    # review
    # ------------------------------------------------------------------

    async def quarantine(self, user_id: str) -> list[m.QuarantineItem]:
        data = await self._request("GET", f"/quarantine/{user_id}", idempotent=True)
        return [m.QuarantineItem(**i) for i in data["items"]]

    async def release(self, memory_id: str, user_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/quarantine/{memory_id}/release",
                                   params={"user_id": user_id}, idempotent=False)

    async def reject(self, memory_id: str, user_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/quarantine/{memory_id}/reject",
                                   params={"user_id": user_id}, idempotent=False)

    # ------------------------------------------------------------------
    # privacy
    # ------------------------------------------------------------------

    async def forget(self, user_id: str, *, memory_ids: list[str] | None = None,
                     all_for_user: bool = False, reason: str = "") -> m.ErasureReceipt:
        body = {"user_id": user_id, "memory_ids": memory_ids or [], "all_for_user": all_for_user,
                "reason": reason}
        return m.ErasureReceipt(**await self._request("POST", "/forget", json=body, idempotent=False,
                                                      idempotency_key=_new_key()))

    async def get_receipt(self, receipt_id: str) -> m.ErasureReceipt:
        return m.ErasureReceipt(**await self._request("GET", f"/receipts/{receipt_id}", idempotent=True))

    async def verify_receipt(self, receipt: m.ErasureReceipt | dict[str, Any]) -> bool:
        payload = receipt.model_dump() if isinstance(receipt, m.ErasureReceipt) else receipt
        return (await self._request("POST", "/receipts/verify", json=payload, idempotent=True))["valid"]

    async def stats(self, user_id: str, namespace: str = "") -> dict[str, Any]:
        return await self._request("GET", "/stats", params={"user_id": user_id, "namespace": namespace},
                                   idempotent=True)

    async def health(self) -> dict[str, Any]:
        r = await self._http.get(self._base + "/health")
        r.raise_for_status()
        return r.json()

    async def trust_sources(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/trust/sources", idempotent=True))["sources"]


class AegisMemSync:
    """Blocking wrapper for scripts and non-async apps. Not for use inside a running event loop."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._loop = asyncio.new_event_loop()
        self._client = AegisMem(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._client, name)
        if not asyncio.iscoroutinefunction(attr):
            return attr
        return lambda *a, **kw: self._loop.run_until_complete(attr(*a, **kw))

    def close(self) -> None:
        self._loop.run_until_complete(self._client.close())
        self._loop.close()

    def __enter__(self) -> "AegisMemSync":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
