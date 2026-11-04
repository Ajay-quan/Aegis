"""Unit tests for continual-learning metrics (BWT/FWT/forgetting)."""
from __future__ import annotations

import pytest

from domain.learning.cl_metrics import (
    average_accuracy, backward_transfer, forgetting, forward_transfer,
    summarize_matrix,
)


# R[i][j] = perf on task j after training through task i.
R = [
    [1.0, 0.0],
    [0.5, 1.0],
]


def test_average_accuracy():
    # mean of final row = (0.5 + 1.0) / 2
    assert average_accuracy(R) == 0.75


def test_backward_transfer_detects_forgetting():
    # R[1][0] - R[0][0] = 0.5 - 1.0 = -0.5
    assert backward_transfer(R) == -0.5


def test_forgetting():
    # task 0 peak = max(1.0, 0.5)=1.0, final=0.5 => 0.5
    assert forgetting(R) == 0.5


def test_forward_transfer_default_baseline():
    # R[0][1] - 0 = 0.0
    assert forward_transfer(R) == 0.0


def test_positive_backward_transfer():
    good = [[1.0, 0.0], [1.0, 1.0]]
    assert backward_transfer(good) == 0.0
    better = [[0.8, 0.0], [0.9, 1.0]]
    assert backward_transfer(better) == pytest.approx(0.1)


def test_non_square_matrix_raises():
    with pytest.raises(ValueError):
        average_accuracy([[1.0, 0.0]])


def test_summarize_bundles_all():
    s = summarize_matrix(R)
    assert s["tasks"] == 2
    assert s["average_accuracy"] == 0.75
    assert s["backward_transfer"] == -0.5
    assert s["forgetting"] == 0.5
