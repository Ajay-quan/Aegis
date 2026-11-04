"""Abstract vector store interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class VectorSearchResult:
    id: str
    score: float
    payload: dict[str, Any]


class VectorStore(ABC):
    """Abstract vector store for semantic memory retrieval."""

    @abstractmethod
    async def upsert(
        self,
        id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None: ...

    @abstractmethod
    async def search(
        self,
        query_vector: list[float],
        top_k: int = 10,
        filter: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]: ...

    @abstractmethod
    async def delete(self, id: str) -> None: ...

    @abstractmethod
    async def get(self, id: str) -> VectorSearchResult | None: ...

    @abstractmethod
    async def update_payload(self, id: str, fields: dict[str, Any]) -> None:
        """Merge ``fields`` into a point's payload (e.g. keep ``status`` in sync)."""

    @abstractmethod
    async def initialize(self, dimension: int) -> None: ...
