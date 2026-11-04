"""pgvector-backed vector store: single-database deployments (Postgres holds everything).

Postgres: ``vector(dim)`` column, cosine distance via ``<=>``, HNSW index (migration 0003).
SQLite (development and tests only): embeddings stored as JSON, cosine computed in Python over
the column-filtered candidates.

``tenant_id``, ``user_id`` and ``status`` are real columns so tenant and status filters are
index-backed; any other filter key is matched against the JSON payload.
"""
from __future__ import annotations

import logging
import math
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from adapters.relational_store.vector_models import MemoryVector
from adapters.vector_store.base import VectorSearchResult, VectorStore
from core.tenancy_context import apply_rls

logger = logging.getLogger(__name__)

_COLUMNS = ("tenant_id", "user_id", "status")


class PgVectorStore(VectorStore):
    def __init__(self, database_url: str | None = None, engine: AsyncEngine | None = None) -> None:
        if engine is None:
            kwargs: dict[str, Any] = {"pool_pre_ping": True}
            if database_url and not database_url.startswith("sqlite"):
                kwargs.update(pool_size=10, max_overflow=20)
            engine = create_async_engine(database_url, **kwargs)
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._dim = 0

    @property
    def _is_pg(self) -> bool:
        return self._engine.dialect.name == "postgresql"

    async def initialize(self, dimension: int) -> None:
        """Schema is owned by Alembic (0003). Dev/test on SQLite creates the table directly."""
        self._dim = dimension
        if not self._is_pg:
            async with self._engine.begin() as conn:
                await conn.run_sync(MemoryVector.__table__.create, checkfirst=True)

    async def ping(self) -> None:
        async with self._engine.connect() as conn:
            await conn.exec_driver_sql("SELECT 1")

    async def close(self) -> None:
        await self._engine.dispose()

    def _check_dim(self, vector: list[float]) -> None:
        if self._dim and len(vector) != self._dim:
            raise ValueError(f"embedding has {len(vector)} dims, store expects {self._dim}")

    async def upsert(self, id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self._check_dim(vector)
        cols = {c: str(payload.get(c, "")) for c in _COLUMNS}
        async with self._sessions.begin() as s:
            await apply_rls(s)
            row = await s.get(MemoryVector, id)
            if row is None:
                s.add(MemoryVector(id=id, embedding=list(vector), payload=dict(payload), **cols))
            else:
                row.embedding, row.payload = list(vector), dict(payload)
                for k, v in cols.items():
                    setattr(row, k, v)

    async def update_payload(self, id: str, fields: dict[str, Any]) -> None:
        async with self._sessions.begin() as s:
            await apply_rls(s)
            row = await s.get(MemoryVector, id)
            if row is None:
                return
            row.payload = {**(row.payload or {}), **fields}
            for c in _COLUMNS:
                if c in fields:
                    setattr(row, c, str(fields[c]))

    async def get(self, id: str) -> VectorSearchResult | None:
        async with self._sessions() as s:
            await apply_rls(s)
            row = await s.get(MemoryVector, id)
            return VectorSearchResult(id=row.id, score=1.0, payload=row.payload or {}) if row else None

    async def delete(self, id: str) -> None:
        async with self._sessions.begin() as s:
            await apply_rls(s)
            row = await s.get(MemoryVector, id)
            if row is not None:
                await s.delete(row)

    async def search(
        self, query_vector: list[float], top_k: int = 10, filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        self._check_dim(query_vector)
        filter = filter or {}
        col_filters = {k: str(v) for k, v in filter.items() if k in _COLUMNS}
        json_filters = {k: v for k, v in filter.items() if k not in _COLUMNS}
        stmt = select(MemoryVector)
        for k, v in col_filters.items():
            stmt = stmt.where(getattr(MemoryVector, k) == v)

        async with self._sessions() as s:
            await apply_rls(s)
            if self._is_pg:
                dist = MemoryVector.embedding.cosine_distance(query_vector)
                fetch = top_k * 4 if json_filters else top_k
                rows = (await s.execute(stmt.add_columns(dist).order_by(dist).limit(fetch))).all()
                scored = [(r[0], 1.0 - float(r[1])) for r in rows]
            else:
                rows = (await s.execute(stmt)).scalars().all()
                scored = [(r, _cosine(query_vector, r.embedding)) for r in rows]
                scored.sort(key=lambda x: x[1], reverse=True)

        out = []
        for row, score in scored:
            if any((row.payload or {}).get(k) != v for k, v in json_filters.items()):
                continue
            out.append(VectorSearchResult(id=row.id, score=score, payload=row.payload or {}))
            if len(out) >= top_k:
                break
        return out


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb + 1e-9)
