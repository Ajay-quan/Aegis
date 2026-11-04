"""Feedback signal schema and reward shaping.

Reward is the single scalar that drives every learning loop. It fuses:

* **explicit** feedback — an agent says a memory was useful (bool) or grades it
  (score in [0, 1]);
* **implicit / outcome** feedback — whether the downstream agent turn succeeded;
* **integrity penalties** — a confirmed-contradicted (stale) memory is penalized
  even if it was retrieved, so the policy learns to down-rank stale facts.

Keeping reward shaping in one pure function makes it testable and keeps the
policy honest (no reward logic hidden in the service layer).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FeedbackSignal(BaseModel):
    """A piece of feedback about a single retrieved memory for a query."""

    query_id: str
    memory_id: str
    useful: bool | None = Field(
        default=None, description="Coarse explicit signal: was this memory useful?"
    )
    score: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Fine explicit grade in [0, 1]; overrides 'useful' if set.",
    )
    outcome: str = Field(
        default="", description="Downstream result: 'success' | 'failure' | ''."
    )


def shape_reward(
    *,
    useful: bool | None = None,
    score: float | None = None,
    outcome: str = "",
    contradicted: bool = False,
    success_bonus: float = 0.2,
    contradiction_penalty: float = 0.3,
) -> float:
    """Fuse explicit, implicit, and integrity signals into a reward in [0, 1].

    Precedence: an explicit ``score`` wins; else ``useful`` maps to 1.0/0.0;
    else a neutral 0.5 prior. Outcome nudges the base up/down, and a confirmed
    contradiction applies a penalty.
    """
    if score is not None:
        base = float(score)
    elif useful is not None:
        base = 1.0 if useful else 0.0
    else:
        base = 0.5  # neutral prior when no explicit signal is given

    outcome_norm = (outcome or "").strip().lower()
    if outcome_norm in ("success", "succeeded", "good", "1", "true"):
        base += success_bonus
    elif outcome_norm in ("failure", "failed", "bad", "0", "false"):
        base -= success_bonus

    if contradicted:
        base -= contradiction_penalty

    return max(0.0, min(1.0, base))
