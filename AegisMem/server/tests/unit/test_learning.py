"""Tests for the online per-user weight learner."""
import pytest

from domain.learning import OnlineWeightLearner, SIGNALS
from domain.learning.weight_learner import default_weights


def _semantic_wins(n: int):
    """Feedback where only high-semantic, low-recency memories get used."""
    ex = []
    for _ in range(n):
        ex.append(({"semantic": 0.9, "recency": 0.1, "importance": 0.5, "utility": 0.1}, True))
        ex.append(({"semantic": 0.2, "recency": 0.9, "importance": 0.5, "utility": 0.1}, False))
    return ex


class TestOnlineWeightLearner:
    async def test_inactive_until_min_events(self):
        learner = OnlineWeightLearner(min_events=20)
        await learner.observe("u", _semantic_wins(5))  # 10 events
        assert await learner.weights_for("u") is None

    async def test_learns_toward_useful_signal(self):
        """When recency (not semantics) predicts usage, weight shifts toward recency."""
        learner = OnlineWeightLearner(min_events=20)
        ex = []
        for _ in range(100):
            ex.append(({"semantic": 0.5, "recency": 0.95, "importance": 0.5, "utility": 0.5}, True))
            ex.append(({"semantic": 0.5, "recency": 0.05, "importance": 0.5, "utility": 0.5}, False))
        await learner.observe("u", ex)
        w = await learner.weights_for("u")
        d = default_weights()
        assert w["recency"] > d["recency"]
        assert w["semantic"] < d["semantic"]

    async def test_weights_stay_on_bounded_simplex(self):
        learner = OnlineWeightLearner(min_events=1, learning_rate=0.5, floor=0.05)
        await learner.observe("u", _semantic_wins(500))
        w = await learner.weights_for("u")
        assert sum(w.values()) == pytest.approx(1.0)
        assert all(w[s] >= 0.04 for s in SIGNALS)

    async def test_users_are_isolated_and_resettable(self):
        learner = OnlineWeightLearner(min_events=1)
        await learner.observe("a", _semantic_wins(50))
        assert await learner.weights_for("b") is None
        await learner.reset("a")
        assert await learner.state("a") is None
