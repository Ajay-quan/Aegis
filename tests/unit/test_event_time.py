"""Time correctness: recency follows when information is from, and retrieval does not refresh it."""
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient

from apps.api import dependencies as deps
from apps.api.main import app
from core.schemas.memory import MemoryItem, RetrievalQuery
from domain.memory.scoring import compute_recency_score


def test_recency_uses_event_time_not_storage_time():
    old = MemoryItem(namespace="n", user_id="u", content="x",
                     event_time=datetime.now(timezone.utc) - timedelta(days=60))
    new = MemoryItem(namespace="n", user_id="u", content="y", event_time=datetime.now(timezone.utc))
    assert compute_recency_score(old) < compute_recency_score(new)


def test_access_does_not_change_updated_at():
    m = MemoryItem(namespace="n", user_id="u", content="x")
    before = m.updated_at
    m.bump_access()
    assert m.updated_at == before and m.access_count == 1


async def test_api_accepts_event_time(monkeypatch):
    from adapters.relational_store.memory_store import InMemoryMemoryStore
    db = InMemoryMemoryStore()
    monkeypatch.setitem(app.dependency_overrides, deps.get_raw_db_store, lambda: db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/v1/ingest", json={"text": "User moved to Austin", "user_id": "u",
                                                 "event_time": "2023-05-30T12:00:00Z"})
    assert r.status_code == 201
    stored = next(iter(db._memories.values()))
    assert stored.event_time.year == 2023 and stored.event_time.month == 5
