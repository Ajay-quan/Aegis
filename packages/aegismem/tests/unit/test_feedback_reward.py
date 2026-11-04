"""Unit tests for feedback reward shaping."""
from __future__ import annotations

import pytest

from domain.learning.feedback import FeedbackSignal, shape_reward


def test_explicit_score_takes_precedence():
    assert shape_reward(score=0.9, useful=False) == pytest.approx(0.9)


def test_useful_maps_to_bounds():
    assert shape_reward(useful=True) == 1.0
    assert shape_reward(useful=False) == 0.0


def test_neutral_prior_without_signal():
    assert shape_reward() == 0.5


def test_outcome_nudges():
    assert shape_reward(score=0.5, outcome="success", success_bonus=0.2) == pytest.approx(0.7)
    assert shape_reward(score=0.5, outcome="failure", success_bonus=0.2) == pytest.approx(0.3)


def test_contradiction_penalty():
    assert shape_reward(score=0.8, contradicted=True, contradiction_penalty=0.3) == pytest.approx(0.5)


def test_reward_is_clamped():
    assert shape_reward(score=0.0, outcome="failure") == 0.0
    assert shape_reward(score=1.0, outcome="success") == 1.0


def test_signal_schema_validates_score_range():
    FeedbackSignal(query_id="q", memory_id="m", score=0.5)
    with pytest.raises(Exception):
        FeedbackSignal(query_id="q", memory_id="m", score=1.5)
