"""Qdrant vector store adapter."""
from __future__ import annotations

import logging
import uuid
from typing import Any

from core.exceptions import MemoryStorageError
from .base import VectorStore, VectorSearchResult

logger = logging.getLogger(__name__)


_POINT_NS = uuid.UUID("6f1c2b1e-6a8e-4d55-9a8e-2f0b6b8f3c11")


def _point_id(memory_id: str) -> str:
    """Stable Qdrant point id. Must not use hash(): it is salted per process,
    so ids would change on restart and deletes would silently miss."""
    return str(uuid.uuid5(_POINT_NS, memory_id))


point_id_for = _point_id  # public alias (used by migrations/tools)


class QdrantStore(VectorStore):
    """Qdrant-backed vector store."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        collection_name: str = "aegismem_memories",
    ) -> None:
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self._client: Any = None

    async def _get_client(self) -> Any:
        if self._client is None:
            try:
                from qdrant_client import AsyncQdrantClient
                self._client = AsyncQdrantClient(host=self.host, port=self.port)
            except Exception as e:
                raise MemoryStorageError(f"Qdrant connection failed: {e}") from e
        return self._client

    async def initialize(self, dimension: int) -> None:
        from qdrant_client.models import Distance, VectorParams
        client = await self._get_client()
        collections = await client.get_collections()
        existing = [c.name for c in collections.collections]
        if self.collection_name not in existing:
            await client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection: {self.collection_name} (dim={dimension})")
        else:
            logger.info(f"Qdrant collection already exists: {self.collection_name}")

    async def upsert(
        self, id: str, vector: list[float], payload: dict[str, Any]
    ) -> None:
        from qdrant_client.models import PointStruct
        client = await self._get_client()
        point_id = _point_id(id)
        payload["_aegis_id"] = id  # store original string id
        await client.upsert(
            collection_name=self.collection_name,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = await self._get_client()
        qdrant_filter = None
        if filter:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filter.items()
            ]
            if conditions:
                from qdrant_client.models import Filter as QFilter
                qdrant_filter = QFilter(must=conditions)

        # query_points replaces the removed `search` API (qdrant-client >= 1.12).
        response = await client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        )
        results = response.points

        return [
            VectorSearchResult(
                id=r.payload.get("_aegis_id", str(r.id)) if r.payload else str(r.id),
                score=r.score,
                payload=r.payload or {},
            )
            for r in results
        ]

    async def delete(self, id: str) -> None:
        from qdrant_client.models import PointIdsList
        client = await self._get_client()
        point_id = _point_id(id)
        await client.delete(
            collection_name=self.collection_name,
            points_selector=PointIdsList(points=[point_id]),
        )

    async def backfill_tenant(self, tenant_id: str, batch: int = 256) -> int:
        """Stamp tenant_id on points written before tenancy (they are invisible under tenant filters)."""
        from qdrant_client.models import Filter, IsEmptyCondition, PayloadField
        client = await self._get_client()
        missing = Filter(must=[IsEmptyCondition(is_empty=PayloadField(key="tenant_id"))])
        updated, offset = 0, None
        while True:
            points, offset = await client.scroll(self.collection_name, scroll_filter=missing,
                                                 limit=batch, offset=offset, with_payload=False)
            if not points:
                return updated
            await client.set_payload(self.collection_name, payload={"tenant_id": tenant_id},
                                     points=[p.id for p in points])
            updated += len(points)
            if offset is None:
                return updated

    async def update_payload(self, id: str, fields: dict[str, Any]) -> None:
        client = await self._get_client()
        await client.set_payload(
            collection_name=self.collection_name,
            payload=fields,
            points=[_point_id(id)],
        )

    async def get(self, id: str) -> VectorSearchResult | None:
        client = await self._get_client()
        point_id = _point_id(id)
        try:
            results = await client.retrieve(
                collection_name=self.collection_name,
                ids=[point_id],
                with_payload=True,
            )
            if results:
                r = results[0]
                return VectorSearchResult(
                    id=r.payload.get("_aegis_id", str(r.id)) if r.payload else str(r.id),
                    score=1.0,
                    payload=r.payload or {},
                )
        except Exception:
            pass
        return None


class InMemoryVectorStore(VectorStore):
    """Simple in-memory vector store for testing/development."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[list[float], dict[str, Any]]] = {}
        self._dim = 0

    async def initialize(self, dimension: int) -> None:
        self._dim = dimension
        logger.info(f"InMemoryVectorStore initialized (dim={dimension})")

    async def upsert(self, id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self._store[id] = (vector, payload)

    async def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        import numpy as np
        qv = np.array(query_vector)
        scores = []
        for id, (vec, payload) in self._store.items():
            # Apply filters
            if filter:
                if not all(payload.get(k) == v for k, v in filter.items()):
                    continue
            v = np.array(vec)
            score = float(np.dot(qv, v) / (np.linalg.norm(qv) * np.linalg.norm(v) + 1e-9))
            scores.append(VectorSearchResult(id=id, score=score, payload=payload))
        scores.sort(key=lambda x: x.score, reverse=True)
        return scores[:top_k]

    async def delete(self, id: str) -> None:
        self._store.pop(id, None)

    async def update_payload(self, id: str, fields: dict[str, Any]) -> None:
        if id in self._store:
            self._store[id][1].update(fields)

    async def get(self, id: str) -> VectorSearchResult | None:
        if id in self._store:
            vec, payload = self._store[id]
            return VectorSearchResult(id=id, score=1.0, payload=payload)
        return None
