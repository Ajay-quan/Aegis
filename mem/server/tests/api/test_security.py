"""HTTP hardening: security headers, no-store, body limits, stats, durable audit trail.
(Authentication, scopes and rate limits are covered in test_auth_tenancy.py / test_rate_limit.py.)"""
import pytest
from httpx import ASGITransport, AsyncClient

from adapters.graph_store.neo4j_store import MockGraphStore
from adapters.relational_store.memory_store import InMemoryMemoryStore
from adapters.vector_store.qdrant_store import InMemoryVectorStore
from apps.api import dependencies as deps
from apps.api.auth import issue_key
from apps.api.main import app
from apps.api.security import SECURITY_HEADERS
from core.config import settings


@pytest.fixture
async def client(monkeypatch):
    vs = InMemoryVectorStore()
    await vs.initialize(384)
    db = InMemoryMemoryStore()
    monkeypatch.setitem(app.dependency_overrides, deps.get_raw_db_store, lambda: db)
    monkeypatch.setitem(app.dependency_overrides, deps.get_raw_vector_store, lambda: vs)
    monkeypatch.setitem(app.dependency_overrides, deps.get_graph_store, MockGraphStore)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_security_headers_on_every_response(client):
    r = await client.get("/health")
    for header, value in SECURITY_HEADERS.items():
        assert r.headers[header] == value


async def test_api_routes_are_not_cached(client):
    r = await client.post("/api/v1/retrieve", json={"query": "x", "user_id": "u"})
    assert r.headers["cache-control"] == "no-store"
    assert "cache-control" not in (await client.get("/health")).headers


async def test_oversized_body_rejected_before_parsing(client, monkeypatch):
    monkeypatch.setattr(settings, "max_request_bytes", 100)
    r = await client.post("/api/v1/ingest", json={"text": "x" * 500, "user_id": "u"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


async def test_stats_aggregates_one_users_memories(client):
    for text, mtype in (("likes tea", "fact"), ("went hiking", "observation"), ("likes jazz", "fact")):
        await client.post("/api/v1/ingest", json={"text": text, "user_id": "s1", "memory_type": mtype})
    await client.post("/api/v1/ingest", json={"text": "other user", "user_id": "s2"})
    body = (await client.get("/api/v1/stats", params={"user_id": "s1"})).json()
    assert body["total_memories"] == 3 and body["by_type"] == {"fact": 2, "observation": 1}
    assert body["by_status"] == {"active": 3} and body["last_memory_at"]


async def test_mutations_are_audited_durably_per_tenant(client, monkeypatch, _isolated_control_plane):
    monkeypatch.setattr(settings, "auth_enabled", True)
    store = _isolated_control_plane
    _, admin = await issue_key(store, "acme", ["admin"], "ops-admin")
    _, other = await issue_key(store, "globex", ["admin"], "globex-admin")
    h = {"Authorization": f"Bearer {admin}"}
    await client.post("/api/v1/ingest", json={"text": "audited write", "user_id": "u"}, headers=h)
    await client.post("/api/v1/retrieve", json={"query": "audited", "user_id": "u"}, headers=h)
    trail = (await client.get("/api/v1/admin/audit", headers=h)).json()
    routes = [(e["method"], e["route"], e["status"], e["principal"]) for e in trail]
    assert ("POST", "/api/v1/ingest", 201, "ops-admin") in routes
    others = (await client.get("/api/v1/admin/audit", headers={"Authorization": f"Bearer {other}"})).json()
    assert all(e["principal"] != "ops-admin" for e in others)  # tenant-scoped
