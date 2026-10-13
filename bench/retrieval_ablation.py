"""Retrieval ablations on the LongMemEval *dev* split only (test split untouched).

    python -m bench.retrieval_ablation --variants blend rrf convex:0.3 convex:0.5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from core.config.settings import settings

from bench import memory_recall as MR
from bench.answer_eval import split_of
from bench.embedcache import CachedEmbedding
from bench.validate import MODELS

OUT = Path("bench-results/ablation")


def apply(variant: str) -> None:
    mode, _, w = variant.partition(":")
    settings.hybrid_fusion = mode
    if w:
        settings.hybrid_lexical_weight = float(w)


async def main(variants: list[str], model: str, limit: int | None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    corpora = [c for c in MR.longmemeval() if split_of(c.key) == "dev"][:limit]
    emb = CachedEmbedding(model, MODELS[model])
    for v in variants:
        path = OUT / f"lme-dev-{model}-{v.replace(':', '_')}.json"
        if path.exists():
            continue
        apply(v)
        print(f"== {v} on {len(corpora)} dev questions", flush=True)
        r = await MR.run(corpora, emb, "longmemeval_s:dev", progress_every=50)
        path.write_text(json.dumps(r, indent=1, default=str))
        o = r["overall"]
        print(f"  {v}: aegis r@5 {o['aegis']['recall_all@5']['mean']:.3f} dense {o['dense']['recall_all@5']['mean']:.3f}"
              f" bm25 {o['bm25']['recall_all@5']['mean']:.3f}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="+", default=["blend", "rrf", "convex:0.3", "convex:0.5"])
    ap.add_argument("--model", default="all-minilm")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    logging.disable(logging.WARNING)
    asyncio.run(main(a.variants, a.model, a.limit))
