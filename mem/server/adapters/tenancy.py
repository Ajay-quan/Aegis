"""Tenant isolation enforced at the storage boundary.

Services never receive raw stores. DI wraps them per request with the caller's tenant, so
every read is filtered, every write is stamped, and cross-tenant ids behave exactly like
missing ids (no existence oracle). Methods are allow-listed: anything not explicitly scoped
raises, so a new store method cannot silently bypass isolation.
"""
from __future__ import annotations

import logging
from typing import Any

from core.exceptions import MemoryNotFoundError
from core.schemas.memory import MemoryItem
from core.tenancy_context import tenant_context

logger = logging.getLogger(__name__)

TENANT_FIELD = "tenant_id"


class TenantViolation(PermissionError):
    pass


class TenantScopedMemoryStore:
    def __init__(self, inner: Any, tenant_id: str) -> None:
        if not tenant_id:
            raise ValueError("tenant_id required")
        self._inner = inner
        self.tenant_id = tenant_id

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"'{name}' is not tenant-scoped; add it to TenantScopedMemoryStore")

    async def _owned(self, memory_id: str) -> MemoryItem:
        with tenant_context(self.tenant_id):
            m = await self._inner.get_memory(memory_id)
        if m.tenant_id != self.tenant_id:
            logger.warning(f"tenant {self.tenant_id} denied access to memory {memory_id}")
            raise MemoryNotFoundError(memory_id)
        return m

    # -- memories -----------------------------------------------------

    async def save_memory(self, memory: MemoryItem) -> MemoryItem:
        if memory.tenant_id not in (self.tenant_id, "default"):
            raise TenantViolation(f"cannot write memory for tenant {memory.tenant_id}")
        memory.tenant_id = self.tenant_id
        with tenant_context(self.tenant_id):
            return await self._inner.save_memory(memory)

    async def get_memory(self, memory_id: str) -> MemoryItem:
        return await self._owned(memory_id)

    async def update_memory(self, memory: MemoryItem) -> MemoryItem:
        await self._owned(memory.memory_id)
        memory.tenant_id = self.tenant_id
        with tenant_context(self.tenant_id):
            return await self._inner.update_memory(memory)

    async def delete_memory(self, memory_id: str, user_id: str) -> None:
        await self._owned(memory_id)
        with tenant_context(self.tenant_id):
            await self._inner.delete_memory(memory_id, user_id)

    async def purge_memory(self, memory_id: str, user_id: str) -> None:
        await self._owned(memory_id)
        with tenant_context(self.tenant_id):
            await self._inner.purge_memory(memory_id, user_id)

    async def list_memories(self, user_id: str, **kwargs: Any) -> list[MemoryItem]:
        kwargs.pop("tenant_id", None)
        with tenant_context(self.tenant_id):
            return await self._inner.list_memories(user_id=user_id, tenant_id=self.tenant_id, **kwargs)

    async def count_memories(self, user_id: str, namespace: str = "") -> int:
        with tenant_context(self.tenant_id):
            return await self._inner.count_memories(user_id, namespace, tenant_id=self.tenant_id)

    async def get_operation_logs(self, memory_id: str) -> list[dict[str, Any]]:
        await self._owned(memory_id)
        with tenant_context(self.tenant_id):
            return await self._inner.get_operation_logs(memory_id)

    # -- contradictions ---------------------------------------------------

    async def save_contradiction(self, report_id: str, a_id: str, b_id: str,
                                 description: str, confidence: float) -> None:
        await self._owned(a_id)
        await self._owned(b_id)
        with tenant_context(self.tenant_id):
            await self._inner.save_contradiction(report_id, a_id, b_id, description, confidence)

    async def list_contradictions(self, resolved: bool = False) -> list[dict[str, Any]]:
        with tenant_context(self.tenant_id):
            rows = await self._inner.list_contradictions(resolved=resolved)
        out = []
        for r in rows:
            try:
                await self._owned(r.get("memory_a_id") or r.get("a_id", ""))
                out.append(r)
            except MemoryNotFoundError:
                continue
        return out

    # -- non-tenant data ------------------------------------------------

    async def save_eval_result(self, *args: Any, **kwargs: Any) -> Any:
        with tenant_context(self.tenant_id):
            return await self._inner.save_eval_result(*args, **kwargs)


class TenantScopedVectorStore:
    def __init__(self, inner: Any, tenant_id: str) -> None:
        if not tenant_id:
            raise ValueError("tenant_id required")
        self._inner = inner
        self.tenant_id = tenant_id

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"'{name}' is not tenant-scoped; add it to TenantScopedVectorStore")

    async def initialize(self, dimension: int) -> None:
        with tenant_context(self.tenant_id):
            await self._inner.initialize(dimension)

    async def upsert(self, id: str, vector: list[float], payload: dict[str, Any]) -> None:
        with tenant_context(self.tenant_id):
            existing = await self._inner.get(id)
        if existing is not None and existing.payload.get(TENANT_FIELD) != self.tenant_id:
            raise TenantViolation("vector id belongs to another tenant")
        with tenant_context(self.tenant_id):
            await self._inner.upsert(id, vector, {**payload, TENANT_FIELD: self.tenant_id})

    async def search(self, query_vector: list[float], top_k: int = 10,
                     filter: dict[str, Any] | None = None) -> list[Any]:
        with tenant_context(self.tenant_id):
            return await self._inner.search(
            query_vector=query_vector, top_k=top_k,
            filter={**(filter or {}), TENANT_FIELD: self.tenant_id},
        )

    async def get(self, id: str) -> Any:
        with tenant_context(self.tenant_id):
            r = await self._inner.get(id)
        return r if r is not None and r.payload.get(TENANT_FIELD) == self.tenant_id else None

    async def delete(self, id: str) -> None:
        # Delegate unless the id is visibly another tenant's: deleting a not-yet-indexed id
        # must still reach the inner store so pending index repairs are cancelled.
        with tenant_context(self.tenant_id):
            r = await self._inner.get(id)
        if r is not None and r.payload.get(TENANT_FIELD) != self.tenant_id:
            return
        with tenant_context(self.tenant_id):
            await self._inner.delete(id)

    async def enqueue_upsert(self, id: str) -> None:
        enqueue = getattr(self._inner, "enqueue_upsert", None)
        if enqueue is None:
            raise AttributeError("inner store has no repair queue")
        await enqueue(id)

    async def update_payload(self, id: str, fields: dict[str, Any]) -> None:
        if TENANT_FIELD in fields:
            raise TenantViolation("tenant_id is immutable")
        if await self.get(id) is not None:
            with tenant_context(self.tenant_id):
                await self._inner.update_payload(id, fields)
