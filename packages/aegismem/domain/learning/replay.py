"""Replay buffer — the continual-learning substrate.

Every retrieval logs the served candidates and their feature vectors here. When
feedback arrives later, the matching interaction is found and a reward is
attached. This buffer is therefore three things at once:

* the **feedback join table** (query_id -> served candidates) used to turn a
  late ``/feedback`` call into a labeled training example;
* the **experience-replay store** for any parametric loop (L2 reranker, L3
  embedder) — ``sample()`` draws a uniform slice of historical labeled
  examples, the strongest known defense against catastrophic forgetting;
* the **audit log** of what the system retrieved and why.

Bounded ring buffer, pure stdlib, optional JSON persistence. Reservoir-style
uniform sampling keeps replay representative without unbounded growth.
"""
from __future__ import annotations

import json
import os
import random
import threading
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Iterable


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CandidateRecord:
    """One served candidate within a retrieval interaction."""

    memory_id: str
    features: dict[str, float]
    served_rank: int
    score: float
    reward: float | None = None  # filled in when feedback arrives


@dataclass
class RetrievalInteraction:
    """A single logged retrieval: a query and the candidates it served."""

    query_id: str
    user_id: str
    namespace: str
    query_text: str
    candidates: list[CandidateRecord] = field(default_factory=list)
    created_at: str = field(default_factory=_utcnow_iso)

    def candidate(self, memory_id: str) -> CandidateRecord | None:
        for c in self.candidates:
            if c.memory_id == memory_id:
                return c
        return None


class ReplayBuffer:
    """Bounded, thread-safe store of retrieval interactions + labeled examples."""

    def __init__(self, capacity: int = 5000, seed: int | None = None) -> None:
        self.capacity = int(capacity)
        self._interactions: "OrderedDict[str, RetrievalInteraction]" = OrderedDict()
        # Flat list of labeled (features, reward, namespace) for replay sampling.
        self._labeled: list[tuple[dict[str, float], float, str]] = []
        self._rng = random.Random(seed)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ write
    def log(
        self,
        query_id: str,
        user_id: str,
        namespace: str,
        query_text: str,
        candidates: Iterable[CandidateRecord],
    ) -> RetrievalInteraction:
        interaction = RetrievalInteraction(
            query_id=query_id,
            user_id=user_id,
            namespace=namespace,
            query_text=query_text,
            candidates=list(candidates),
        )
        with self._lock:
            self._interactions[query_id] = interaction
            self._interactions.move_to_end(query_id)
            while len(self._interactions) > self.capacity:
                self._interactions.popitem(last=False)
        return interaction

    def attach_reward(self, query_id: str, memory_id: str, reward: float) -> bool:
        """Label a served candidate with an observed reward."""
        with self._lock:
            interaction = self._interactions.get(query_id)
            if interaction is None:
                return False
            cand = interaction.candidate(memory_id)
            if cand is None:
                return False
            cand.reward = float(reward)
            self._labeled.append((dict(cand.features), float(reward), interaction.namespace))
            # Keep labeled set bounded too.
            if len(self._labeled) > self.capacity:
                self._labeled = self._labeled[-self.capacity:]
            return True

    # ------------------------------------------------------------------- read
    def get(self, query_id: str) -> RetrievalInteraction | None:
        with self._lock:
            return self._interactions.get(query_id)

    def sample(
        self,
        n: int,
        namespace: str | None = None,
    ) -> list[tuple[dict[str, float], float, str]]:
        """Uniformly sample labeled examples for experience replay."""
        with self._lock:
            pool = self._labeled
            if namespace is not None:
                pool = [ex for ex in pool if ex[2] == namespace]
            if not pool:
                return []
            n = min(n, len(pool))
            return self._rng.sample(pool, n)

    def __len__(self) -> int:
        with self._lock:
            return len(self._interactions)

    def labeled_count(self) -> int:
        with self._lock:
            return len(self._labeled)

    def stats(self) -> dict:
        with self._lock:
            rewards = [r for _, r, _ in self._labeled]
            return {
                "interactions": len(self._interactions),
                "labeled": len(self._labeled),
                "avg_reward": round(sum(rewards) / len(rewards), 4) if rewards else 0.0,
                "capacity": self.capacity,
            }

    # ------------------------------------------------------------ persistence
    def save(self, path: str) -> None:
        """Persist interactions to a JSON file (optional durability)."""
        with self._lock:
            payload = {
                "interactions": [
                    {**asdict(i)} for i in self._interactions.values()
                ],
                "labeled": [
                    {"features": f, "reward": r, "namespace": ns}
                    for f, r, ns in self._labeled
                ],
            }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, path)

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        with self._lock:
            self._interactions.clear()
            for i in payload.get("interactions", []):
                cands = [CandidateRecord(**c) for c in i.get("candidates", [])]
                interaction = RetrievalInteraction(
                    query_id=i["query_id"],
                    user_id=i.get("user_id", ""),
                    namespace=i.get("namespace", ""),
                    query_text=i.get("query_text", ""),
                    candidates=cands,
                    created_at=i.get("created_at", _utcnow_iso()),
                )
                self._interactions[interaction.query_id] = interaction
            self._labeled = [
                (ex["features"], ex["reward"], ex["namespace"])
                for ex in payload.get("labeled", [])
            ]
