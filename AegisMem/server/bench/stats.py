"""Statistics for reported metrics: bootstrap confidence intervals and paired differences."""
from __future__ import annotations

import random
import statistics
from typing import Sequence


def mean_ci(values: Sequence[float], n_boot: int = 1000, alpha: float = 0.05, seed: int = 0) -> dict[str, float]:
    """Mean with a percentile-bootstrap (1 - alpha) confidence interval."""
    vals = list(values)
    if not vals:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": 0}
    rng = random.Random(seed)
    n = len(vals)
    boots = sorted(statistics.fmean(rng.choices(vals, k=n)) for _ in range(n_boot))
    return {"mean": statistics.fmean(vals), "lo": boots[int(n_boot * alpha / 2)],
            "hi": boots[int(n_boot * (1 - alpha / 2)) - 1], "n": n}


def paired_diff_ci(a: Sequence[float], b: Sequence[float], n_boot: int = 1000, seed: int = 0) -> dict[str, float]:
    """CI for mean(a - b) over paired items (same questions), plus the share of resamples where a > b."""
    diffs = [x - y for x, y in zip(a, b)]
    ci = mean_ci(diffs, n_boot=n_boot, seed=seed)
    rng = random.Random(seed + 1)
    wins = sum(statistics.fmean(rng.choices(diffs, k=len(diffs))) > 0 for _ in range(n_boot))
    ci["p_better"] = wins / n_boot
    return ci


def proportion_ci(successes: int, n: int, n_boot: int = 1000, seed: int = 0) -> dict[str, float]:
    return mean_ci([1.0] * successes + [0.0] * (n - successes), n_boot=n_boot, seed=seed)


def fmt(ci: dict[str, float], pct: bool = False) -> str:
    if ci["n"] == 0:
        return "n/a"
    k = 100 if pct else 1
    d = 1 if pct else 3
    return f"{ci['mean'] * k:.{d}f} [{ci['lo'] * k:.{d}f}, {ci['hi'] * k:.{d}f}]"
