"""Second-stage reranking and diversity filtering for retrieval candidates.

Architecture:
    BaseReranker          — abstract interface for pluggable rerankers
    HeuristicReranker     — config-driven composite reranking + diversity (default)
    CrossEncoderReranker  — lazy-loaded ms-marco cross-encoder with heuristic
                            fallback (enabled via RERANKER_TYPE=cross_encoder)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from core.schemas.memory import RetrievalCandidate

logger = logging.getLogger(__name__)


class BaseReranker(ABC):
    """Abstract reranker interface."""

    @abstractmethod
    def rerank(
        self,
        candidates: list[RetrievalCandidate],
        query_text: str,
        top_k: int,
    ) -> list[RetrievalCandidate]:
        """Rerank candidates and return the top-k."""
        ...


class HeuristicReranker(BaseReranker):
    """Config-driven heuristic reranker with diversity filtering.

    1. Sort by composite_score (already computed by scoring module).
    2. Apply diversity filtering to suppress near-duplicate content.
    3. Assign final ranks and truncate to top_k.
    """

    def __init__(self, diversity_threshold: float = 0.92) -> None:
        self._diversity_threshold = diversity_threshold

    def rerank(
        self,
        candidates: list[RetrievalCandidate],
        query_text: str,
        top_k: int,
    ) -> list[RetrievalCandidate]:
        # Sort by composite score (descending).
        sorted_candidates = sorted(
            candidates, key=lambda c: c.composite_score, reverse=True,
        )

        # Diversity filter: greedy selection, skip near-duplicates.
        selected = self._diversity_filter(sorted_candidates)

        # Assign ranks and truncate.
        for i, c in enumerate(selected):
            c.rank = i + 1
        return selected[:top_k]

    def _diversity_filter(
        self, candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        """Greedy diversity selection — skip candidates too similar to already-selected ones."""
        if not candidates:
            return []

        selected: list[RetrievalCandidate] = []
        selected_texts: list[str] = []

        for c in candidates:
            if self._is_too_similar(c.memory.content, selected_texts):
                logger.debug(
                    f"Diversity filter: suppressed memory {c.memory.memory_id} "
                    f"(score={c.composite_score:.3f})"
                )
                continue
            selected.append(c)
            selected_texts.append(c.memory.content)

        return selected

    def _is_too_similar(self, content: str, existing_texts: list[str]) -> bool:
        """Check if content is too similar to any already-selected text."""
        if not existing_texts:
            return False

        content_tokens = set(content.lower().split())
        if not content_tokens:
            return False

        for existing in existing_texts:
            existing_tokens = set(existing.lower().split())
            if not existing_tokens:
                continue
            # Jaccard similarity on raw word tokens.
            intersection = len(content_tokens & existing_tokens)
            union = len(content_tokens | existing_tokens)
            if union > 0 and (intersection / union) > self._diversity_threshold:
                return True
        return False


class CrossEncoderReranker(BaseReranker):
    """Cross-encoder reranker (e.g. ms-marco-MiniLM).

    A cross-encoder jointly encodes (query, document) and is materially more
    accurate than the bi-encoder cosine similarity used at first-stage
    retrieval — at the cost of running the model once per candidate. It is
    therefore applied only to the small post-fusion candidate set.

    The ``sentence-transformers`` model is loaded lazily on first use and
    cached. If the dependency or model is unavailable, the reranker degrades
    gracefully to :class:`HeuristicReranker` instead of failing the request.
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        diversity_threshold: float = 0.92,
    ) -> None:
        self._model_name = model_name
        self._model = None
        self._unavailable = False
        self._fallback = HeuristicReranker(diversity_threshold=diversity_threshold)

    def _load_model(self) -> None:
        if self._model is not None or self._unavailable:
            return
        try:
            from sentence_transformers import CrossEncoder  # type: ignore

            self._model = CrossEncoder(self._model_name)
            logger.info(f"Loaded cross-encoder reranker: {self._model_name}")
        except Exception as e:  # ImportError or model download failure
            self._unavailable = True
            logger.warning(
                f"Cross-encoder unavailable ({e}); falling back to heuristic reranker."
            )

    def rerank(
        self,
        candidates: list[RetrievalCandidate],
        query_text: str,
        top_k: int,
    ) -> list[RetrievalCandidate]:
        if not candidates:
            return []

        self._load_model()
        if self._model is None:
            return self._fallback.rerank(candidates, query_text, top_k)

        # Diversity-filter first so we only pay for cross-encoding distinct docs.
        deduped = self._fallback._diversity_filter(
            sorted(candidates, key=lambda c: c.composite_score, reverse=True)
        )
        pairs = [(query_text, c.memory.content) for c in deduped]
        try:
            scores = self._model.predict(pairs)
        except Exception as e:
            logger.warning(f"Cross-encoder scoring failed ({e}); using heuristic order.")
            return self._fallback.rerank(candidates, query_text, top_k)

        score_vals = [float(s) for s in scores]
        lo, hi = min(score_vals), max(score_vals)
        for c, s in zip(deduped, score_vals):
            # Normalize the cross-encoder logit into [0,1] for a comparable score.
            c.composite_score = (s - lo) / (hi - lo) if hi > lo else 1.0
        deduped.sort(key=lambda c: c.composite_score, reverse=True)
        for i, c in enumerate(deduped):
            c.rank = i + 1
        return deduped[:top_k]


def build_reranker(settings) -> BaseReranker:
    """Construct the reranker selected by configuration.

    ``reranker_type='cross_encoder'`` returns a lazily-loaded cross-encoder
    (with heuristic fallback); anything else returns the heuristic reranker.
    """
    if getattr(settings, "reranker_type", "heuristic") == "cross_encoder":
        return CrossEncoderReranker(
            model_name=getattr(
                settings, "cross_encoder_model",
                "cross-encoder/ms-marco-MiniLM-L-6-v2",
            ),
            diversity_threshold=settings.diversity_threshold,
        )
    return HeuristicReranker(diversity_threshold=settings.diversity_threshold)
