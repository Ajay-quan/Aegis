"""Standard information-retrieval metrics for memory evaluation.

The original benchmark reported only Precision@1 on a synthetic set. Credible
retrieval evaluation uses ranked-list metrics that account for *where* the
relevant items land. These are the standard ones (TREC/BEIR conventions),
implemented dependency-free so they run anywhere:

* hit@k        — did any relevant item appear in the top-k?
* precision@k  — fraction of the top-k that are relevant.
* recall@k     — fraction of all relevant items found in the top-k.
* MRR          — mean reciprocal rank of the first relevant item.
* nDCG@k       — rank-weighted gain, normalized to the ideal ordering.

Each function takes a ranked list of retrieved ids and the set of relevant ids.
``aggregate`` averages a metric over many queries.
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence


def hit_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    rel = set(relevant)
    return 1.0 if any(r in rel for r in ranked[:k]) else 0.0


def precision_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    if k <= 0:
        return 0.0
    rel = set(relevant)
    topk = ranked[:k]
    return sum(1 for r in topk if r in rel) / k


def recall_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    rel = set(relevant)
    if not rel:
        return 0.0
    topk = set(ranked[:k])
    return len(topk & rel) / len(rel)


def reciprocal_rank(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    rel = set(relevant)
    for i, r in enumerate(ranked, start=1):
        if r in rel:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    rel = set(relevant)
    # Binary relevance DCG.
    dcg = sum(
        (1.0 / math.log2(i + 1))
        for i, r in enumerate(ranked[:k], start=1)
        if r in rel
    )
    # Ideal DCG: all relevant items ranked first.
    ideal_hits = min(len(rel), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def aggregate(
    metric: Callable[..., float],
    cases: Sequence[tuple[Sequence[str], Iterable[str]]],
    **kwargs,
) -> float:
    """Average a metric over a set of (ranked, relevant) query cases."""
    if not cases:
        return 0.0
    return sum(metric(ranked, relevant, **kwargs) for ranked, relevant in cases) / len(cases)


def report(
    cases: Sequence[tuple[Sequence[str], Iterable[str]]],
    ks: Sequence[int] = (1, 3, 5, 10),
) -> dict:
    """Compute a full metric report averaged over all query cases."""
    out: dict[str, float] = {"queries": len(cases), "mrr": round(aggregate(reciprocal_rank, cases), 4)}
    for k in ks:
        out[f"hit@{k}"] = round(aggregate(hit_at_k, cases, k=k), 4)
        out[f"precision@{k}"] = round(aggregate(precision_at_k, cases, k=k), 4)
        out[f"recall@{k}"] = round(aggregate(recall_at_k, cases, k=k), 4)
        out[f"ndcg@{k}"] = round(aggregate(ndcg_at_k, cases, k=k), 4)
    return out
