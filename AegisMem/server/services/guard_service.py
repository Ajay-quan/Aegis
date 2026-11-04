"""Read-time memory guard: nothing reaches an agent without passing integrity checks.

Vector indexes are caches. Their payloads (status, owner) go stale whenever a memory is
superseded, revoked, quarantined or erased, so the guard re-checks every candidate against
the canonical record before it is served:

    erased / missing      -> withheld
    other user's memory   -> withheld (tenant isolation, defence in depth)
    superseded            -> replaced by its active successor, if one exists
    quarantined (pending) -> withheld
    past valid_to         -> withheld (expired)
    below trust floor     -> withheld

Every decision is recorded, so a retrieval can explain what it did *not* show and why.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.schemas.memory import MemoryItem
from core.config.settings import settings
from domain.integrity.provenance import get_trust
from domain.learning.trust_calibrator import memory_source_origin

logger = logging.getLogger(__name__)


def _val(v: Any) -> str:
    return v.value if hasattr(v, "value") else str(v)


@dataclass
class GuardDecision:
    memory_id: str
    action: str  # "serve" | "replace" | "withhold"
    reason: str = ""
    replaced_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


class MemoryGuard:
    def __init__(
        self,
        relational_store: Any,
        min_trust: float | None = None,
        trust_calibrator: Any | None = None,
    ) -> None:
        self._db = relational_store
        self.min_trust = settings.guard_min_trust if min_trust is None else min_trust
        self._calibrator = trust_calibrator

    async def resolve(
        self, memory_id: str, user_id: str, cache: dict[str, Any] | None = None,
    ) -> tuple[MemoryItem | None, GuardDecision]:
        """Return the memory that may be served for ``memory_id`` (possibly a successor).

        Pass the same ``cache`` dict for all candidates of one retrieval so the
        successor index is built at most once.
        """
        try:
            m = await self._db.get_memory(memory_id)
        except Exception:
            return None, GuardDecision(memory_id, "withhold", "erased")

        if m.user_id != user_id:
            logger.warning(f"Guard blocked cross-user memory {memory_id}")
            return None, GuardDecision(memory_id, "withhold", "owner mismatch")

        status = _val(m.status)
        if status == "superseded":
            succ = await self._explicit_successor(m)
            if succ is None:
                cache = cache if cache is not None else {}
                if "successors" not in cache:
                    cache["successors"] = await self.successor_index(user_id)
                succ = cache["successors"].get(memory_id)
            if succ is not None:
                ok, reason = await self.servable(succ)
                if ok:
                    return succ, GuardDecision(memory_id, "replace", "superseded", succ.memory_id)
            return None, GuardDecision(memory_id, "withhold", "superseded")
        if status != "active":
            reason = "quarantined" if status == "pending" else status
            return None, GuardDecision(memory_id, "withhold", reason)

        ok, reason = await self.servable(m)
        if not ok:
            return None, GuardDecision(memory_id, "withhold", reason)
        return m, GuardDecision(memory_id, "serve")

    async def effective_trust(self, m: MemoryItem) -> float:
        """Trust at write time, lowered (never raised) by what has been learned since.

        This makes learned distrust retroactive: when an origin is found to be bad,
        everything already stored from it stops being served.
        """
        stored = get_trust(m.metadata, default=1.0)
        if self._calibrator is None or "provenance" not in m.metadata:
            return stored
        source, origin = memory_source_origin(m.metadata, m.source_type)
        return min(stored, await self._calibrator.trust(source, origin))

    async def servable(self, m: MemoryItem) -> tuple[bool, str]:
        if _val(m.status) != "active":
            return False, _val(m.status)
        if m.valid_to is not None:
            vt = m.valid_to if m.valid_to.tzinfo else m.valid_to.replace(tzinfo=timezone.utc)
            if vt < datetime.now(timezone.utc):
                return False, "expired"
        if await self.effective_trust(m) < self.min_trust:
            return False, "below trust floor"
        return True, ""

    async def _explicit_successor(self, m: MemoryItem, max_hops: int = 10) -> MemoryItem | None:
        """Follow superseded_by / merged_into pointers to the live end of the chain."""
        current = m
        for _ in range(max_hops):
            nxt = current.metadata.get("superseded_by") or current.metadata.get("merged_into")
            if not nxt:
                break
            try:
                current = await self._db.get_memory(nxt)
            except Exception:
                return None
            if current.user_id != m.user_id:
                return None
        return current if current is not m else None

    async def successor_index(self, user_id: str) -> dict[str, MemoryItem]:
        """Map every superseded ancestor id to the newest active memory that replaced it."""
        active = await self._db.list_memories(user_id=user_id, status="active", limit=1000)
        index: dict[str, MemoryItem] = {}
        for m in sorted(active, key=lambda x: x.version):
            for parent in m.parent_memory_ids:
                index[parent] = m
        return index
