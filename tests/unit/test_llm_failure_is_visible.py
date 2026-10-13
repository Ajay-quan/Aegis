"""LLM unavailability must be visible (503), never a silent mock or a plausible default."""
import pytest
from httpx import ASGITransport, AsyncClient

from adapters.llm.unavailable import UnavailableLLMClient
from apps.api import dependencies as deps
from apps.api.main import app
from core.config.settings import settings
from core.exceptions import LLMError
from services.reflect_service import ReflectionService
from tests.fixtures.conftest import MockPostgresStore


def test_get_llm_never_silently_mocks(monkeypatch):
    monkeypatch.setattr(settings, "default_llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert isinstance(deps.get_llm(), UnavailableLLMClient)


async def test_services_propagate_unavailability():
    svc = ReflectionService(MockPostgresStore(), ingest_service=None, llm_client=UnavailableLLMClient("test"))
    svc._db.list_memories = None
    with pytest.raises(LLMError):
        await svc._llm.generate_json("x")


async def test_llm_endpoints_return_503(monkeypatch):
    from adapters.relational_store.memory_store import InMemoryMemoryStore
    db = InMemoryMemoryStore()  # one shared store (a class here would build a new one per request)
    monkeypatch.setitem(app.dependency_overrides, deps.get_raw_db_store, lambda: db)
    monkeypatch.setattr(deps, "get_llm", lambda: UnavailableLLMClient("no model configured"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        for _ in range(12):
            await c.post("/api/v1/ingest", json={"text": "User likes tea and jazz", "user_id": "u"})
        r = await c.post("/api/v1/reflect", json={"user_id": "u", "force": True})
    assert r.status_code == 503 and r.json()["error"]["code"] == "llm_unavailable"


def test_production_refuses_mock_llm(monkeypatch):
    from apps.api.main import validate_runtime_config
    for k, v in (("app_env", "production"), ("auth_enabled", True), ("app_secret_key", "x" * 48),
                 ("api_key_pepper", "p" * 48), ("memory_backend", "postgres"), ("vector_backend", "pgvector"),
                 ("graph_backend", "none"), ("embedding_backend", "openai"), ("default_llm_provider", "mock")):
        monkeypatch.setattr(settings, k, v)
    with pytest.raises(RuntimeError, match="DEFAULT_LLM_PROVIDER=mock"):
        validate_runtime_config()
