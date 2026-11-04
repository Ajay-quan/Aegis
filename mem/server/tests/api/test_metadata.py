"""API metadata / version consistency and store-fallback behavior."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from apps.api.main import app
from core.version import __version__, PRODUCT_NAME
import apps.api.dependencies as deps
from core.config.settings import settings


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_root_reports_unified_version_and_brand(client):
    body = (await client.get("/")).json()
    assert body["version"] == __version__
    assert body["name"] == PRODUCT_NAME == "AegisMem"
    assert body["engine"] == "aegismem"


async def test_health_version_matches_package(client):
    body = (await client.get("/health")).json()
    assert body["version"] == __version__
    assert body["components"]["product"] == PRODUCT_NAME


async def test_openapi_title_is_branded(client):
    schema = (await client.get("/openapi.json")).json()
    assert PRODUCT_NAME in schema["info"]["title"]
    assert schema["info"]["version"] == __version__


# --- env-aware store fallback ------------------------------------------------

async def test_production_raises_on_unavailable_postgres(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "memory_backend", "postgres")
    monkeypatch.setattr(settings, "postgres_port", 1)  # nothing listens here
    deps._db_store = None
    try:
        with pytest.raises(RuntimeError):
            await deps.get_raw_db_store()   # postgres unavailable -> must NOT fall back
    finally:
        deps._db_store = None


async def test_dev_falls_back_to_memory(monkeypatch):
    from adapters.relational_store.memory_store import InMemoryRelationalStore
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "memory_backend", "postgres")
    monkeypatch.setattr(settings, "postgres_port", 1)
    deps._db_store = None
    try:
        store = await deps.get_raw_db_store()
        assert isinstance(store, InMemoryRelationalStore)
    finally:
        deps._db_store = None
