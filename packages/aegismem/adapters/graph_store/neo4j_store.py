"""Neo4j graph store adapter for relational memory."""
from __future__ import annotations

import logging
from typing import Any

from core.exceptions import MemoryStorageError

logger = logging.getLogger(__name__)


class GraphStore:
    """Neo4j-backed graph store for entity-relationship memory."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self._driver: Any = None

    async def connect(self) -> None:
        try:
            from neo4j import AsyncGraphDatabase
            self._driver = AsyncGraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            await self._driver.verify_connectivity()
            logger.info("Neo4j connection established")
        except Exception as e:
            logger.warning(f"Neo4j connection failed (graph features disabled): {e}")
            self._driver = None

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()

    def is_available(self) -> bool:
        return self._driver is not None

    async def create_memory_node(self, memory_id: str, properties: dict[str, Any]) -> None:
        if not self._driver:
            return
        async with self._driver.session() as session:
            await session.run(
                """
                MERGE (m:Memory {memory_id: $memory_id})
                SET m += $props
                """,
                memory_id=memory_id,
                props={k: str(v) for k, v in properties.items() if v is not None},
            )

    async def create_entity(self, entity_id: str, entity_type: str, name: str) -> None:
        if not self._driver:
            return
        async with self._driver.session() as session:
            await session.run(
                f"""
                MERGE (e:{entity_type} {{entity_id: $entity_id}})
                SET e.name = $name, e.entity_type = $entity_type
                """,
                entity_id=entity_id,
                name=name,
                entity_type=entity_type,
            )

    async def link_memory_to_entity(
        self, memory_id: str, entity_id: str, relationship: str
    ) -> None:
        if not self._driver:
            return
        async with self._driver.session() as session:
            await session.run(
                f"""
                MATCH (m:Memory {{memory_id: $memory_id}})
                MATCH (e {{entity_id: $entity_id}})
                MERGE (m)-[:{relationship}]->(e)
                """,
                memory_id=memory_id,
                entity_id=entity_id,
            )

    async def create_relationship(
        self,
        from_id: str,
        to_id: str,
        relationship: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        if not self._driver:
            return
        props = properties or {}
        async with self._driver.session() as session:
            await session.run(
                f"""
                MATCH (a {{entity_id: $from_id}})
                MATCH (b {{entity_id: $to_id}})
                MERGE (a)-[r:{relationship}]->(b)
                SET r += $props
                """,
                from_id=from_id,
                to_id=to_id,
                props={k: str(v) for k, v in props.items()},
            )

    async def find_related(
        self,
        entity_id: str,
        relationship: str | None = None,
        depth: int = 2,
    ) -> list[dict[str, Any]]:
        if not self._driver:
            return []
        rel_filter = f":{relationship}" if relationship else ""
        async with self._driver.session() as session:
            result = await session.run(
                f"""
                MATCH (a {{entity_id: $entity_id}})-[r{rel_filter}*1..{depth}]-(b)
                RETURN b, type(r[0]) as rel_type
                LIMIT 50
                """,
                entity_id=entity_id,
            )
            records = await result.data()
            return records

    async def delete_memory_node(self, memory_id: str) -> None:
        if not self._driver:
            return
        async with self._driver.session() as session:
            await session.run(
                "MATCH (m:Memory {memory_id: $memory_id}) DETACH DELETE m",
                memory_id=memory_id,
            )

    async def has_memory_node(self, memory_id: str) -> bool:
        if not self._driver:
            return False
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (m:Memory {memory_id: $memory_id}) RETURN count(m) AS n",
                memory_id=memory_id,
            )
            record = await result.single()
            return bool(record and record["n"])

    async def mark_contradiction(self, memory_a_id: str, memory_b_id: str) -> None:
        if not self._driver:
            return
        async with self._driver.session() as session:
            await session.run(
                """
                MATCH (a:Memory {memory_id: $a_id})
                MATCH (b:Memory {memory_id: $b_id})
                MERGE (a)-[:CONTRADICTS]-(b)
                """,
                a_id=memory_a_id,
                b_id=memory_b_id,
            )

    async def get_memory_chain(self, memory_id: str) -> list[str]:
        """Get parent memory chain (for version history)."""
        if not self._driver:
            return []
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (m:Memory {memory_id: $memory_id})-[:DERIVED_FROM*]->(parent:Memory)
                RETURN parent.memory_id as parent_id
                """,
                memory_id=memory_id,
            )
            records = await result.data()
            return [r["parent_id"] for r in records]


class MockGraphStore(GraphStore):
    """In-memory mock graph store for testing."""

    def __init__(self) -> None:
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: list[tuple[str, str, str]] = []

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def is_available(self) -> bool:
        return True

    async def create_memory_node(self, memory_id: str, properties: dict[str, Any]) -> None:
        self._nodes[memory_id] = properties

    async def create_entity(self, entity_id: str, entity_type: str, name: str) -> None:
        self._nodes[entity_id] = {"type": entity_type, "name": name}

    async def link_memory_to_entity(
        self, memory_id: str, entity_id: str, relationship: str
    ) -> None:
        self._edges.append((memory_id, entity_id, relationship))

    async def create_relationship(
        self, from_id: str, to_id: str, relationship: str, properties: dict[str, Any] | None = None
    ) -> None:
        self._edges.append((from_id, to_id, relationship))

    async def find_related(
        self, entity_id: str, relationship: str | None = None, depth: int = 2
    ) -> list[dict[str, Any]]:
        related = []
        for src, dst, rel in self._edges:
            if src == entity_id or dst == entity_id:
                other = dst if src == entity_id else src
                if relationship is None or rel == relationship:
                    related.append({"entity_id": other, "rel_type": rel})
        return related

    async def delete_memory_node(self, memory_id: str) -> None:
        self._nodes.pop(memory_id, None)
        self._edges = [e for e in self._edges if memory_id not in (e[0], e[1])]

    async def has_memory_node(self, memory_id: str) -> bool:
        return memory_id in self._nodes

    async def mark_contradiction(self, memory_a_id: str, memory_b_id: str) -> None:
        self._edges.append((memory_a_id, memory_b_id, "CONTRADICTS"))

    async def get_memory_chain(self, memory_id: str) -> list[str]:
        return []
