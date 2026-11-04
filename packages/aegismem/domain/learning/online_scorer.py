"""Online, per-namespace learned ranking policy (AegisMem-CL loop L1).

The static scorer in ``domain.memory.scoring`` combines signals with *fixed*
weights from settings. This policy makes those weights *learned* and *adapted
online* from retrieval feedback, with two properties that matter for a
continual-learning system:

1. **Per-namespace isolation (modular CL).** Each namespace (tenant / user /
   project) owns its own weight vector, so adapting one never overwrites
   another — interference is impossible by construction.

2. **EWC-style anchoring (anti-forgetting).** Each online update is pulled back
   toward a protected anchor with strength proportional to an accumulated
   Fisher-information diagonal. ``consolidate()`` snapshots the current weights
   as the new anchor at a task boundary. This is the online/L2-SP variant of
   Elastic Weight Consolidation and resists catastrophic forgetting of
   previously-good weightings.

The model is a convex (non-negative, sum-to-one) linear scorer over the five
features in :data:`domain.learning.features.FEATURE_NAMES`. The convexity keeps
the composite score in [0, 1] for features in [0, 1] — the same invariant the
static scorer guarantees — so the learned policy is a safe drop-in.

Pure Python / stdlib only: no numpy, no GPU, no infra.
"""
from __future__ import annotations

from threading import RLock

from domain.learning.features import FEATURE_NAMES


class OnlineRankingPolicy:
    """A learnable, EWC-anchored, per-namespace ranking weight vector."""

    def __init__(
        self,
        base_weights: dict[str, float],
        learning_rate: float = 0.05,
        ewc_lambda: float = 0.1,
    ) -> None:
        # The prior / cold-start weights (normalized convex form of settings).
        self._base = self._normalize(base_weights)
        self.learning_rate = float(learning_rate)
        self.ewc_lambda = float(ewc_lambda)

        self._w: dict[str, dict[str, float]] = {}        # namespace -> weights
        self._anchor: dict[str, dict[str, float]] = {}   # protected weights
        self._fisher: dict[str, dict[str, float]] = {}   # Fisher diagonal
        self._counts: dict[str, int] = {}                # updates per namespace
        self._lock = RLock()

    # ------------------------------------------------------------------ state
    def _ensure(self, namespace: str) -> None:
        ns = namespace or "_global"
        if ns not in self._w:
            self._w[ns] = dict(self._base)
            self._anchor[ns] = dict(self._base)
            self._fisher[ns] = {f: 0.0 for f in FEATURE_NAMES}
            self._counts[ns] = 0

    def weights(self, namespace: str = "") -> dict[str, float]:
        """Current learned weight vector for a namespace (cold-starts at base)."""
        ns = namespace or "_global"
        with self._lock:
            self._ensure(ns)
            return dict(self._w[ns])

    def predict(self, namespace: str, features: dict[str, float]) -> float:
        """Linear score w·x for the given features under this namespace."""
        w = self.weights(namespace)
        return sum(w[f] * float(features.get(f, 0.0)) for f in FEATURE_NAMES)

    # --------------------------------------------------------------- learning
    def update(
        self,
        namespace: str,
        features: dict[str, float],
        reward: float,
    ) -> dict[str, float]:
        """Single online SGD step toward ``reward`` with an EWC anchor pull.

        Loss is pointwise squared error ``0.5 * (reward - w·x)^2``. The gradient
        ascent step moves weights toward features that earned reward, the Fisher
        diagonal accumulates squared gradients, and an EWC penalty resists
        drifting away from the protected anchor. Weights are re-projected to the
        convex simplex after each step.
        """
        ns = namespace or "_global"
        reward = max(0.0, min(1.0, float(reward)))
        with self._lock:
            self._ensure(ns)
            w = self._w[ns]
            anchor = self._anchor[ns]
            fisher = self._fisher[ns]

            pred = sum(w[f] * float(features.get(f, 0.0)) for f in FEATURE_NAMES)
            err = reward - pred  # >0 -> push weights up on active features

            new: dict[str, float] = {}
            for f in FEATURE_NAMES:
                x = float(features.get(f, 0.0))
                grad = err * x  # gradient of the reward objective wrt w[f]
                anchor_pull = self.ewc_lambda * fisher[f] * (w[f] - anchor[f])
                new[f] = w[f] + self.learning_rate * grad - self.learning_rate * anchor_pull
                fisher[f] += grad * grad  # online Fisher accumulation

            self._w[ns] = self._normalize(new)
            self._counts[ns] += 1
            return dict(self._w[ns])

    def consolidate(self, namespace: str = "") -> None:
        """Mark a task boundary: protect the current weights as the new anchor.

        Online-EWC semantics — after consolidation, the accumulated Fisher makes
        subsequent updates resist moving away from *these* weights, preserving
        what was learned for prior tasks/namespaces.
        """
        ns = namespace or "_global"
        with self._lock:
            self._ensure(ns)
            self._anchor[ns] = dict(self._w[ns])

    def update_count(self, namespace: str = "") -> int:
        ns = namespace or "_global"
        with self._lock:
            self._ensure(ns)
            return self._counts[ns]

    def namespaces(self) -> list[str]:
        with self._lock:
            return sorted(self._w.keys())

    def stats(self) -> dict[str, dict]:
        """Inspectable snapshot for a /learning/stats endpoint or eval."""
        with self._lock:
            return {
                ns: {
                    "updates": self._counts[ns],
                    "weights": dict(self._w[ns]),
                    "drift_from_base": round(
                        sum(abs(self._w[ns][f] - self._base[f]) for f in FEATURE_NAMES),
                        4,
                    ),
                }
                for ns in self._w
            }

    # ------------------------------------------------------------- utilities
    @staticmethod
    def _normalize(weights: dict[str, float]) -> dict[str, float]:
        """Project onto the convex simplex (non-negative, sums to 1)."""
        clipped = {f: max(0.0, float(weights.get(f, 0.0))) for f in FEATURE_NAMES}
        total = sum(clipped.values())
        if total <= 0.0:
            uniform = 1.0 / len(FEATURE_NAMES)
            return {f: uniform for f in FEATURE_NAMES}
        return {f: clipped[f] / total for f in FEATURE_NAMES}
