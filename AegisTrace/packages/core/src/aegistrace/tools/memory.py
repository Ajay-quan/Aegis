# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Governed memory: AegisMem exposed as gateway tools.

Every memory read, write and erasure an agent makes goes through the same
default-deny policy, approval and evidence path as any other tool, so the
signed event log shows exactly what an agent remembered and recalled.

Isolation: the AegisMem user id is derived server-side as
"<tenant_id>/<subject>"; the model only chooses the subject, so it cannot
reach another tenant's memories.

Provenance: each write carries the run id and idempotency key in its
metadata, so any memory can be traced back to the run (and its signed
events) that created it. AegisMem may quarantine a write it considers
untrusted; the tool reports that instead of hiding it.

The memory service URL is platform configuration, never model input, so
these tools are not egress tools (network=False for policy purposes).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .registry import Classification, RiskClass, ToolContext, ToolRegistry, ToolSpec

SUBJECT = r"^[a-z0-9_.-]{1,64}$"
AGENT_ID = "aegistrace"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecallArgs(Strict):
    subject: str = Field(pattern=SUBJECT)
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class Recalled(Strict):
    memory_id: str
    content: str
    score_bp: int  # relevance in basis points (0-10000); the evidence log admits no floats


class RecallOut(Strict):
    memories: list[Recalled]


class RememberArgs(Strict):
    subject: str = Field(pattern=SUBJECT)
    text: str = Field(min_length=1, max_length=4000)


class RememberOut(Strict):
    memory_id: str
    status: str  # "active", or "pending" when AegisMem quarantined it for review
    quarantine_reason: str | None = None


class ForgetArgs(Strict):
    subject: str = Field(pattern=SUBJECT)
    memory_ids: list[str] = Field(min_length=1, max_length=100)
    reason: str = Field(default="", max_length=200)


class ForgetOut(Strict):
    erased: int
    receipt_id: str
    verified: bool  # AegisMem re-checked every store after erasing
    receipt_signature: str


class MemoryClient(Protocol):
    def post(self, path: str, body: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]: ...


class HttpMemoryClient:
    """Talks to an AegisMem server (`/api/v1`)."""

    def __init__(self, base_url: str, api_key: str | None, timeout: float = 10.0) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(base_url=base_url.rstrip("/") + "/api/v1", headers=headers, timeout=timeout)

    def post(self, path: str, body: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        r = self._http.post(path, json=body, headers=headers)
        r.raise_for_status()
        out: dict[str, Any] = r.json()
        return out


def client_from_env(env: Mapping[str, str]) -> HttpMemoryClient | None:
    """AEGIS_MEMORY_URL enables the memory tools; AEGIS_MEMORY_API_KEY authenticates to AegisMem."""
    url = env.get("AEGIS_MEMORY_URL")
    return HttpMemoryClient(url, env.get("AEGIS_MEMORY_API_KEY")) if url else None


def memory_user(ctx: ToolContext, subject: str) -> str:
    return f"{ctx.tenant_id}/{subject}"


def register_memory_tools(reg: ToolRegistry, client: MemoryClient) -> None:
    def recall(ctx: ToolContext, a: RecallArgs) -> RecallOut:
        r = client.post("/retrieve", {"query": a.query, "user_id": memory_user(ctx, a.subject), "top_k": a.top_k})
        return RecallOut(
            memories=[
                Recalled(
                    memory_id=m["memory_id"], content=m["content"], score_bp=round(float(m["composite_score"]) * 10_000)
                )
                for m in r.get("results", [])
            ]
        )

    def remember(ctx: ToolContext, a: RememberArgs) -> RememberOut:
        r = client.post(
            "/ingest",
            {
                "text": a.text,
                "user_id": memory_user(ctx, a.subject),
                "agent_id": AGENT_ID,
                "session_id": ctx.run_id,
                "source_type": "agent_observation",
                "metadata": {"aegistrace": {"run_id": ctx.run_id, "idempotency_key": ctx.idempotency_key}},
            },
            idempotency_key=ctx.idempotency_key,
        )
        return RememberOut(
            memory_id=r["memory_id"], status=r.get("status", "active"), quarantine_reason=r.get("quarantine_reason")
        )

    def forget(ctx: ToolContext, a: ForgetArgs) -> ForgetOut:
        r = client.post(
            "/forget",
            {"user_id": memory_user(ctx, a.subject), "memory_ids": a.memory_ids, "reason": a.reason},
            idempotency_key=ctx.idempotency_key,
        )
        body = r["body"]
        return ForgetOut(
            erased=len(body["erased"]),
            receipt_id=body["receipt_id"],
            verified=bool(body["verified"]),
            receipt_signature=r["signature"],
        )

    reg.register(
        ToolSpec(
            "memory.recall",
            "Recall stored memories about a subject",
            RiskClass.CONTROLLED_READ,
            RecallArgs,
            RecallOut,
            recall,
            True,
            output_classification=Classification.CONFIDENTIAL,
            resource_of=lambda a: {"subject": a.subject},
        )
    )
    reg.register(
        ToolSpec(
            "memory.remember",
            "Store a memory about a subject",
            RiskClass.REVERSIBLE_WRITE,
            RememberArgs,
            RememberOut,
            remember,
            True,  # AegisMem deduplicates on the Idempotency-Key header
            resource_of=lambda a: {"subject": a.subject},
        )
    )
    reg.register(
        ToolSpec(
            "memory.forget",
            "Permanently erase memories (returns a signed erasure receipt)",
            RiskClass.IRREVERSIBLE,
            ForgetArgs,
            ForgetOut,
            forget,
            False,
            resource_of=lambda a: {"subject": a.subject, "count": len(a.memory_ids)},
        )
    )
