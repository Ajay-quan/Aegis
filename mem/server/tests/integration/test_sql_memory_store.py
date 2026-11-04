"""PostgresStore exercised through SQLAlchemy on SQLite: every field must round-trip."""
from datetime import datetime, timedelta, timezone

import os
import uuid

import pytest

from adapters.relational_store.postgres_store import PostgresStore
from adapters.tenancy import TenantScopedMemoryStore
from core.exceptions import MemoryNotFoundError
from core.schemas.memory import MemoryItem, MemoryLayer


PG_URL = os.environ.get("AEGIS_TEST_PG_URL")  # e.g. postgresql+asyncpg://... (set in CI)


@pytest.fixture(params=["sqlite"] + (["postgres"] if PG_URL else []))
async def db(request, tmp_path):
    url = PG_URL if request.param == "postgres" else f"sqlite+aiosqlite:///{tmp_path}/mem.db"
    store = PostgresStore(url)
    if request.param == "postgres":  # shared server: start every test from an empty schema
        from adapters.relational_store import control_models  # noqa: F401
        from adapters.relational_store.models import Base
        async with store._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    await store.initialize()
    yield store
    await store.close()


async def test_all_fields_persist_through_save_and_update(db):
    m = MemoryItem(tenant_id="acme", namespace="n", user_id="u", content="Prefers tea",
                   memory_type="fact", memory_layer=MemoryLayer.SEMANTIC)
    await db.save_memory(m)
    m.parent_memory_ids = ["p1"]
    m.contradicted_by = ["c1"]
    m.valid_to = datetime.now(timezone.utc) + timedelta(days=1)
    m.retrieval_count, m.successful_retrieval_count = 7, 3
    m.confidence_score, m.access_count, m.tags = 0.42, 5, ["pref"]
    m.metadata = {"provenance": {"trust": 0.9}}
    await db.update_memory(m)

    got = await db.get_memory(m.memory_id)
    assert got.tenant_id == "acme" and got.memory_layer == "semantic"
    assert got.parent_memory_ids == ["p1"] and got.contradicted_by == ["c1"]
    assert got.valid_to is not None
    assert (got.retrieval_count, got.successful_retrieval_count) == (7, 3)
    assert (got.confidence_score, got.access_count, got.tags) == (0.42, 5, ["pref"])
    assert got.metadata["provenance"]["trust"] == 0.9


async def test_tenant_scoped_listing_and_purge(db):
    a = TenantScopedMemoryStore(db, "acme")
    b = TenantScopedMemoryStore(db, "globex")
    m = await a.save_memory(MemoryItem(namespace="n", user_id="u", content="acme secret"))
    await b.save_memory(MemoryItem(namespace="n", user_id="u", content="globex secret"))

    assert [x.content for x in await a.list_memories(user_id="u")] == ["acme secret"]
    assert await b.count_memories("u") == 1
    with pytest.raises(MemoryNotFoundError):
        await b.get_memory(m.memory_id)
    with pytest.raises(MemoryNotFoundError):
        await b.purge_memory(m.memory_id, "u")

    await a.purge_memory(m.memory_id, "u")
    with pytest.raises(MemoryNotFoundError):
        await db.get_memory(m.memory_id)  # hard-deleted, not a status flag


async def test_unscoped_methods_fail_closed(db):
    with pytest.raises(AttributeError, match="not tenant-scoped"):
        TenantScopedMemoryStore(db, "acme").get_facts_for_user("u")
