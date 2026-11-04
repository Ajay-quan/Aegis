"""Graph store for deployments without Neo4j (single-store mode). Every operation is a no-op;
erasure verification reports the graph as "not configured" rather than clean-by-accident."""
from __future__ import annotations

from typing import Any


class NullGraphStore:
    configured = False

    async def connect(self) -> None: ...
    async def close(self) -> None: ...

    def is_available(self) -> bool:
        return False

    async def create_memory_node(self, memory_id: str, properties: dict[str, Any]) -> None: ...
    async def create_entity(self, entity_id: str, entity_type: str, name: str) -> None: ...
    async def link_memory_to_entity(self, memory_id: str, entity_id: str, relationship: str) -> None: ...
    async def create_relationship(self, from_id: str, to_id: str, relationship: str,
                                  properties: dict[str, Any] | None = None) -> None: ...

    async def find_related(self, entity_id: str, relationship: str | None = None,
                           depth: int = 2) -> list[dict[str, Any]]:
        return []

    async def mark_contradiction(self, memory_a_id: str, memory_b_id: str) -> None: ...

    async def get_memory_chain(self, memory_id: str) -> list[str]:
        return []

    async def delete_memory_node(self, memory_id: str) -> None: ...

    async def has_memory_node(self, memory_id: str) -> bool:
        return False
