"""Keeps the vector index eventually consistent with the canonical store.

``ResilientVectorStore`` wraps the raw index for one tenant. Index writes that fail inline
(upsert, status sync, delete) are recorded in the durable outbox instead of being lost, and
``OutboxWorker`` replays them with exponential backoff, dead-lettering after ``max_attempts``.

Invariants:
  * The outbox stores ids and status fields, never content. Upserts re-read and re-embed the
    canonical memory at replay time, so they always index the latest version.
  * Deleting a memory cancels its pending upserts and status syncs first, so an erased memory
    can never be re-indexed by a late retry.
  * A replayed upsert for a memory that no longer exists is a no-op (it was erased).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.exceptions import MemoryNotFoundError
from core.observability.metrics import OUTBOX_PROCESSED
from core.tenancy_context import system_context

logger = logging.getLogger(__name__)


def index_payload(memory: Any) -> dict[str, Any]:
    """The single definition of what the vector index stores for a memory."""
    def v(x: Any) -> Any:
        return x.value if hasattr(x, "value") else x
    return {
        "user_id": memory.user_id,
        "tenant_id": memory.tenant_id,
        "namespace": memory.namespace,
        "memory_type": v(memory.memory_type),
        "memory_layer": v(memory.memory_layer),
        "content": memory.content[:500],
        "importance_score": memory.importance_score,
        "status": v(memory.status),
    }


class ResilientVectorStore:
    def __init__(self, inner: Any, control: Any, tenant_id: str) -> None:
        self._inner = inner
        self._control = control
        self.tenant_id = tenant_id

    async def initialize(self, dimension: int) -> None:
        await self._inner.initialize(dimension)

    async def search(self, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.search(*args, **kwargs)

    async def get(self, id: str) -> Any:
        return await self._inner.get(id)

    async def upsert(self, id: str, vector: list[float], payload: dict[str, Any]) -> None:
        try:
            await self._inner.upsert(id, vector, payload)
        except Exception as e:
            logger.warning(f"index upsert failed for {id}, queued for repair: {e}")
            await self.enqueue_upsert(id)

    async def update_payload(self, id: str, fields: dict[str, Any]) -> None:
        try:
            await self._inner.update_payload(id, fields)
        except Exception as e:
            logger.warning(f"index status sync failed for {id}, queued for repair: {e}")
            await self._control.enqueue_outbox(self.tenant_id, id, "status", fields)

    async def delete(self, id: str) -> None:
        await self._control.cancel_outbox(self.tenant_id, id, ("upsert", "status"))
        try:
            await self._inner.delete(id)
        except Exception as e:
            logger.warning(f"index delete failed for {id}, queued for repair: {e}")
            await self._control.enqueue_outbox(self.tenant_id, id, "delete")
            raise  # erasure must not report success while the vector still exists

    async def enqueue_upsert(self, id: str) -> None:
        await self._control.enqueue_outbox(self.tenant_id, id, "upsert")


class OutboxWorker:
    def __init__(
        self, control: Any, raw_db: Any, raw_vs: Any, embedding: Any,
        max_attempts: int = 8, batch: int = 100,
    ) -> None:
        self._control = control
        self._db = raw_db
        self._vs = raw_vs
        self._embed = embedding
        self.max_attempts = max_attempts
        self.batch = batch

    async def drain_once(self) -> dict[str, int]:
        with system_context():  # cross-tenant system job; tenant checked per record below
            return await self._drain()

    async def _drain(self) -> dict[str, int]:
        stats = {"done": 0, "retry": 0, "dead": 0}
        for rec in await self._control.due_outbox(self.batch):
            try:
                await self._apply(rec)
                await self._control.finish_outbox(rec.seq)
                stats["done"] += 1
                OUTBOX_PROCESSED.labels(rec.op, "done").inc()
            except Exception as e:
                state = await self._control.retry_outbox(rec.seq, repr(e), self.max_attempts)
                key = "dead" if state == "dead" else "retry"
                stats[key] += 1
                OUTBOX_PROCESSED.labels(rec.op, key).inc()
                if state == "dead":
                    logger.error(f"outbox op {rec.op} for {rec.memory_id} dead-lettered: {e}")
        return stats

    async def _apply(self, rec: Any) -> None:
        if rec.op == "delete":
            await self._vs.delete(rec.memory_id)
            return
        try:
            memory = await self._db.get_memory(rec.memory_id)
        except MemoryNotFoundError:
            return  # erased since enqueue: nothing to index
        if memory.tenant_id != rec.tenant_id:
            raise PermissionError("outbox tenant mismatch")
        if rec.op == "upsert":
            vector = await self._embed.embed_single(memory.content)
            await self._vs.upsert(memory.memory_id, vector, index_payload(memory))
        elif rec.op == "status":
            await self._vs.update_payload(memory.memory_id, rec.fields)
        else:
            raise ValueError(f"unknown outbox op {rec.op}")

    async def maintenance(self, ledger_hours: int, idempotency_hours: int) -> dict[str, int]:
        """Prune operational records so control-plane tables stay bounded."""
        from datetime import timedelta
        return {
            "ledger_pruned": await self._control.prune_ledger(timedelta(hours=ledger_hours)),
            "idempotency_pruned": await self._control.prune_idempotency(timedelta(hours=idempotency_hours)),
        }

    async def run_forever(self, interval_s: float = 5.0, maintenance_every: int = 720,
                          ledger_hours: int = 168, idempotency_hours: int = 24) -> None:
        ticks = 0
        while True:
            try:
                await self.drain_once()
                if ticks % maintenance_every == 0:  # ~hourly at the default 5s interval
                    logger.info(f"maintenance: {await self.maintenance(ledger_hours, idempotency_hours)}")
                ticks += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:  # never let the loop die
                logger.error(f"outbox drain failed: {e}")
            await asyncio.sleep(interval_s)
