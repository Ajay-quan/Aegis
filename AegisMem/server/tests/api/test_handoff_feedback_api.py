"""API tests for /handoff, /feedback and /learning."""
import pytest
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from apps.api.dependencies import (
    get_db_store, get_ingest_service, get_retrieve_service,
    get_feedback_service, get_handoff_service, get_learner,
)
from adapters.embeddings.backend import MockEmbeddingBackend
from adapters.graph_store.neo4j_store import MockGraphStore
from adapters.llm.mock_client import MockLLMClient
from adapters.vector_store.qdrant_store import InMemoryVectorStore
from domain.learning import OnlineWeightLearner
from services.feedback_service import FeedbackService, RetrievalLedger
from services.handoff_service import HandoffService
from services.ingest_service import IngestionService
from services.retrieve_service import RetrievalService
from tests.fixtures.conftest import MockPostgresStore


@pytest.fixture
async def client():
    db = MockPostgresStore()
    embed = MockEmbeddingBackend(dim=384)
    vs = InMemoryVectorStore()
    await vs.initialize(384)
    learner, ledger = OnlineWeightLearner(min_events=2), RetrievalLedger()
    ingest = IngestionService(db, vs, embed, MockGraphStore(), MockLLMClient())
    retrieve = RetrievalService(db, vs, embed, learner=learner, ledger=ledger)

    app.dependency_overrides.update({
        get_db_store: lambda: db,
        get_ingest_service: lambda: ingest,
        get_retrieve_service: lambda: retrieve,
        get_feedback_service: lambda: FeedbackService(db, ledger, learner),
        get_handoff_service: lambda: HandoffService(db, retrieve),
        get_learner: lambda: learner,
    })
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _ingest(client, text):
    r = await client.post("/api/v1/ingest", json={"text": text, "user_id": "u1"})
    assert r.status_code == 201


async def test_retrieve_feedback_learning_roundtrip(client):
    for t in ["User loves hiking in the Alps", "User works as a data engineer", "User has a cat"]:
        await _ingest(client, t)

    r = (await client.post("/api/v1/retrieve", json={"query": "hiking", "user_id": "u1"})).json()
    assert r["retrieval_id"]
    used = [r["results"][0]["memory_id"]]

    fb = await client.post("/api/v1/feedback", json={
        "retrieval_id": r["retrieval_id"], "user_id": "u1", "used_memory_ids": used,
    })
    assert fb.status_code == 200
    assert fb.json()["used"] == 1

    # Replays and cross-user feedback are rejected.
    again = await client.post("/api/v1/feedback", json={
        "retrieval_id": r["retrieval_id"], "user_id": "u1", "used_memory_ids": used,
    })
    assert again.status_code == 422

    state = (await client.get("/api/v1/learning/u1")).json()
    assert state["events"] == len(r["results"])
    assert state["learning_active"] is (state["events"] >= 2)

    assert (await client.delete("/api/v1/learning/u1")).status_code == 204
    assert (await client.get("/api/v1/learning/u1")).json()["events"] == 0


async def test_feedback_rejects_foreign_memory_ids(client):
    await _ingest(client, "User likes tea")
    r = (await client.post("/api/v1/retrieve", json={"query": "tea", "user_id": "u1"})).json()
    fb = await client.post("/api/v1/feedback", json={
        "retrieval_id": r["retrieval_id"], "user_id": "u1", "used_memory_ids": ["nope"],
    })
    assert fb.status_code == 422


async def test_handoff_endpoint(client):
    await _ingest(client, "User prefers Python over Java")
    r = await client.post("/api/v1/handoff", json={
        "user_id": "u1", "task": "help choose a language", "token_budget": 500,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["tokens_used"] <= 500
    assert "Python" in body["markdown"]
