"""API endpoint tests using FastAPI TestClient."""
import pytest
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from apps.api.dependencies import (
    get_db_store, get_vector_store, get_graph_store,
    get_ingest_service, get_retrieve_service, get_update_service,
    get_reflect_service, get_contradiction_service,
)
from tests.fixtures.conftest import MockPostgresStore
from adapters.vector_store.qdrant_store import InMemoryVectorStore
from adapters.graph_store.neo4j_store import MockGraphStore
from adapters.embeddings.backend import MockEmbeddingBackend
from adapters.llm.mock_client import MockLLMClient
from services.ingest_service import IngestionService
from services.retrieve_service import RetrievalService
from services.update_service import UpdateService
from services.reflect_service import ReflectionService
from services.contradiction_service import ContradictionService


@pytest.fixture
def mock_db_instance():
    return MockPostgresStore()


@pytest.fixture
async def test_client(mock_db_instance):
    embed = MockEmbeddingBackend(dim=384)
    vs = InMemoryVectorStore()
    await vs.initialize(384)
    graph = MockGraphStore()
    llm = MockLLMClient()

    ingest = IngestionService(mock_db_instance, vs, embed, graph, llm)
    retrieve = RetrievalService(mock_db_instance, vs, embed)
    update = UpdateService(mock_db_instance, vs, embed, llm, ingest)
    reflect = ReflectionService(mock_db_instance, ingest, llm)
    contradiction = ContradictionService(mock_db_instance, vs, embed, llm, graph)

    # Override dependencies
    app.dependency_overrides[get_db_store] = lambda: mock_db_instance
    app.dependency_overrides[get_vector_store] = lambda: vs
    app.dependency_overrides[get_graph_store] = lambda: graph
    app.dependency_overrides[get_ingest_service] = lambda: ingest
    app.dependency_overrides[get_retrieve_service] = lambda: retrieve
    app.dependency_overrides[get_update_service] = lambda: update
    app.dependency_overrides[get_reflect_service] = lambda: reflect
    app.dependency_overrides[get_contradiction_service] = lambda: contradiction

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


class TestHealthEndpoint:
    async def test_health_returns_ok(self, test_client):
        resp = await test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_root_returns_info(self, test_client):
        resp = await test_client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "AegisMem"
        assert body["engine"] == "aegismem"  # package / engine identifier


class TestIngestEndpoint:
    async def test_ingest_creates_memory(self, test_client):
        resp = await test_client.post(
            "/api/v1/ingest",
            json={
                "text": "User is a Python developer who loves open source",
                "user_id": "api_test_user",
                "session_id": "s1",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "memory_id" in data
        assert data["user_id"] == "api_test_user"
        assert data["importance_score"] >= 0.0

    async def test_ingest_empty_text_fails(self, test_client):
        resp = await test_client.post(
            "/api/v1/ingest",
            json={"text": "", "user_id": "u1"},
        )
        assert resp.status_code == 422

    async def test_batch_ingest(self, test_client):
        resp = await test_client.post(
            "/api/v1/ingest/batch",
            json={
                "items": [
                    {"text": f"Batch item {i}", "user_id": "batch_user"}
                    for i in range(3)
                ]
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["ingested"] == 3
        assert data["failed"] == 0


class TestRetrieveEndpoint:
    async def test_retrieve_returns_results(self, test_client):
        # First ingest something
        await test_client.post(
            "/api/v1/ingest",
            json={"text": "User loves machine learning", "user_id": "ret_user"},
        )
        resp = await test_client.post(
            "/api/v1/retrieve",
            json={"query": "machine learning", "user_id": "ret_user", "top_k": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "latency_ms" in data

    async def test_retrieve_empty_query_fails(self, test_client):
        resp = await test_client.post(
            "/api/v1/retrieve",
            json={"query": "", "user_id": "u1"},
        )
        assert resp.status_code == 422


class TestMemoryDetailEndpoint:
    async def test_get_nonexistent_memory_returns_404(self, test_client):
        resp = await test_client.get("/api/v1/memories/nonexistent-id-123")
        assert resp.status_code == 404

    async def test_get_existing_memory(self, test_client, mock_db_instance):
        from core.schemas.memory import MemoryItem, MemoryType
        m = MemoryItem(
            namespace="user:u_detail",
            user_id="u_detail",
            memory_type=MemoryType.OBSERVATION,
            content="Test memory content",
        )
        await mock_db_instance.save_memory(m)
        resp = await test_client.get(f"/api/v1/memories/{m.memory_id}")
        assert resp.status_code == 200
        assert resp.json()["memory_id"] == m.memory_id
