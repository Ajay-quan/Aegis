"""BEIR retrieval quality: is AegisMem's hybrid retrieval competitive on standard IR benchmarks?

Each corpus is ingested as one user's memories through the production pipeline; every test query is
answered by three systems over identical vectors: aegis (dense + BM25 RRF -> guard -> ranking),
dense (raw vector search), bm25. Metrics: nDCG@10 (BEIR's headline metric) and recall@100, with
95% bootstrap CIs over queries. Our BM25 is compared against BEIR's published BM25 numbers as a
correctness check (Thakur et al., 2021: SciFact 0.665, NFCorpus 0.325, FiQA 0.236 nDCG@10).

The lexical pool is set to the corpus size for this run (documented in the report): BEIR corpora are
document collections, larger than a typical user's memory.
"""
from __future__ import annotations

import math
import time
from typing import Any

from core.config.settings import settings
from core.schemas.memory import RetrievalQuery, SourceType
from domain.memory.lexical import BM25Index

from bench import sources
from bench.harness import build_env, use_embedding
from bench.stats import mean_ci, paired_diff_ci

PUBLISHED_BM25_NDCG10 = {"beir_scifact": 0.665, "beir_nfcorpus": 0.325, "beir_fiqa": 0.236}


def ndcg_at_k(ranked: list[str], rels: dict[str, int], k: int = 10) -> float:
    dcg = sum(rels.get(d, 0) / math.log2(i + 2) for i, d in enumerate(ranked[:k]))
    ideal = sorted(rels.values(), reverse=True)[:k]
    idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def recall_at_k(ranked: list[str], rels: dict[str, int], k: int = 100) -> float:
    return len(set(ranked[:k]) & set(rels)) / len(rels)


async def run(name: str, embed: Any, max_queries: int | None = None) -> dict[str, Any]:
    corpus, queries, qrels = sources.load_beir(name)
    qids = sorted(queries)[:max_queries]
    t0 = time.time()
    await embed.prefill(list(corpus.values()) + [queries[q] for q in qids], progress=True)
    env = await build_env(dim=embed.dimension)
    use_embedding(env, embed)
    pool = settings.lexical_candidate_pool
    settings.lexical_candidate_pool = len(corpus)
    try:
        mem_to_doc = {}
        for did, text in corpus.items():
            m = await env.ingest.ingest_text(text, user_id="beir", source_type=SourceType.INGESTION)
            mem_to_doc[m.memory_id] = did
        bm25 = BM25Index.build(list(corpus.items()))
        per: dict[str, dict[str, list[float]]] = {s: {"ndcg@10": [], "recall@100": []} for s in ("aegis", "dense", "bm25")}
        for qid in qids:
            q, rels = queries[qid], qrels[qid]
            r = await env.retrieve.retrieve(RetrievalQuery(query_text=q, user_id="beir", top_k=50))
            aegis = [mem_to_doc.get(c.memory.memory_id, "") for c in r.candidates]
            qv = await embed.embed_single(q)
            dense = [mem_to_doc.get(h.id, "") for h in await env.raw_vs.search(qv, top_k=100, filter={"user_id": "beir"})]
            lexical = [d for d, _ in bm25.search(q, top_k=100)]
            for s, ranked in (("aegis", aegis), ("dense", dense), ("bm25", lexical)):
                per[s]["ndcg@10"].append(ndcg_at_k(ranked, rels))
                per[s]["recall@100"].append(recall_at_k(ranked, rels))
    finally:
        settings.lexical_candidate_pool = pool
    quarantined = sum(1 for m in env.raw_db._memories.values() if m.status == "pending")
    return {
        "dataset": name, "docs": len(corpus), "queries": len(qids), "seconds": round(time.time() - t0, 1),
        "docs_quarantined": quarantined,
        "published_bm25_ndcg10": PUBLISHED_BM25_NDCG10.get(name),
        "overall": {s: {m: mean_ci(v) for m, v in d.items()} for s, d in per.items()},
        "aegis_vs_dense": {m: paired_diff_ci(per["aegis"][m], per["dense"][m]) for m in ("ndcg@10",)},
        "aegis_vs_bm25": {m: paired_diff_ci(per["aegis"][m], per["bm25"][m]) for m in ("ndcg@10",)},
        "note": "aegis top_k=50 (API max); recall@100 for aegis is therefore recall@50",
    }
