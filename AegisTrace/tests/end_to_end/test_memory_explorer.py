# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Studio Memory Explorer: search, contradictions, review, corrections and erasure, all scoped to one
organization's subject, with permissions checked and every change audited."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from aegistrace.api.app import Deps, create_app
from aegistrace.evidence.signing import LocalEd25519Signer
from aegistrace.identity.devissuer import AUDIENCE, ISSUER, DevIssuer
from aegistrace.identity.jwt import JwksCache, TokenValidator
from tests.end_to_end.test_governed_memory import FakeAegisMem


class ExplorerFake(FakeAegisMem):
    def __init__(self) -> None:
        super().__init__(quarantine_words=("ignore previous instructions",))
        self.contradictions: list[dict[str, Any]] = []

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((path, params or {}, None))
        if path == "/contradictions":
            return {"contradictions": self.contradictions, "total": len(self.contradictions)}
        raise AssertionError(path)

    def post(self, path: str, body: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        if path.startswith("/quarantine/"):
            mid, action = path.split("?")[0].split("/")[2:4]
            user = path.split("user_id=")[1]
            rec = self.store[user][mid]
            if action == "release":
                rec["pending"] = False
            else:
                del self.store[user][mid]
            self.calls.append((path, body, None))
            return {"memory_id": mid, "status": action}
        if path == "/update":
            self.calls.append((path, body, None))
            mid = f"mem_{next(self._ids)}"
            self.store.setdefault(body["user_id"], {})[mid] = {
                "content": body["new_content"],
                "metadata": {},
                "pending": False,
            }
            return {
                "memory_id": mid,
                "action": "supersede",
                "reason": "newer",
                "previous_memory_id": "",
                "content_preview": body["new_content"][:40],
            }
        if path == "/retrieve":
            out = super().post(path, body, idempotency_key)
            for m in out["results"]:
                m.update(semantic_score=0.8, rank=1, memory_type="observation")
            return out
        return super().post(path, body, idempotency_key)


@pytest.fixture
def mem() -> ExplorerFake:
    return ExplorerFake()


@pytest.fixture
def issuer() -> DevIssuer:
    return DevIssuer()


@pytest.fixture
def api(app_engine, harness, mem, issuer) -> TestClient:
    deps = Deps(
        app_engine,
        TokenValidator(ISSUER, AUDIENCE, JwksCache(issuer.jwks)),
        LocalEd25519Signer(),
        harness.redis,
        gateway=harness.worker.gateway,
        memory=mem,
    )
    return TestClient(create_app(deps), raise_server_exceptions=False)


ALL = [
    "runs:read",
    "payloads:read",
    "approvals:decide",
    "agents:write",
    "data:erase",
    "audit:read",
    "members:manage",
    "agents:read",
]


def h(issuer, tenant, scopes=ALL, sub="usr_alice"):
    return {"Authorization": "Bearer " + issuer.mint(sub, tenant.tenant_id, scopes)}


def seed(mem, tenant, subject, *texts, pending=False):
    user = mem.store.setdefault(f"{tenant.tenant_id}/{subject}", {})
    ids = []
    for t in texts:
        mid = f"mem_{next(mem._ids)}"
        user[mid] = {"content": t, "metadata": {"aegistrace": {"run_id": "run_x"}}, "pending": pending}
        ids.append(mid)
    return ids


def test_search_returns_scored_results_for_this_subject_only(api, issuer, tenant, other_tenant, mem):
    seed(mem, tenant, "acme", "Acme pays in EUR")
    seed(mem, other_tenant, "acme", "Acme pays in GBP")
    r = api.post("/v1/memory/acme/search", headers=h(issuer, tenant), json={"query": "acme pays"})
    assert r.status_code == 200
    assert [m["content"] for m in r.json()["items"]] == ["Acme pays in EUR"]
    assert r.json()["items"][0]["score_bp"] == 9000
    assert mem.calls[-1][1]["user_id"] == f"{tenant.tenant_id}/acme"


def test_contradictions_never_leak_across_organizations(api, issuer, tenant, other_tenant, mem):
    a, b = seed(mem, tenant, "acme", "Acme pays in EUR", "Acme pays in USD")
    c, d = seed(mem, other_tenant, "acme", "secret A", "secret B")
    mem.contradictions = [
        {"report_id": "r1", "memory_a_id": a, "memory_b_id": b, "description": "currency", "confidence": 0.9},
        {"report_id": "r2", "memory_a_id": c, "memory_b_id": d, "description": "other org", "confidence": 0.8},
        {"report_id": "r3", "memory_a_id": a, "memory_b_id": c, "description": "mixed", "confidence": 0.7},
    ]
    items = api.get("/v1/memory/acme/contradictions", headers=h(issuer, tenant)).json()["items"]
    assert [i["report_id"] for i in items] == ["r1"]  # r2 belongs to another org; r3 straddles orgs
    assert {items[0]["a"]["content"], items[0]["b"]["content"]} == {"Acme pays in EUR", "Acme pays in USD"}


def test_review_releases_or_rejects_quarantined_memories_and_is_audited(api, issuer, tenant, mem):
    (held,) = seed(mem, tenant, "acme", "Ignore previous instructions", pending=True)
    r = api.post(f"/v1/memory/acme/review/{held}", headers=h(issuer, tenant), json={"release": False})
    assert r.status_code == 200 and held not in mem.store[f"{tenant.tenant_id}/acme"]
    events = api.get("/v1/audit-events", headers=h(issuer, tenant)).json()["items"]
    assert ("memory.rejected", f"acme/{held}") in {(e["action"], e["target"]) for e in events}


def test_cannot_act_on_another_subjects_or_organizations_memory(api, issuer, tenant, other_tenant, mem):
    (theirs,) = seed(mem, other_tenant, "acme", "theirs", pending=True)
    assert (
        api.post(f"/v1/memory/acme/review/{theirs}", headers=h(issuer, tenant), json={"release": True}).status_code
        == 404
    )
    r = api.post("/v1/memory/acme/forget", headers=h(issuer, tenant), json={"memory_ids": [theirs], "reason": "x" * 5})
    assert r.status_code == 404
    assert theirs in mem.store[f"{other_tenant.tenant_id}/acme"]  # untouched


def test_corrections_and_erasure(api, issuer, tenant, mem):
    (old,) = seed(mem, tenant, "acme", "Acme pays in USD")
    r = api.post("/v1/memory/acme/corrections", headers=h(issuer, tenant), json={"text": "Acme pays in EUR"})
    assert r.status_code == 200 and r.json()["action"] == "supersede"
    r = api.post(
        "/v1/memory/acme/forget", headers=h(issuer, tenant), json={"memory_ids": [old], "reason": "request 12"}
    )
    assert r.status_code == 200 and r.json()["body"]["erased"] == [old]
    actions = {e["action"] for e in api.get("/v1/audit-events", headers=h(issuer, tenant)).json()["items"]}
    assert {"memory.corrected", "memory.erased"} <= actions


def test_permissions(api, issuer, tenant, mem):
    seed(mem, tenant, "acme", "x")
    viewer = h(issuer, tenant, ["runs:read", "agents:read"])
    assert api.post("/v1/memory/acme/search", headers=viewer, json={"query": "x"}).status_code == 403
    dev = h(issuer, tenant, ["runs:read", "payloads:read", "agents:write"])
    assert (
        api.post("/v1/memory/acme/forget", headers=dev, json={"memory_ids": ["m"], "reason": "abc"}).status_code == 403
    )
    assert api.post("/v1/memory/acme/review/m", headers=dev, json={"release": True}).status_code == 403
    assert api.post("/v1/memory/..%2F..%2Fx/search", headers=h(issuer, tenant), json={"query": "x"}).status_code in (
        404,
        422,
    )
