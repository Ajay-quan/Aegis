#!/usr/bin/env python3
"""Information-retrieval benchmark for AegisMem memory recall.

Runs a dataset of users (each with memories + gold-labeled queries) through the
*real* ingest + retrieval stack and reports standard IR metrics
(recall@k, MRR, nDCG@k). It also runs a **dense-only vs hybrid** ablation so the
value of BM25 + RRF fusion is measured, not asserted.

Dataset schema (see docs/benchmarks/sample_dataset.json) — swap in real
LoCoMo / LongMemEval data by converting it to the same shape:

    {"users": [{"user_id", "memories": [{"id","text","memory_type"}],
                "queries": [{"query","relevant_ids":[...]}]}]}

Usage:
    python scripts/benchmark_memory.py --dataset docs/benchmarks/sample_dataset.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config.settings import settings  # noqa: E402
from core.schemas.memory import MemoryType, RetrievalQuery  # noqa: E402
from adapters.relational_store.memory_store import InMemoryRelationalStore  # noqa: E402
from adapters.vector_store.qdrant_store import InMemoryVectorStore  # noqa: E402
from adapters.graph_store.neo4j_store import MockGraphStore  # noqa: E402
from adapters.embeddings.backend import MockEmbeddingBackend  # noqa: E402
from services.ingest_service import IngestionService  # noqa: E402
from services.retrieve_service import RetrievalService  # noqa: E402
from domain.evaluations.ir_metrics import report as ir_report  # noqa: E402


async def _run_once(dataset: dict, top_k: int) -> dict:
    """Ingest the dataset into a fresh stack and evaluate all queries."""
    db = InMemoryRelationalStore()
    await db.initialize()
    vs = InMemoryVectorStore()
    embed = MockEmbeddingBackend(dim=384)
    await vs.initialize(embed.dimension)
    graph = MockGraphStore()
    await graph.connect()
    ingest = IngestionService(db, vs, embed, graph)
    retrieve = RetrievalService(db, vs, embed)

    cases: list[tuple[list[str], set[str]]] = []
    for user in dataset["users"]:
        uid = user["user_id"]
        id_map: dict[str, str] = {}   # dataset id -> real memory_id
        for m in user["memories"]:
            try:
                mtype = MemoryType(m.get("memory_type", "observation"))
            except ValueError:
                mtype = MemoryType.OBSERVATION
            mem = await ingest.ingest_text(text=m["text"], user_id=uid, memory_type=mtype)
            id_map[m["id"]] = mem.memory_id

        for q in user["queries"]:
            result = await retrieve.retrieve(
                RetrievalQuery(query_text=q["query"], user_id=uid, top_k=top_k)
            )
            ranked = [c.memory.memory_id for c in result.candidates]
            gold = {id_map[g] for g in q["relevant_ids"] if g in id_map}
            cases.append((ranked, gold))

    return ir_report(cases, ks=(1, 3, 5))


async def _main_async(args) -> int:
    with open(args.dataset, encoding="utf-8") as fh:
        dataset = json.load(fh)

    # Hybrid (dense + BM25 + RRF) vs dense-only ablation.
    original = settings.hybrid_retrieval_enabled
    try:
        settings.hybrid_retrieval_enabled = True
        hybrid = await _run_once(dataset, args.top_k)
        settings.hybrid_retrieval_enabled = False
        dense = await _run_once(dataset, args.top_k)
    finally:
        settings.hybrid_retrieval_enabled = original

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset.get("name", args.dataset),
        "embedding_backend": "mock (deterministic)",
        "hybrid": hybrid,
        "dense_only": dense,
        "delta_recall@5": round(hybrid.get("recall@5", 0) - dense.get("recall@5", 0), 4),
        "delta_mrr": round(hybrid.get("mrr", 0) - dense.get("mrr", 0), 4),
    }

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "ir_benchmark.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    print(json.dumps({k: out[k] for k in ("dataset", "hybrid", "dense_only",
                                          "delta_recall@5", "delta_mrr")}, indent=2))
    print(f"\nWrote {path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="AegisMem IR recall benchmark")
    ap.add_argument("--dataset", default="docs/benchmarks/sample_dataset.json")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--out", default="docs/benchmarks")
    return asyncio.run(_main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
