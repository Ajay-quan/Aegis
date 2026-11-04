"""Online, per-user learning of retrieval ranking weights.

Clients report whether each retrieved memory was actually used. Every report is
a labelled example ``(signals, used)``. We fit a logistic model over the ranking
signals with one SGD step per example, then map the coefficients back onto the
weight simplex used by ``compute_composite_score``.

Guardrails:
  * Learned weights are only served after ``min_events`` feedback events.
  * L2 pull toward the global default weights prevents drift on sparse data.
  * Weights are projected to ``[floor, 1]`` and renormalised to sum to 1, so no
    signal can be switched off entirely by a burst of noisy feedback.
  * State is per user and can be reset at any time (the reset is itself an event).

Persistence: each user's state is a ``UserWeightModel`` state machine. ``OnlineWeightLearner``
resolves models through an optional async resolver (the learning runtime), which binds a
durable journal; without one, models live in process memory.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from core.config.settings import settings

SIGNALS: tuple[str, ...] = ("semantic", "recency", "importance", "utility")
COMPONENT_PREFIX = "weights/"

Journal = Callable[[dict[str, Any]], Awaitable[None]]


def default_weights() -> dict[str, float]:
    return {
        "semantic": settings.weight_semantic,
        "recency": settings.weight_recency,
        "importance": settings.weight_importance,
        "utility": settings.weight_utility,
    }


@dataclass
class UserWeightState:
    user_id: str
    weights: dict[str, float] = field(default_factory=default_weights)
    bias: float = 0.0
    events: int = 0
    positives: int = 0
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "weights": {k: round(v, 4) for k, v in self.weights.items()},
            "events": self.events,
            "positives": self.positives,
            "updated_at": self.updated_at,
        }


@dataclass
class LearnerParams:
    learning_rate: float = 0.05
    prior_strength: float = 0.02
    floor: float = 0.05
    scale: float = 4.0  # so weights in [0,1] produce usable logits


class UserWeightModel:
    """Deterministic state machine for one user's ranking weights."""

    def __init__(self, user_id: str, params: LearnerParams | None = None, journal: Journal | None = None):
        self.params = params or LearnerParams()
        self.state = UserWeightState(user_id=user_id)
        self._journal = journal

    async def submit(self, event: dict[str, Any]) -> None:
        event = {**event, "at": datetime.now(timezone.utc).isoformat()}
        if self._journal is not None:
            await self._journal(event)
        else:
            self.apply(event)

    def apply(self, event: dict[str, Any]) -> None:
        if event["type"] == "reset":
            self.state = UserWeightState(user_id=self.state.user_id, updated_at=event.get("at"))
            return
        p, st, prior = self.params, self.state, default_weights()
        for signals, used in event["examples"]:
            x = {s: float(signals.get(s, 0.0)) for s in SIGNALS}
            z = st.bias + p.scale * sum(st.weights[s] * x[s] for s in SIGNALS)
            prob = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            err = (1.0 if used else 0.0) - prob
            for s in SIGNALS:
                grad = err * p.scale * x[s] - p.prior_strength * (st.weights[s] - prior[s])
                st.weights[s] += p.learning_rate * grad
            st.bias += p.learning_rate * err
            st.weights = self._project(st.weights)
            st.events += 1
            st.positives += int(bool(used))
        st.updated_at = event.get("at")

    def _project(self, w: dict[str, float]) -> dict[str, float]:
        clipped = {s: min(1.0, max(self.params.floor, w[s])) for s in SIGNALS}
        total = sum(clipped.values())
        return {s: v / total for s, v in clipped.items()}

    def to_state(self) -> dict[str, Any]:
        return {"params": vars(self.params), "state": vars(self.state)}

    @classmethod
    def from_state(cls, user_id: str, state: dict[str, Any] | None, journal: Journal | None = None):
        if not state:
            return cls(user_id, journal=journal)
        m = cls(user_id, LearnerParams(**state["params"]), journal=journal)
        m.state = UserWeightState(**state["state"])
        return m


Resolver = Callable[[str], Awaitable[UserWeightModel]]


class OnlineWeightLearner:
    def __init__(
        self,
        learning_rate: float = 0.05,
        prior_strength: float = 0.02,
        floor: float = 0.05,
        min_events: int = 20,
        resolver: Resolver | None = None,
    ) -> None:
        self.params = LearnerParams(learning_rate, prior_strength, floor)
        self.min_events = min_events
        self._resolver = resolver
        self._local: dict[str, UserWeightModel] = {}

    @property
    def floor(self) -> float:
        return self.params.floor

    async def _model(self, user_id: str) -> UserWeightModel:
        if self._resolver is not None:
            return await self._resolver(user_id)
        if user_id not in self._local:
            self._local[user_id] = UserWeightModel(user_id, self.params)
        return self._local[user_id]

    async def weights_for(self, user_id: str) -> dict[str, float] | None:
        """Learned weights for ranking, or None if not enough evidence yet."""
        st = (await self._model(user_id)).state
        return dict(st.weights) if st.events >= self.min_events else None

    async def state(self, user_id: str) -> UserWeightState | None:
        st = (await self._model(user_id)).state
        return st if st.events else None

    async def reset(self, user_id: str) -> None:
        await (await self._model(user_id)).submit({"type": "reset"})

    async def observe(
        self, user_id: str, examples: list[tuple[dict[str, float], bool]],
    ) -> UserWeightState:
        model = await self._model(user_id)
        await model.submit({"type": "observe", "examples": [[s, bool(u)] for s, u in examples]})
        return model.state
