"""Per-tenant rate limiting (token bucket).

Buckets are keyed by ``tenant:class`` where class is ``read`` (memory:read routes) or ``write``
(everything else), so a bulk import cannot starve a tenant's interactive reads.

Backends:
  * ``redis``: atomic Lua script; correct across any number of API replicas.
  * ``memory``: process-local; correct for a single replica and for development.
  * ``off``: disabled.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Protocol

from core.config.settings import settings


@dataclass
class Decision:
    allowed: bool
    remaining: int
    retry_after_s: int


class RateLimiter(Protocol):
    async def hit(self, key: str, rate_per_min: int, burst: int) -> Decision: ...


class InProcessRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)

    async def hit(self, key: str, rate_per_min: int, burst: int) -> Decision:
        now = time.monotonic()
        rate = rate_per_min / 60.0
        tokens, last = self._buckets.get(key, (float(burst), now))
        tokens = min(float(burst), tokens + (now - last) * rate)
        if tokens >= 1.0:
            self._buckets[key] = (tokens - 1.0, now)
            return Decision(True, int(tokens - 1.0), 0)
        self._buckets[key] = (tokens, now)
        return Decision(False, 0, max(1, math.ceil((1.0 - tokens) / rate)))


_LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])   -- tokens per second
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1]) or burst
local ts = tonumber(data[2]) or now
tokens = math.min(burst, tokens + (now - ts) * rate)
local allowed = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, math.ceil(burst / rate) + 60)
return {allowed, tostring(tokens)}
"""


class RedisRateLimiter:
    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis
        self._redis = aioredis.from_url(url)
        self._script = self._redis.register_script(_LUA)

    async def hit(self, key: str, rate_per_min: int, burst: int) -> Decision:
        rate = rate_per_min / 60.0
        allowed, tokens = await self._script(keys=[f"aegis:rl:{key}"], args=[rate, burst, time.time()])
        tokens = float(tokens)
        if int(allowed):
            return Decision(True, int(tokens), 0)
        return Decision(False, 0, max(1, math.ceil((1.0 - tokens) / rate)))


_limiter: RateLimiter | None = None


def get_limiter() -> RateLimiter | None:
    global _limiter
    if settings.rate_limit_backend == "off":
        return None
    if _limiter is None:
        _limiter = (RedisRateLimiter(settings.redis_url) if settings.rate_limit_backend == "redis"
                    else InProcessRateLimiter())
    return _limiter


def limits_for(scope: str) -> tuple[str, int, int]:
    if scope == "memory:read":
        return "read", settings.rate_limit_read_per_minute, settings.rate_limit_read_burst
    return "write", settings.rate_limit_write_per_minute, settings.rate_limit_write_burst
