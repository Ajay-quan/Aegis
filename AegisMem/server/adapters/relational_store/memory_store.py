"""In-memory memory store (see InMemoryMemoryStore)."""
from __future__ import annotations

from core.exceptions import MemoryNotFoundError
from core.schemas.memory import MemoryItem


class InMemoryMemoryStore:
    """Process-local implementation of the memory-store interface (dev, tests, benchmarks).

    Mirrors PostgresStore semantics, including hard purge and tenant-filtered listing.
    Not for production: nothing survives a restart.
    """

    def __init__(self):
        self._memories: dict[str, MemoryItem] = {}
        self._facts = []
        self._contradictions = []
        self._logs = []
        self._evals = []

    async def initialize(self):
        pass

    async def save_memory(self, memory: MemoryItem) -> MemoryItem:
        self._memories[memory.memory_id] = memory
        return memory

    async def get_memory(self, memory_id: str) -> MemoryItem:
        if memory_id not in self._memories:
            raise MemoryNotFoundError(memory_id)
        return self._memories[memory_id]

    async def update_memory(self, memory: MemoryItem) -> MemoryItem:
        self._memories[memory.memory_id] = memory
        return memory

    async def delete_memory(self, memory_id: str, user_id: str) -> None:
        if memory_id in self._memories:
            self._memories[memory_id].status = "deleted"

    async def purge_memory(self, memory_id: str, user_id: str) -> None:
        self._memories.pop(memory_id, None)
        self._contradictions = [c for c in self._contradictions
                                if memory_id not in (c["memory_a_id"], c["memory_b_id"])]
        self._logs.append({"memory_id": memory_id, "operation": "purge"})

    async def list_memories(self, user_id: str, namespace: str = "", memory_type: str = "",
                             status: str = "active", limit: int = 50, offset: int = 0,
                             tenant_id: str | None = None) -> list:
        results = [
            m for m in self._memories.values()
            if m.user_id == user_id
            and (tenant_id is None or m.tenant_id == tenant_id)
            and (not status or (m.status if isinstance(m.status, str) else m.status.value) == status)
            and (not namespace or m.namespace == namespace)
            and (not memory_type or (m.memory_type if isinstance(m.memory_type, str) else m.memory_type.value) == memory_type)
        ]
        return results[offset:offset + limit]

    async def count_memories(self, user_id: str, namespace: str = "", tenant_id: str | None = None) -> int:
        return len([m for m in self._memories.values() if m.user_id == user_id
                    and (tenant_id is None or m.tenant_id == tenant_id)
                    and (m.status if isinstance(m.status, str) else m.status.value) == "active"
                    and (not namespace or m.namespace == namespace)])  # same semantics as Postgres

    async def save_fact(self, fact):
        self._facts.append(fact)
        return fact

    async def get_facts_for_user(self, user_id: str, subject: str = ""):
        return []

    async def save_contradiction(self, report_id, a_id, b_id, description, confidence):
        self._contradictions.append({"report_id": report_id, "memory_a_id": a_id, "memory_b_id": b_id,
                                     "description": description, "confidence": confidence,
                                     "resolved": False})

    async def list_contradictions(self, resolved: bool = False):
        return [c for c in self._contradictions if c["resolved"] == resolved]

    async def save_eval_result(self, eval_name, run_id, metrics, config):
        self._evals.append({"eval_name": eval_name, "run_id": run_id})

    async def get_operation_logs(self, memory_id: str):
        return []

    async def ping(self):
        return None

    async def close(self):
        pass


# Name used on the pre-merge main branch.
InMemoryRelationalStore = InMemoryMemoryStore
