"""
AegisMem Benchmark Runner
==========================
Runs the full evaluation suite with multi-K metrics and benchmark modes.

Usage:
    python scripts/run_local_eval.py                # expanded mode (default)
    python scripts/run_local_eval.py --mode sanity   # quick smoke test
    python scripts/run_local_eval.py --mode hard     # hard benchmark
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.llm.factory import create_llm_client
from adapters.embeddings.backend import SentenceTransformerBackend
from adapters.vector_store.qdrant_store import InMemoryVectorStore
from adapters.graph_store.neo4j_store import MockGraphStore
from services.ingest_service import IngestionService
from services.retrieve_service import RetrievalService
from services.contradiction_service import ContradictionService
from domain.evaluations.evaluator import EvaluationRunner, EvalMode
from tests.fixtures.conftest import MockPostgresStore


def parse_args():
    parser = argparse.ArgumentParser(description="AegisMem Benchmark Suite")
    parser.add_argument(
        "--mode", choices=["sanity", "expanded", "hard", "contradiction"],
        default="expanded", help="Benchmark mode",
    )
    return parser.parse_args()


async def main(mode: EvalMode):
    print("\n" + "=" * 65)
    print(f"  AegisMem Benchmark Suite — {mode.value.upper()} mode")
    print("=" * 65 + "\n")

    # Setup: real embeddings, mock infrastructure.
    embed = SentenceTransformerBackend(model_name="BAAI/bge-large-en-v1.5")
    vs = InMemoryVectorStore()
    await vs.initialize(dimension=embed.dimension)
    graph = MockGraphStore()
    db = MockPostgresStore()
    llm = create_llm_client()

    ingest = IngestionService(db, vs, embed, graph, llm)
    retrieve = RetrievalService(db, vs, embed)
    contradiction = ContradictionService(db, vs, embed, llm, graph)

    runner = EvaluationRunner(ingest, retrieve, contradiction)

    print("Running evaluation suites...\n")

    # --- Retrieval Evaluation ---
    if mode != EvalMode.CONTRADICTION:
        print("📊 Retrieval Evaluation")
        print("  Ingesting synthetic dataset...")
        rm = await runner.run_retrieval_eval(
            user_id="bench_retrieval", mode=mode,
        )
        print(f"  Dataset:      {rm.total_queries} queries, {rm.total_memories} memories")
        print(f"  P@1:          {rm.precision_at_1:.3f}")
        print(f"  P@3:          {rm.precision_at_3:.3f}")
        print(f"  P@5:          {rm.precision_at_5:.3f}")
        print(f"  R@1:          {rm.recall_at_1:.3f}")
        print(f"  R@3:          {rm.recall_at_3:.3f}")
        print(f"  R@5:          {rm.recall_at_5:.3f}")
        print(f"  F1@1:         {rm.f1_at_1:.3f}")
        print(f"  F1@3:         {rm.f1_at_3:.3f}")
        print(f"  F1@5:         {rm.f1_at_5:.3f}")
        print(f"  MRR:          {rm.mrr:.3f}")
        print(f"  nDCG@5:       {rm.ndcg_at_5:.3f}")
        print(f"  Avg Latency:  {rm.latency_ms:.1f}ms")

    # --- Contradiction Evaluation ---
    print("\n📊 Contradiction Detection Evaluation")
    cm = await runner.run_contradiction_eval(user_id="bench_contradiction")
    print(f"  Dataset:          {cm.total_pairs} pairs")
    print(f"  True Positives:   {cm.true_positives}")
    print(f"  True Negatives:   {cm.true_negatives}")
    print(f"  False Positives:  {cm.false_positives}")
    print(f"  False Negatives:  {cm.false_negatives}")
    print(f"  Precision:        {cm.precision:.3f}")
    print(f"  Recall:           {cm.recall:.3f}")
    print(f"  F1 Score:         {cm.f1:.3f}")

    print("\n" + "=" * 65)
    print("  Benchmark Complete")
    print("=" * 65 + "\n")

    result: dict[str, Any] = {}
    if mode != EvalMode.CONTRADICTION:
        result["retrieval"] = {
            "P@1": rm.precision_at_1, "P@3": rm.precision_at_3, "P@5": rm.precision_at_5,
            "R@1": rm.recall_at_1, "R@3": rm.recall_at_3, "R@5": rm.recall_at_5,
            "F1@1": rm.f1_at_1, "F1@3": rm.f1_at_3, "F1@5": rm.f1_at_5,
            "MRR": rm.mrr, "nDCG@5": rm.ndcg_at_5,
            "latency_ms": rm.latency_ms,
            "total_queries": rm.total_queries, "total_memories": rm.total_memories,
        }
    result["contradiction"] = {
        "precision": cm.precision, "recall": cm.recall, "f1": cm.f1,
        "total_pairs": cm.total_pairs,
    }
    return result


if __name__ == "__main__":
    args = parse_args()
    eval_mode = EvalMode(args.mode)
    results = asyncio.run(main(eval_mode))
    print("JSON Results:")
    print(json.dumps(results, indent=2))
