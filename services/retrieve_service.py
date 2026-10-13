"""Memory retrieval service — hybrid semantic + lexical + reranking pipeline.

Pipeline stages:
    1. Semantic search → broad candidate pool (top_n_candidates)
    2. Enrich from relational store + compute multi-signal scores
    3. Apply symbolic filters (time, type, importance)
    4. Second-stage reranking with diversity filtering
    5. Return top_k results
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from core.config.settings import settings
from core.schemas.memory import (
    MemoryItem, RetrievalQuery, RetrievalResult, RetrievalCandidate,
)
from domain.memory.scoring import score_memory_for_retrieval, rank_candidates
from core.observability.metrics import GUARD_DECISIONS, observe_retrieval_results
from core.observability.tracing import tracer
from domain.memory.lexical import BM25Index, normalize_scores, reciprocal_rank_fusion
from domain.memory.reranker import HeuristicReranker

logger = logging.getLogger(__name__)


class RetrievalService:
    """Hybrid memory retrieval combining semantic search + lexical signals + reranking."""

    def __init__(
        self,
        relational_store: Any,
        vector_store: Any,
        embedding_backend: Any,
        graph_store: Any | None = None,
        learner: Any | None = None,
        ledger: Any | None = None,
        guard: Any | None = None,
    ) -> None:
        self._db = relational_store
        self._vs = vector_store
        self._embed = embedding_backend
        self._graph = graph_store
        self._learner = learner
        self._ledger = ledger
        # Integrity guard is always on; pass a configured one to change the trust floor.
        if guard is None:
            from services.guard_service import MemoryGuard
            guard = MemoryGuard(relational_store)
        self._guard = guard
        self._tenant = getattr(relational_store, "tenant_id", "unscoped")
        self._reranker = HeuristicReranker(
            diversity_threshold=settings.diversity_threshold,
        )

    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Main retrieval entry point (span: aegis.retrieve)."""
        with tracer.start_as_current_span("aegis.retrieve") as span:
            result = await self._retrieve(query)
            observe_retrieval_results(len(result.candidates), result.total_found)
            span.set_attributes({"aegis.retrieval_id": result.retrieval_id,
                                 "aegis.returned": len(result.candidates),
                                 "aegis.guard_interventions": len(result.guard_report),
                                 "aegis.learned_weights": self._learner is not None})
            return result

    async def _retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        start = time.time()

        # Stage 1: dense retrieval, plus BM25 over the user's corpus when hybrid is on; the
        # two rankings are fused with Reciprocal Rank Fusion. Every fused candidate then goes
        # through the integrity guard below, so the lexical path cannot leak revoked data.
        dense = await self._semantic_search(query)
        lexical = await self._lexical_search(query) if settings.hybrid_retrieval_enabled else []
        semantic_candidates = self._fuse(dense, lexical)
        lexical_scores = normalize_scores(lexical)

        # Stage 2: Enrich with full records + multi-signal scoring,
        # using per-user learned weights once enough feedback exists.
        weights = None
        if self._learner is not None:
            weights = await self._learner.weights_for(query.user_id)
        guard_report: list[dict[str, Any]] = []
        enriched = await self._enrich_candidates(
            semantic_candidates, query, weights=weights, guard_report=guard_report,
        )

        for c in enriched:
            c.lexical_score = lexical_scores.get(c.memory.memory_id, 0.0)

        # Stage 3: Symbolic filters (time range, type, importance).
        filtered = self._apply_filters(enriched, query)

        # Stage 4: Second-stage reranking with diversity filtering.
        reranked = self._reranker.rerank(
            candidates=filtered,
            query_text=query.query_text,
            top_k=query.top_k,
        )

        # Stage 5: Update access counts on returned results.
        for candidate in reranked:
            candidate.memory.bump_access()
            try:
                await self._db.update_memory(candidate.memory)
            except Exception:
                pass

        latency_ms = (time.time() - start) * 1000

        logger.info(
            f"Retrieved {len(reranked)}/{len(filtered)} memories for user={query.user_id} "
            f"in {latency_ms:.1f}ms (candidates={len(enriched)})"
        )

        result = RetrievalResult(
            query=query,
            candidates=reranked,
            total_found=len(filtered),
            guard_report=guard_report,
            latency_ms=latency_ms,
        )
        if self._ledger is not None:
            await self._ledger.record(result)
        return result

    async def _lexical_search(self, query: RetrievalQuery) -> list[tuple[str, float]]:
        """BM25 over the user's active memories (pure Python; rare tokens, names, ids)."""
        try:
            memories = await self._db.list_memories(
                user_id=query.user_id, namespace=query.namespace,
                limit=settings.lexical_candidate_pool,
            )
            if not memories:
                return []
            index = BM25Index.build([(m.memory_id, m.content) for m in memories],
                                    k1=settings.bm25_k1, b=settings.bm25_b)
            return index.search(query.query_text,
                                top_k=max(settings.retrieval_top_n_candidates, query.top_k * 4))
        except Exception as e:
            logger.warning(f"Lexical search failed: {e}")
            return []

    @staticmethod
    def _fuse(dense: list[tuple[str, float]], lexical: list[tuple[str, float]]) -> list[tuple[str, float]]:
        """RRF-ordered candidates with a blended relevance score for ranking."""
        if not lexical:
            return dense
        dense_map = dict(dense)
        lex_map = normalize_scores(lexical)
        order = reciprocal_rank_fusion([[i for i, _ in dense], [i for i, _ in lexical]],
                                       k=settings.rrf_k)
        w = settings.hybrid_lexical_weight
        return [(mid, (1 - w) * max(0.0, dense_map.get(mid, 0.0)) + w * lex_map.get(mid, 0.0))
                for mid, _ in order]

    async def _semantic_search(
        self, query: RetrievalQuery,
    ) -> list[tuple[str, float]]:
        """Run semantic search — return (memory_id, score) pairs."""
        try:
            query_embedding = await self._embed.embed_single(query.query_text)

            # Build vector filter.
            vector_filter: dict[str, Any] = {"user_id": query.user_id}
            if not query.include_archived:
                vector_filter["status"] = "active"

            # Fetch a broad candidate pool — refined by reranker later.
            n_candidates = max(
                settings.retrieval_top_n_candidates,
                query.top_k * 4,
            )

            results = await self._vs.search(
                query_vector=query_embedding,
                top_k=min(n_candidates, 50),
                filter=vector_filter,
            )
            return [(r.id, r.score) for r in results]
        except Exception as e:
            logger.warning(f"Semantic search failed, falling back to DB: {e}")
            return []

    async def _enrich_candidates(
        self,
        semantic_hits: list[tuple[str, float]],
        query: RetrievalQuery,
        weights: dict[str, float] | None = None,
        guard_report: list[dict[str, Any]] | None = None,
    ) -> list[RetrievalCandidate]:
        """Resolve hits through the integrity guard, then compute multi-signal scores."""
        report = guard_report if guard_report is not None else []
        cache: dict[str, Any] = {}
        # A memory can be reached several times: directly, and as the guard's substitute for a
        # superseded memory it replaced. Keep its *best* relevance. (Keeping the first occurrence
        # let a successor inherit its own weak score instead of its predecessor's exact match.)
        best: dict[str, tuple[Any, float]] = {}
        for memory_id, semantic_score in semantic_hits:
            try:
                memory, decision = await self._guard.resolve(memory_id, query.user_id, cache)
                if decision.action != "serve":
                    report.append(decision.to_dict())
                    GUARD_DECISIONS.labels(self._tenant, decision.action, decision.reason).inc()
                if memory is None:
                    continue
                prev = best.get(memory.memory_id)
                if prev is None or semantic_score > prev[1]:
                    best[memory.memory_id] = (memory, semantic_score)
            except Exception as e:
                logger.debug(f"Could not enrich memory {memory_id}: {e}")
        candidates: list[RetrievalCandidate] = [
            score_memory_for_retrieval(memory, score, query_text=query.query_text, weights=weights)
            for memory, score in best.values()
        ]

        # Fallback: if semantic search returned nothing, query DB directly.
        if not candidates and not report:
            memories = await self._db.list_memories(
                user_id=query.user_id,
                namespace=query.namespace,
                limit=query.top_k * 2,
            )
            for memory in memories:
                ok, _ = await self._guard.servable(memory)
                if not ok:
                    continue
                candidates.append(score_memory_for_retrieval(
                    memory, 0.5, query_text=query.query_text, weights=weights,
                ))

        return candidates

    def _apply_filters(
        self,
        candidates: list[RetrievalCandidate],
        query: RetrievalQuery,
    ) -> list[RetrievalCandidate]:
        """Apply symbolic filters to the candidate set."""
        filtered = []
        for c in candidates:
            m = c.memory

            # Importance threshold.
            if m.importance_score < query.min_importance:
                continue

            # Memory type filter.
            if query.memory_types and m.memory_type not in [
                mt.value if hasattr(mt, "value") else mt for mt in query.memory_types
            ]:
                continue

            # Memory layer filter.
            if query.memory_layers:
                layer_vals = [
                    ml.value if hasattr(ml, "value") else ml
                    for ml in query.memory_layers
                ]
                mem_layer = m.memory_layer if isinstance(m.memory_layer, str) else (
                    m.memory_layer.value if hasattr(m.memory_layer, 'value') else str(m.memory_layer)
                )
                if mem_layer not in layer_vals:
                    continue

            # Time range filter.
            if query.time_range_start and m.event_time:
                event_time = m.event_time
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=timezone.utc)
                start = query.time_range_start
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                if event_time < start:
                    continue

            if query.time_range_end and m.event_time:
                event_time = m.event_time
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=timezone.utc)
                end = query.time_range_end
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                if event_time > end:
                    continue

            # Namespace filter.
            if query.namespace and m.namespace and not m.namespace.startswith(query.namespace):
                continue

            filtered.append(c)

        return filtered

    async def get_context_window(
        self,
        user_id: str,
        query_text: str,
        top_k: int = 5,
        namespace: str = "",
    ) -> str:
        """Retrieve memories and format them as a context window string."""
        result = await self.retrieve(
            RetrievalQuery(
                query_text=query_text,
                user_id=user_id,
                namespace=namespace,
                top_k=top_k,
            )
        )

        if not result.candidates:
            return ""

        lines = ["# Relevant Memories\n"]
        for i, c in enumerate(result.candidates, 1):
            m = c.memory
            lines.append(
                f"{i}. [{m.memory_type}] {m.content} "
                f"(importance={m.importance_score:.2f}, score={c.composite_score:.2f})"
            )

        return "\n".join(lines)
