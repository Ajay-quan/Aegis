"""Unit tests for memory scoring module."""
import math
import pytest
from datetime import datetime, timedelta, timezone

from core.schemas.memory import MemoryItem, MemoryType
from domain.memory.scoring import (
    compute_recency_score,
    compute_importance_heuristic,
    compute_composite_score,
    compute_type_boost,
    rank_candidates,
    score_memory_for_retrieval,
)


def make_memory(content: str, age_hours: float = 0, importance: float = 0.5) -> MemoryItem:
    created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return MemoryItem(
        namespace="user:test",
        user_id="test",
        memory_type=MemoryType.OBSERVATION,
        content=content,
        importance_score=importance,
        created_at=created,
        updated_at=created,
    )


class TestRecencyScore:
    def test_fresh_memory_scores_near_one(self):
        memory = make_memory("fresh content", age_hours=0)
        score = compute_recency_score(memory)
        assert score > 0.99

    def test_old_memory_scores_lower(self):
        fresh = make_memory("fresh", age_hours=1)
        old = make_memory("old", age_hours=200)
        assert compute_recency_score(fresh) > compute_recency_score(old)

    def test_score_between_zero_and_one(self):
        memory = make_memory("content", age_hours=500)
        score = compute_recency_score(memory)
        assert 0.0 <= score <= 1.0

    def test_exponential_decay(self):
        memory = make_memory("content", age_hours=168)
        score = compute_recency_score(memory, decay_hours=168)
        assert abs(score - math.exp(-1.0)) < 0.01  # exp(-1) ≈ 0.367


class TestImportanceHeuristic:
    def test_preference_words_boost_score(self):
        low = compute_importance_heuristic("The weather is nice today")
        high = compute_importance_heuristic("I prefer Python and always use it for ML")
        assert high > low

    def test_score_capped_at_one(self):
        content = "prefer always critical important goal deadline must need require"
        score = compute_importance_heuristic(content)
        assert score <= 1.0

    def test_score_above_base(self):
        score = compute_importance_heuristic("anything")
        assert score >= 0.4  # base score

    def test_long_content_bonus(self):
        short = compute_importance_heuristic("short")
        long = compute_importance_heuristic("x" * 300)
        assert long >= short


class TestCompositeScore:
    def test_all_ones_returns_one(self):
        score = compute_composite_score(1.0, 1.0, 1.0, utility=1.0)
        assert score <= 1.0
        assert score > 0.95

    def test_all_zeros_returns_zero(self):
        score = compute_composite_score(0.0, 0.0, 0.0, utility=0.0)
        assert score == 0.0

    def test_contradiction_penalty_reduces_score(self):
        without = compute_composite_score(0.8, 0.8, 0.8, contradiction_penalty=0.0)
        with_penalty = compute_composite_score(0.8, 0.8, 0.8, contradiction_penalty=0.3)
        assert with_penalty < without

    def test_custom_weights(self):
        weights = {"semantic": 1.0, "recency": 0.0, "importance": 0.0, "utility": 0.0}
        score = compute_composite_score(0.5, 0.0, 0.0, weights=weights)
        assert abs(score - 0.5) < 0.01


class TestTypeBoost:
    def test_semantic_layer_gets_boost(self):
        from core.schemas.memory import MemoryLayer
        mem = make_memory("user works at Acme")
        mem.memory_layer = MemoryLayer.SEMANTIC
        boost = compute_type_boost(mem)
        assert boost > 0.0

    def test_episodic_layer_no_boost(self):
        from core.schemas.memory import MemoryLayer
        mem = make_memory("user said hello")
        mem.memory_layer = MemoryLayer.EPISODIC
        boost = compute_type_boost(mem)
        assert boost == 0.0

    def test_semantic_boost_improves_composite(self):
        from core.schemas.memory import MemoryLayer
        episodic_mem = make_memory("user likes Python")
        episodic_mem.memory_layer = MemoryLayer.EPISODIC
        semantic_mem = make_memory("user likes Python")
        semantic_mem.memory_layer = MemoryLayer.SEMANTIC

        ep_candidate = score_memory_for_retrieval(episodic_mem, 0.8, "Python")
        sem_candidate = score_memory_for_retrieval(semantic_mem, 0.8, "Python")
        assert sem_candidate.composite_score >= ep_candidate.composite_score


class TestRankCandidates:
    def test_ranks_are_assigned(self, sample_memory):
        from core.schemas.memory import RetrievalCandidate
        candidates = [
            RetrievalCandidate(memory=sample_memory, semantic_score=0.5,
                               recency_score=0.5, importance_score=0.5, composite_score=0.6),
            RetrievalCandidate(memory=sample_memory, semantic_score=0.8,
                               recency_score=0.8, importance_score=0.8, composite_score=0.9),
        ]
        ranked = rank_candidates(candidates)
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2
        assert ranked[0].composite_score > ranked[1].composite_score
