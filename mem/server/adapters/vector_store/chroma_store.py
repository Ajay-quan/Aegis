"""Optional local persistent ChromaDB vector store adapter."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from adapters.vector_store.base import VectorSearchResult


class ChromaVectorStore:
    """ChromaDB persistent client adapter for single-node local demos."""

    def __init__(self, persist_dir: str | Path, collection_name: str = "aegismem_memories") -> None:
        self.persist_dir = Path(persist_dir)
        self.collection_name = collection_name
        self._client: Any = None
        self._collection: Any = None

    def initialize(self, dimension: int) -> None:
        try:
            import chromadb
        except Exception as exc:  # pragma: no cover - dependency availability
            raise RuntimeError("chromadb is not installed; run `pip install -r requirements.txt`") from exc
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = self._client.get_or_create_collection(name=self.collection_name)

    def upsert(self, id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self._ensure()
        metadata = {k: v for k, v in payload.items() if isinstance(v, str | int | float | bool)}
        self._collection.upsert(
            ids=[id],
            embeddings=[vector],
            metadatas=[metadata],
            documents=[payload.get("content", "")],
        )

    def search(self, query_vector: list[float], top_k: int = 10, filter: dict[str, Any] | None = None) -> list[VectorSearchResult]:
        self._ensure()
        results = self._collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=filter or None,
            include=["metadatas", "distances", "documents"],
        )
        output: list[VectorSearchResult] = []
        ids = results.get("ids", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        for memory_id, distance, metadata in zip(ids, distances, metadatas):
            score = 1.0 / (1.0 + float(distance))
            output.append(VectorSearchResult(id=memory_id, score=score, payload=metadata or {}))
        return output

    def get(self, id: str) -> VectorSearchResult | None:
        self._ensure()
        result = self._collection.get(ids=[id], include=["metadatas"])
        if not result.get("ids"):
            return None
        metadata = result.get("metadatas", [{}])[0] or {}
        return VectorSearchResult(id=id, score=1.0, payload=metadata)

    def delete(self, id: str) -> None:
        self._ensure()
        self._collection.delete(ids=[id])

    def _ensure(self) -> None:
        if self._collection is None:
            raise RuntimeError("ChromaVectorStore.initialize() must be called first")
