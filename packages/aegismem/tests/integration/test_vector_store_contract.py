"""Vector-store conformance kit: every backend must satisfy the same contract.

Runs against InMemory and pgvector (SQLite locally; real Postgres+pgvector in CI when
AEGIS_TEST_PG_URL is set). Add new backends (e.g. Qdrant with a live server) to BACKENDS.
"""
import os
import uuid

import pytest

from adapters.tenancy import TenantScopedVectorStore, TenantViolation
from adapters.vector_store.pgvector_store import PgVectorStore
from adapters.vector_store.qdrant_store import InMemoryVectorStore

DIM = 8
PG_URL = os.environ.get("AEGIS_TEST_PG_URL")
QDRANT = os.environ.get("AEGIS_TEST_QDRANT")  # host:port, set in CI
BACKENDS = (["memory", "pgvector-sqlite"] + (["pgvector-postgres"] if PG_URL else [])
            + (["qdrant"] if QDRANT else []))


def vec(*xs):
    v = list(xs) + [0.0] * (DIM - len(xs))
    return v


@pytest.fixture(params=BACKENDS)
async def vs(request, tmp_path):
    if request.param == "memory":
        store = InMemoryVectorStore()
    elif request.param == "qdrant":
        from adapters.vector_store.qdrant_store import QdrantStore
        host, port = QDRANT.split(":")
        store = QdrantStore(host=host, port=int(port), collection_name=f"contract_{uuid.uuid4().hex[:8]}")
    elif request.param == "pgvector-sqlite":
        store = PgVectorStore(f"sqlite+aiosqlite:///{tmp_path}/vec.db")
    else:
        store = PgVectorStore(PG_URL)
        async with store._engine.begin() as conn:
            await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.exec_driver_sql("DROP TABLE IF EXISTS memory_vectors")
            await conn.exec_driver_sql(
                f"CREATE TABLE memory_vectors (id varchar(36) primary key, tenant_id varchar(64) not null, "
                f"user_id varchar(255) not null, status varchar(50) not null, embedding vector({DIM}), "
                f"payload json not null)")
    await store.initialize(DIM)
    yield store
    if request.param == "qdrant":
        await (await store._get_client()).delete_collection(store.collection_name)
    if hasattr(store, "close"):
        await store.close()


async def test_upsert_get_search_order(vs):
    await vs.upsert("a", vec(1, 0), {"user_id": "u", "status": "active", "tenant_id": "t"})
    await vs.upsert("b", vec(0.9, 0.1), {"user_id": "u", "status": "active", "tenant_id": "t"})
    await vs.upsert("c", vec(0, 1), {"user_id": "u", "status": "active", "tenant_id": "t"})
    hits = await vs.search(vec(1, 0), top_k=2, filter={"user_id": "u"})
    assert [h.id for h in hits] == ["a", "b"]
    assert hits[0].score == pytest.approx(1.0, abs=1e-6)
    assert (await vs.get("c")).payload["user_id"] == "u"


async def test_filters_and_status_updates(vs):
    await vs.upsert("a", vec(1), {"user_id": "u", "status": "active", "tenant_id": "t", "namespace": "n1"})
    await vs.upsert("b", vec(1), {"user_id": "v", "status": "active", "tenant_id": "t", "namespace": "n1"})
    assert [h.id for h in await vs.search(vec(1), filter={"user_id": "u", "status": "active"})] == ["a"]
    assert [h.id for h in await vs.search(vec(1), filter={"namespace": "n1", "user_id": "v"})] == ["b"]
    await vs.update_payload("a", {"status": "superseded"})
    assert await vs.search(vec(1), filter={"user_id": "u", "status": "active"}) == []
    assert (await vs.get("a")).payload["status"] == "superseded"


async def test_upsert_replaces_and_delete_removes(vs):
    await vs.upsert("a", vec(1), {"user_id": "u", "status": "active", "tenant_id": "t"})
    await vs.upsert("a", vec(0, 1), {"user_id": "u", "status": "active", "tenant_id": "t"})
    assert [h.id for h in await vs.search(vec(0, 1), top_k=1)] == ["a"]
    await vs.delete("a")
    await vs.delete("a")  # idempotent
    assert await vs.get("a") is None and await vs.search(vec(0, 1)) == []


async def test_tenant_wrapper_isolation(vs):
    t1, t2 = TenantScopedVectorStore(vs, "t1"), TenantScopedVectorStore(vs, "t2")
    await t1.upsert("a", vec(1), {"user_id": "u", "status": "active"})
    assert await t2.get("a") is None
    assert await t2.search(vec(1)) == []
    await t2.delete("a")  # no effect across tenants
    assert await t1.get("a") is not None
    with pytest.raises(TenantViolation):
        await t2.upsert("a", vec(1), {"user_id": "u"})
    with pytest.raises(TenantViolation):
        await t1.update_payload("a", {"tenant_id": "t2"})


@pytest.mark.skipif(not QDRANT, reason="needs Qdrant (set in CI)")
async def test_qdrant_backfill_stamps_only_untenanted_points():
    from adapters.vector_store.qdrant_store import QdrantStore
    host, port = QDRANT.split(":")
    store = QdrantStore(host=host, port=int(port), collection_name=f"backfill_{uuid.uuid4().hex[:8]}")
    await store.initialize(DIM)
    try:
        await store.upsert("legacy-1", vec(1), {"user_id": "u", "status": "active"})
        await store.upsert("legacy-2", vec(0, 1), {"user_id": "u", "status": "active"})
        await store.upsert("new-1", vec(1, 1), {"user_id": "u", "status": "active", "tenant_id": "t9"})
        assert await store.backfill_tenant("default", batch=1) == 2
        assert (await store.get("legacy-1")).payload["tenant_id"] == "default"
        assert (await store.get("new-1")).payload["tenant_id"] == "t9"
        assert await store.backfill_tenant("default") == 0  # idempotent
    finally:
        await (await store._get_client()).delete_collection(store.collection_name)
