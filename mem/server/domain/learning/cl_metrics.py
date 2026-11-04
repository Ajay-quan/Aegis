"""Continual-learning metrics: Backward / Forward Transfer and forgetting.

A self-modifying retrieval system is only trustworthy if we can *measure* that
learning new things does not destroy old performance. These are the standard
metrics from the continual-learning literature (Lopez-Paz & Ranzato, GEM, 2017),
computed over a performance matrix ``R`` where:

    R[i][j] = performance on task j after training through task i.

* **Average accuracy** — mean of the final row (performance on all tasks after
  all training).
* **Backward Transfer (BWT)** — how much learning later tasks changed earlier
  ones. BWT < 0 means catastrophic forgetting; BWT > 0 means positive backward
  transfer.
* **Forward Transfer (FWT)** — how much earlier learning helped a task before it
  was trained, relative to a random/static baseline.
* **Forgetting** — average drop from each task's peak to its final score.

Used by ``scripts/continual_eval.py`` as the promotion gate: a learned policy
that regresses BWT past a threshold must not be promoted.
"""
from __future__ import annotations

Matrix = list[list[float]]


def _validate(R: Matrix) -> int:
    if not R:
        raise ValueError("performance matrix is empty")
    t = len(R)
    for row in R:
        if len(row) != t:
            raise ValueError("performance matrix must be square (T x T)")
    return t


def average_accuracy(R: Matrix) -> float:
    """Mean performance across all tasks after training on the final task."""
    t = _validate(R)
    final = R[-1]
    return sum(final) / t


def backward_transfer(R: Matrix) -> float:
    """BWT = mean_i<T ( R[T-1][i] - R[i][i] ). Negative => forgetting."""
    t = _validate(R)
    if t < 2:
        return 0.0
    return sum(R[t - 1][i] - R[i][i] for i in range(t - 1)) / (t - 1)


def forward_transfer(R: Matrix, baseline: list[float] | None = None) -> float:
    """FWT = mean_i>0 ( R[i-1][i] - baseline[i] ).

    Measures performance on a task *before* it was trained (zero-shot transfer
    from earlier tasks), relative to a per-task baseline (default 0.0).
    """
    t = _validate(R)
    if t < 2:
        return 0.0
    base = baseline or [0.0] * t
    return sum(R[i - 1][i] - base[i] for i in range(1, t)) / (t - 1)


def forgetting(R: Matrix) -> float:
    """Average forgetting: mean over tasks of (peak score - final score)."""
    t = _validate(R)
    if t < 2:
        return 0.0
    total = 0.0
    for i in range(t - 1):
        peak = max(R[k][i] for k in range(i, t))
        total += peak - R[t - 1][i]
    return total / (t - 1)


def summarize_matrix(R: Matrix, baseline: list[float] | None = None) -> dict:
    """Bundle all metrics for reporting."""
    return {
        "tasks": _validate(R),
        "average_accuracy": round(average_accuracy(R), 4),
        "backward_transfer": round(backward_transfer(R), 4),
        "forward_transfer": round(forward_transfer(R, baseline), 4),
        "forgetting": round(forgetting(R), 4),
    }
