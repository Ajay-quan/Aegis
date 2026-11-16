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

import contextlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import httpx
from opentelemetry.trace import SpanKind
from pydantic import BaseModel, ConfigDict, Field

from aegistrace import tracing

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
    def post(self, path: str, body: dict[str, Any], idempotency_key: str | None = None) -> Any: ...
    def get(self, path: str, params: dict[str, Any] | None = None) -> Any: ...


class HttpMemoryClient:
    """Talks to an AegisMem server (`/api/v1`)."""

    def __init__(self, base_url: str, api_key: str | None, timeout: float = 10.0) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(base_url=base_url.rstrip("/") + "/api/v1", headers=headers, timeout=timeout)

    def post(self, path: str, body: dict[str, Any], idempotency_key: str | None = None) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        with tracing.span(f"aegismem {path}", {"aegis.memory.op": path.strip("/")}, kind=SpanKind.CLIENT) as s:
            headers.update(tracing.inject())  # AegisMem can join the trace
            r = self._http.post(path, json=body, headers=headers)
            s.set_attribute("http.response.status_code", r.status_code)
            r.raise_for_status()
            return r.json()

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        with tracing.span(f"aegismem {path}", {"aegis.memory.op": path.strip("/")}, kind=SpanKind.CLIENT) as s:
            r = self._http.get(path, params=params, headers=tracing.inject())
            s.set_attribute("http.response.status_code", r.status_code)
            r.raise_for_status()
            return r.json()


def client_from_env(env: Mapping[str, str]) -> HttpMemoryClient | None:
    """AEGIS_MEMORY_URL enables the memory tools. AegisMem authenticates the service with an `aem_` key from
    AEGIS_MEMORY_API_KEY_FILE (preferred) or AEGIS_MEMORY_API_KEY."""
    url = env.get("AEGIS_MEMORY_URL")
    if not url:
        return None
    key = env.get("AEGIS_MEMORY_API_KEY")
    path = env.get("AEGIS_MEMORY_API_KEY_FILE")
    if path:
        # Not created yet: calls are refused by AegisMem until it is (no silent fallback).
        with contextlib.suppress(OSError):
            key = Path(path).read_text().strip() or key
    return HttpMemoryClient(url, key)


def memory_user(ctx: ToolContext, subject: str) -> str:
    return f"{ctx.tenant_id}/{subject}"


def browse(client: MemoryClient, tenant_id: str, subject: str, limit: int = 50) -> list[dict[str, Any]]:
    """What is stored about a subject, for human review in the dashboard: active
    memories and those AegisMem quarantined, each with the run that wrote it
    (None when it was not written through AegisTrace)."""
    user = f"{tenant_id}/{subject}"
    out: list[dict[str, Any]] = []
    for status in ("active", "pending"):
        for m in client.post("/memories/list", {"user_id": user, "status": status, "limit": limit}):
            prov = (m.get("metadata") or {}).get("aegistrace") or {}
            out.append(
                {
                    "memory_id": m["memory_id"],
                    "content": m["content"],
                    "status": m["status"],
                    "created_at": m["created_at"],
                    "updated_at": m.get("updated_at"),
                    "agent_id": m.get("agent_id", ""),
                    "run_id": prov.get("run_id"),
                    "version": m.get("version", 1),
                    "memory_type": m.get("memory_type"),
                    "source_type": m.get("source_type"),
                    "importance": m.get("importance_score"),
                    "confidence": m.get("confidence_score"),
                    "contradiction_status": m.get("contradiction_status"),
                }
            )
    return sorted(out, key=lambda m: m["created_at"], reverse=True)


# -- Memory Explorer (Studio). Every call is scoped to one tenant's subject; ids from other users are refused. --


def explorer_search(
    client: MemoryClient, tenant_id: str, subject: str, query: str, top_k: int = 20
) -> list[dict[str, Any]]:
    r = client.post("/retrieve", {"query": query, "user_id": f"{tenant_id}/{subject}", "top_k": top_k})
    return [
        {
            "memory_id": m["memory_id"],
            "content": m["content"],
            "memory_type": m.get("memory_type"),
            "rank": m.get("rank"),
            "semantic_bp": round(float(m.get("semantic_score", 0)) * 10_000),
            "score_bp": round(float(m.get("composite_score", 0)) * 10_000),
            "created_at": m.get("created_at"),
        }
        for m in r.get("results", [])
    ]


def explorer_contradictions(client: MemoryClient, tenant_id: str, subject: str) -> list[dict[str, Any]]:
    """AegisMem lists contradictions for its whole tenant, without an owner. All AegisTrace organizations share
    that tenant, so keep only pairs where BOTH memories belong to this subject."""
    owned = {m["memory_id"]: m["content"] for m in browse(client, tenant_id, subject, limit=100)}
    out = []
    for c in client.get("/contradictions", {"resolved": False}).get("contradictions", []):
        a, b = c.get("memory_a_id"), c.get("memory_b_id")
        if a in owned and b in owned:
            out.append(
                {
                    "report_id": c.get("report_id"),
                    "a": {"memory_id": a, "content": owned[a]},
                    "b": {"memory_id": b, "content": owned[b]},
                    "description": c.get("description"),
                    "confidence_bp": round(float(c.get("confidence") or 0) * 10_000),
                    "detected_at": c.get("detected_at"),
                }
            )
    return out


def _owned_ids(client: MemoryClient, tenant_id: str, subject: str) -> set[str]:
    return {m["memory_id"] for m in browse(client, tenant_id, subject, limit=100)}


def explorer_review(client: MemoryClient, tenant_id: str, subject: str, memory_id: str, release: bool) -> Any:
    if memory_id not in _owned_ids(client, tenant_id, subject):  # defence in depth: AegisMem checks too
        raise LookupError(memory_id)
    action = "release" if release else "reject"
    return client.post(f"/quarantine/{memory_id}/{action}?user_id={tenant_id}/{subject}", {})


def explorer_correct(client: MemoryClient, tenant_id: str, subject: str, text: str, actor: str) -> Any:
    """A person corrects what is remembered. AegisMem decides whether it supersedes an earlier memory (versioned)."""
    return client.post(
        "/update", {"user_id": f"{tenant_id}/{subject}", "new_content": text, "agent_id": f"studio:{actor}"}
    )


def explorer_forget(client: MemoryClient, tenant_id: str, subject: str, memory_ids: list[str], reason: str) -> Any:
    if not set(memory_ids) <= _owned_ids(client, tenant_id, subject):
        raise LookupError("not all memories belong to this subject")
    return client.post("/forget", {"user_id": f"{tenant_id}/{subject}", "memory_ids": memory_ids, "reason": reason})


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
