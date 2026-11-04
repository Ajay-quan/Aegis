"""Per-tenant rate limits."""
import os

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api import ratelimit
from apps.api.main import app
from apps.api.ratelimit import InProcessRateLimiter
from core.config.settings import settings


async def test_token_bucket_refills():
    rl = InProcessRateLimiter()
    assert all([(await rl.hit("t:read", 60, 3)).allowed for _ in range(3)])
    d = await rl.hit("t:read", 60, 3)
    assert not d.allowed and d.retry_after_s == 1
    key, tokens_ts = "t:read", rl._buckets["t:read"]
    rl._buckets[key] = (tokens_ts[0], tokens_ts[1] - 2)  # 2s later at 1 token/s
    assert (await rl.hit("t:read", 60, 3)).allowed


async def test_api_returns_429_with_retry_after_and_isolates_classes(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_backend", "memory")
    monkeypatch.setattr(settings, "rate_limit_read_burst", 2)
    monkeypatch.setattr(settings, "rate_limit_read_per_minute", 1)
    monkeypatch.setattr(ratelimit, "_limiter", InProcessRateLimiter())
    from adapters.relational_store.memory_store import InMemoryMemoryStore
    from apps.api import dependencies as deps
    monkeypatch.setitem(app.dependency_overrides, deps.get_raw_db_store, InMemoryMemoryStore)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        codes = [(await c.get("/api/v1/trust/sources")).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        r = await c.get("/api/v1/trust/sources")
        assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
        # writes have their own bucket
        assert (await c.post("/api/v1/feedback", json={"retrieval_id": "x", "user_id": "u"})).status_code == 422


@pytest.mark.skipif(not os.environ.get("AEGIS_TEST_REDIS_URL"), reason="needs Redis (set in CI)")
async def test_redis_limiter_is_shared_across_instances():
    from apps.api.ratelimit import RedisRateLimiter
    url = os.environ["AEGIS_TEST_REDIS_URL"]
    a, b = RedisRateLimiter(url), RedisRateLimiter(url)
    key = f"test:{os.getpid()}"
    await a._redis.delete(f"aegis:rl:{key}")
    results = [await (a if i % 2 else b).hit(key, 60, 4) for i in range(6)]
    assert [r.allowed for r in results] == [True] * 4 + [False] * 2
