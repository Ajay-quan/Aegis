# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""Sync and async clients with identical method sets.

Retries: only on 429/502/503/504 and connection errors, and only for
requests that are safe to repeat (GET, or writes carrying an Idempotency-Key).
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx

from .errors import AegisError, from_response

RETRY_STATUS = {429, 502, 503, 504}


class _Base:
    def __init__(self, base_url: str, token: str, timeout: float, max_retries: int, backoff: float) -> None:
        if not base_url.startswith("https://") and not base_url.startswith(("http://127.0.0.1", "http://localhost")):
            raise ValueError("base_url must use https (plain http is only allowed for localhost)")
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}", "User-Agent": "aegistrace-sdk-python/0.1.0"}
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"  # never include the token

    def _delay(self, attempt: int, resp: httpx.Response | None) -> float:
        if resp is not None and (ra := resp.headers.get("retry-after", "")).isdigit():
            return min(float(ra), 30.0)
        return random.uniform(0, self.backoff * 2**attempt)  # noqa: S311

    @staticmethod
    def _result(resp: httpx.Response) -> Any:
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            raise from_response(resp.status_code, body)
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.content


class AegisClient(_Base):
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, token, timeout, max_retries, backoff)
        self._http = httpx.Client(base_url=self.base_url, headers=self._headers, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> AegisClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _request(self, method: str, path: str, *, retry_safe: bool, **kw: Any) -> Any:
        for attempt in range(self.max_retries + 1):
            resp = None
            try:
                resp = self._http.request(method, path, **kw)
            except httpx.TransportError:
                if not retry_safe or attempt == self.max_retries:
                    raise
            if resp is not None and (
                resp.status_code not in RETRY_STATUS or not retry_safe or attempt == self.max_retries
            ):
                return self._result(resp)
            time.sleep(self._delay(attempt, resp))
        raise AegisError(0, "retries_exhausted", "request failed")

    # agents
    def create_project(self, name: str) -> dict[str, Any]:
        return self._request("POST", "/v1/projects", retry_safe=False, json={"name": name})

    def register_agent(
        self, project_id: str, name: str, model_provider: str = "mock", model_id: str = "mock-deterministic-1"
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/agents",
            retry_safe=False,
            json={
                "project_id": project_id,
                "name": name,
                "model_provider": model_provider,
                "model_id": model_id,
            },
        )

    def list_agents(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/agents", retry_safe=True)["items"]

    def grant_tool(
        self, agent_id: str, tool: str, max_risk_class: int, allowed_hosts: list[str] | None = None
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/v1/agents/{agent_id}/grants",
            retry_safe=True,
            json={
                "tool": tool,
                "max_risk_class": max_risk_class,
                "allowed_hosts": allowed_hosts or [],
            },
        )

    # runs
    def submit_run(self, agent_id: str, input: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        key = idempotency_key or f"sdk-{uuid.uuid4()}"
        return self._request(
            "POST",
            "/v1/runs",
            retry_safe=True,
            json={"agent_id": agent_id, "input": input},
            headers={"Idempotency-Key": key},
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/runs/{run_id}", retry_safe=True)

    def iter_runs(self, state: str | None = None, page_size: int = 50) -> Iterator[dict[str, Any]]:
        cursor = None
        while True:
            params: dict[str, Any] = {"limit": page_size}
            if state:
                params["state"] = state
            if cursor:
                params["cursor"] = cursor
            page = self._request("GET", "/v1/runs", retry_safe=True, params=params)
            yield from page["items"]
            cursor = page.get("next_cursor")
            if not cursor:
                return

    def wait_for_run(
        self,
        run_id: str,
        timeout: float = 60.0,
        poll: float = 0.5,
        until: frozenset[str] = frozenset(
            {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT", "WAITING_FOR_APPROVAL", "NEEDS_RECONCILIATION"}
        ),
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            run = self.get_run(run_id)
            if run["state"] in until or time.monotonic() > deadline:
                return run
            time.sleep(poll)

    def events(self, run_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/v1/runs/{run_id}/events", retry_safe=True)["items"]

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/runs/{run_id}/cancel", retry_safe=False)

    def export_receipt(self, run_id: str) -> bytes:
        return self._request("GET", f"/v1/runs/{run_id}/receipt", retry_safe=True)

    def signing_keys(self) -> dict[str, Any]:
        return self._request("GET", "/v1/signing-keys", retry_safe=True)

    def replay(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/runs/{run_id}/replay", retry_safe=True)

    def fork_run(self, run_id: str, reason: str, idempotency_key: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/runs/{run_id}/fork",
            retry_safe=True,
            json={"reason": reason},
            headers={"Idempotency-Key": idempotency_key or f"sdk-{uuid.uuid4()}"},
        )

    # organization rules & insights
    def get_rules(self) -> dict[str, Any]:
        return self._request("GET", "/v1/rules", retry_safe=True)

    def update_rules(self, rules: dict[str, Any], note: str | None = None) -> dict[str, Any]:
        return self._request("PUT", "/v1/rules", retry_safe=True, json={"rules": rules, "note": note})

    def apply_rules_file(self, yaml_text: str, dry_run: bool = False) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/rules/file",
            retry_safe=False,
            content=yaml_text.encode(),
            params={"dry_run": str(dry_run).lower()},
            headers={"Content-Type": "application/yaml"},
        )

    def export_rules_file(self) -> str:
        data = self._request("GET", "/v1/rules/file", retry_safe=True)
        return data.decode() if isinstance(data, bytes) else str(data)

    def insights(self, range: str = "7d") -> dict[str, Any]:
        return self._request("GET", "/v1/insights", retry_safe=True, params={"range": range})

    # approvals
    def list_approvals(self, status: str = "pending") -> list[dict[str, Any]]:
        return self._request("GET", "/v1/approvals", retry_safe=True, params={"status": status})["items"]

    def decide_approval(self, approval_id: str, approve: bool) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/approvals/{approval_id}/decision",
            retry_safe=False,
            json={"approve": approve},
        )

    @staticmethod
    def verify_receipt(bundle: bytes, trust_store: dict[str, Any], tenant_id: str, run_id: str) -> dict[str, Any]:
        """Offline verification. Requires the `aegistrace` package (verifier)."""
        from aegistrace.evidence.trust import TrustStore
        from aegistrace.evidence.verifier import verify_bundle

        return verify_bundle(bundle, TrustStore.from_json(trust_store), tenant_id, run_id).as_dict()


class AsyncAegisClient(_Base):
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url, token, timeout, max_retries, backoff)
        self._http = httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers, timeout=timeout, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncAegisClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, *, retry_safe: bool, **kw: Any) -> Any:
        for attempt in range(self.max_retries + 1):
            resp = None
            try:
                resp = await self._http.request(method, path, **kw)
            except httpx.TransportError:
                if not retry_safe or attempt == self.max_retries:
                    raise
            if resp is not None and (
                resp.status_code not in RETRY_STATUS or not retry_safe or attempt == self.max_retries
            ):
                return self._result(resp)
            await asyncio.sleep(self._delay(attempt, resp))
        raise AegisError(0, "retries_exhausted", "request failed")

    async def submit_run(
        self, agent_id: str, input: dict[str, Any], idempotency_key: str | None = None
    ) -> dict[str, Any]:
        key = idempotency_key or f"sdk-{uuid.uuid4()}"
        return await self._request(
            "POST",
            "/v1/runs",
            retry_safe=True,
            json={"agent_id": agent_id, "input": input},
            headers={"Idempotency-Key": key},
        )

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/runs/{run_id}", retry_safe=True)

    async def events(self, run_id: str) -> list[dict[str, Any]]:
        return (await self._request("GET", f"/v1/runs/{run_id}/events", retry_safe=True))["items"]

    async def export_receipt(self, run_id: str) -> bytes:
        return await self._request("GET", f"/v1/runs/{run_id}/receipt", retry_safe=True)

    async def list_approvals(self, status: str = "pending") -> list[dict[str, Any]]:
        return (await self._request("GET", "/v1/approvals", retry_safe=True, params={"status": status}))["items"]

    async def decide_approval(self, approval_id: str, approve: bool) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/approvals/{approval_id}/decision",
            retry_safe=False,
            json={"approve": approve},
        )

    async def replay(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/runs/{run_id}/replay", retry_safe=True)
