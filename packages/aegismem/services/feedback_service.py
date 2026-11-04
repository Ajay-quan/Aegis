"""Retrieval feedback: closes the loop between retrieval and continual learning.

Flow:
    /retrieve  -> RetrievalLedger.record() stores the signals each memory was scored with
    /feedback  -> FeedbackService.submit() looks those signals up, updates per-memory
                  usefulness counters, and trains the per-user OnlineWeightLearner.

Scoring the signals the user actually saw, rather than recomputing them later, keeps
training labels consistent even after recency or access counts change.
"""
from __future__ import annotations

import logging
import math
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from core.schemas.memory import RetrievalResult
from domain.learning import OnlineWeightLearner
from domain.memory.scoring import memory_utility
from core.observability.metrics import inc_policy_update, observe_feedback
from domain.learning.trust_calibrator import memory_source_origin

logger = logging.getLogger(__name__)


@dataclass
class LedgerEntry:
    user_id: str
    signals: dict[str, dict[str, float]]  # memory_id -> signal vector
    consumed: bool = False


def ledger_signals(result: RetrievalResult) -> dict[str, dict[str, float]]:
    return {
        c.memory.memory_id: {
            "semantic": c.semantic_score,
            "recency": c.recency_score,
            "importance": c.importance_score,
            "utility": memory_utility(c.memory),
        }
        for c in result.candidates
    }


class RetrievalLedger:
    """In-process bounded LRU of recent retrievals (dev/test). Production: ``SqlRetrievalLedger``."""

    def __init__(self, capacity: int = 10_000) -> None:
        self._capacity = capacity
        self._entries: OrderedDict[str, LedgerEntry] = OrderedDict()

    async def record(self, result: RetrievalResult) -> None:
        self._entries[result.retrieval_id] = LedgerEntry(result.query.user_id, ledger_signals(result))
        self._entries.move_to_end(result.retrieval_id)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)

    async def get(self, retrieval_id: str) -> LedgerEntry | None:
        return self._entries.get(retrieval_id)

    async def consume(self, retrieval_id: str) -> bool:
        entry = self._entries.get(retrieval_id)
        if entry is None or entry.consumed:
            return False
        entry.consumed = True
        return True


class SqlRetrievalLedger:
    """Durable, tenant-scoped ledger; ``consume`` is atomic across replicas."""

    def __init__(self, store: Any, tenant_id: str) -> None:
        self._store = store
        self._tenant = tenant_id

    async def record(self, result: RetrievalResult) -> None:
        await self._store.put_ledger(self._tenant, result.retrieval_id, result.query.user_id,
                                     ledger_signals(result))

    async def get(self, retrieval_id: str) -> LedgerEntry | None:
        row = await self._store.get_ledger(self._tenant, retrieval_id)
        return LedgerEntry(row["user_id"], row["signals"], row["consumed"]) if row else None

    async def consume(self, retrieval_id: str) -> bool:
        return await self._store.consume_ledger(self._tenant, retrieval_id)


class FeedbackError(ValueError):
    pass


class FeedbackService:
    def __init__(
        self,
        relational_store: Any,
        ledger: RetrievalLedger,
        learner: OnlineWeightLearner,
        trust_calibrator: Any | None = None,
        risk_model: Any | None = None,
    ) -> None:
        self._db = relational_store
        self._ledger = ledger
        self._learner = learner
        self._calibrator = trust_calibrator
        self._risk = risk_model

    async def submit(
        self,
        retrieval_id: str,
        user_id: str,
        used_memory_ids: list[str],
    ) -> dict[str, Any]:
        """Record which retrieved memories were used. Others count as not used.

        Each retrieval accepts feedback once, so retries cannot double-train.
        """
        entry = await self._ledger.get(retrieval_id)
        if entry is None:
            raise FeedbackError("unknown or expired retrieval_id")
        if entry.user_id != user_id:
            raise FeedbackError("retrieval_id does not belong to this user")
        if entry.consumed:
            raise FeedbackError("feedback already submitted for this retrieval")

        used = set(used_memory_ids)
        unknown = used - entry.signals.keys()
        if unknown:
            raise FeedbackError(f"memory ids not in this retrieval: {sorted(unknown)}")

        if not await self._ledger.consume(retrieval_id):  # atomic: concurrent replays lose
            raise FeedbackError("feedback already submitted for this retrieval")

        examples = []
        for memory_id, signals in entry.signals.items():
            was_used = memory_id in used
            examples.append((signals, was_used))
            try:
                memory = await self._db.get_memory(memory_id)
                memory.retrieval_count += 1
                if was_used:
                    memory.successful_retrieval_count += 1
                    await self._implicit_benign(memory)
                await self._db.update_memory(memory)
                if was_used and self._calibrator is not None and "provenance" in memory.metadata:
                    source, origin = memory_source_origin(memory.metadata, memory.source_type)
                    await self._calibrator.record(source, origin, "used")
            except Exception as e:
                logger.warning(f"Feedback counter update failed for {memory_id}: {e}")

        state = await self._learner.observe(user_id, examples)
        observe_feedback(True, "recorded", len(used) / max(len(examples), 1))
        inc_policy_update()
        active = state.events >= self._learner.min_events
        return {
            "accepted": len(examples),
            "used": len(used),
            "learning_active": active,
            "weights": state.to_dict()["weights"],
        }

    async def _implicit_benign(self, memory: Any) -> None:
        """A memory the agent actually used is weak evidence its content is benign.

        Counters the risk model's selection bias (it otherwise only sees labels for items it
        held). Once per memory, one low-weight pass, and only for content that passed both
        screening and the read guard. Measured on aegis-bench `external_injection`: held-out
        FPR 0.20 -> 0.04-0.09 at unchanged recall.
        """
        if self._risk is None or memory.metadata.get("implicit_benign_learned"):
            return
        await self._risk.learn(memory.content, malicious=False, implicit=True)
        memory.metadata["implicit_benign_learned"] = True
