"""Feature extraction for the learned ranking policy.

The online policy learns a weight over the *same* signals the static composite
scorer uses, so a learned weight vector is a drop-in replacement for the fixed
``settings.weight_*`` values. Keeping feature extraction in one place guarantees
training-time and serving-time features are identical.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from core.schemas.memory import RetrievalCandidate

# Order matters only for human readability; the policy is keyed by name.
FEATURE_NAMES: tuple[str, ...] = (
    "semantic",
    "lexical",
    "recency",
    "importance",
    "access",
)

# Access-count normalization constant — mirrors domain.memory.scoring so the
# learned 'access' feature is on the same scale as the static scorer.
_ACCESS_NORM = math.log1p(100)


def access_norm(access_count: int) -> float:
    """Log-normalized access frequency in roughly [0, 1]."""
    if access_count <= 0:
        return 0.0
    return min(1.0, math.log1p(access_count) / _ACCESS_NORM)


def extract_features(candidate: "RetrievalCandidate") -> dict[str, float]:
    """Project a scored candidate onto the policy's feature space.

    All features are clamped to [0, 1] so the learned (convex) weight vector
    keeps the composite score bounded.
    """
    def _clamp(x: float) -> float:
        return max(0.0, min(1.0, float(x)))

    return {
        "semantic": _clamp(candidate.semantic_score),
        "lexical": _clamp(candidate.lexical_score),
        "recency": _clamp(candidate.recency_score),
        "importance": _clamp(candidate.importance_score),
        "access": access_norm(candidate.memory.access_count),
    }
