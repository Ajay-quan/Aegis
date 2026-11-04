"""Sparse lexical retrieval (BM25) and rank fusion.

This module implements the *lexical* half of AegisMem's hybrid retrieval
pipeline. Dense vector search is strong on paraphrase and semantic similarity
but weak on rare tokens, identifiers, names, and exact keywords — exactly the
signals that matter for agent memory ("the API key is ...", "user_id 4471").
BM25 complements dense search on those queries, and Reciprocal Rank Fusion
(RRF) merges the two ranked lists without needing the scores to be calibrated
against each other.

The implementation is intentionally dependency-free (pure Python + stdlib) so
it runs in the zero-infra demo as well as the full stack.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokenizer shared by indexing and querying."""
    return _TOKEN_RE.findall(text.lower())


@dataclass
class BM25Index:
    """Okapi BM25 over an in-memory corpus of (doc_id, text) pairs.

    BM25 is the standard strong baseline for sparse retrieval. Scores are
    unbounded and corpus-dependent, so callers should fuse by *rank* (see
    :func:`reciprocal_rank_fusion`) rather than comparing raw scores against
    dense similarities.
    """

    k1: float = 1.5
    b: float = 0.75
    doc_ids: list[str] = field(default_factory=list)
    doc_tokens: list[list[str]] = field(default_factory=list)
    doc_freqs: list[Counter] = field(default_factory=list)
    doc_len: list[int] = field(default_factory=list)
    df: Counter = field(default_factory=Counter)
    avgdl: float = 0.0

    @classmethod
    def build(
        cls,
        documents: list[tuple[str, str]],
        k1: float = 1.5,
        b: float = 0.75,
    ) -> "BM25Index":
        idx = cls(k1=k1, b=b)
        for doc_id, text in documents:
            tokens = tokenize(text)
            freqs = Counter(tokens)
            idx.doc_ids.append(doc_id)
            idx.doc_tokens.append(tokens)
            idx.doc_freqs.append(freqs)
            idx.doc_len.append(len(tokens))
            for term in freqs:
                idx.df[term] += 1
        n = len(idx.doc_len)
        idx.avgdl = (sum(idx.doc_len) / n) if n else 0.0
        return idx

    def _idf(self, term: str) -> float:
        n = len(self.doc_ids)
        df = self.df.get(term, 0)
        # BM25+ style idf with a floor that stays non-negative.
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def score(self, query: str, doc_index: int) -> float:
        if self.avgdl == 0.0:
            return 0.0
        freqs = self.doc_freqs[doc_index]
        dl = self.doc_len[doc_index]
        score = 0.0
        for term in tokenize(query):
            tf = freqs.get(term, 0)
            if tf == 0:
                continue
            idf = self._idf(term)
            denom = tf + self.k1 * (1.0 - self.b + self.b * dl / self.avgdl)
            score += idf * (tf * (self.k1 + 1.0)) / denom
        return score

    def search(self, query: str, top_k: int | None = None) -> list[tuple[str, float]]:
        """Return ``(doc_id, bm25_score)`` ranked high→low (zero scores dropped)."""
        scored = [
            (self.doc_ids[i], self.score(query, i)) for i in range(len(self.doc_ids))
        ]
        scored = [(doc_id, s) for doc_id, s in scored if s > 0.0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k] if top_k else scored


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    k: int = 60,
    weights: list[float] | None = None,
) -> list[tuple[str, float]]:
    """Fuse multiple ranked id lists with Reciprocal Rank Fusion.

    RRF score for a doc = Σ_l w_l / (k + rank_l), where ``rank`` is 1-based and
    ``k`` damps the contribution of low-ranked items (Cormack et al., 2009).
    It is robust precisely because it ignores raw score magnitudes, which is
    what makes it ideal for fusing BM25 with cosine similarity.
    """
    if weights is None:
        weights = [1.0] * len(ranked_lists)
    fused: dict[str, float] = {}
    for lst, w in zip(ranked_lists, weights):
        for rank, doc_id in enumerate(lst, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + w / (k + rank)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def normalize_scores(pairs: list[tuple[str, float]]) -> dict[str, float]:
    """Min-max normalize a list of ``(id, score)`` into ``{id: [0,1]}``."""
    if not pairs:
        return {}
    values = [s for _, s in pairs]
    lo, hi = min(values), max(values)
    if hi <= lo:
        return {doc_id: 1.0 for doc_id, _ in pairs}
    return {doc_id: (s - lo) / (hi - lo) for doc_id, s in pairs}
