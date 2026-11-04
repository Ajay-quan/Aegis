"""Process-wide singletons for the continual-learning subsystem.

The retrieval service and the feedback service must share one ranking policy and
one replay buffer without threading them through every constructor (which would
churn existing call sites and tests). This module owns those singletons, built
lazily from ``settings`` on first use, and exposes a reset hook for tests and
the eval harness.
"""
from __future__ import annotations

from threading import Lock

from core.config.settings import settings
from domain.learning.online_scorer import OnlineRankingPolicy
from domain.learning.replay import ReplayBuffer

_policy: OnlineRankingPolicy | None = None
_buffer: ReplayBuffer | None = None
_lock = Lock()


def _base_weights() -> dict[str, float]:
    return {
        "semantic": settings.weight_semantic,
        "lexical": settings.weight_lexical,
        "recency": settings.weight_recency,
        "importance": settings.weight_importance,
        "access": settings.weight_access,
    }


def get_ranking_policy() -> OnlineRankingPolicy:
    global _policy
    if _policy is None:
        with _lock:
            if _policy is None:
                _policy = OnlineRankingPolicy(
                    base_weights=_base_weights(),
                    learning_rate=settings.cl_learning_rate,
                    ewc_lambda=settings.cl_ewc_lambda,
                )
    return _policy


def get_replay_buffer() -> ReplayBuffer:
    global _buffer
    if _buffer is None:
        with _lock:
            if _buffer is None:
                _buffer = ReplayBuffer(capacity=settings.cl_replay_capacity)
                if settings.cl_replay_persist:
                    try:
                        _buffer.load(f"{settings.data_dir}/replay_buffer.json")
                    except Exception:
                        pass
    return _buffer


def reset_learning_state() -> None:
    """Drop the singletons (used by tests / eval to start from a clean slate)."""
    global _policy, _buffer
    with _lock:
        _policy = None
        _buffer = None
