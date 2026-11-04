"""LoCoMo recall-impact benchmark (real embeddings; opt-in, not part of the default CI gates).

Question: does AegisMem's integrity layer (screening, guard, scoring, reranking) cost recall
compared with raw vector search over the same index?

    AEGIS_BENCH_EMBED_URL=http://localhost:11434/v1 AEGIS_BENCH_EMBED_MODEL=nomic-embed-text \\
    AEGIS_BENCH_EMBED_DIM=768 python -m bench.locomo [--k 5 10] [--conversations 10]

Every turn is ingested through the full pipeline as a user message. For each question with gold
evidence turns (categories 1-4; category 5 is adversarial "not answerable"), we compute
recall@k (fraction of evidence turns retrieved) and hit@k (any evidence retrieved).

LoCoMo (snap-research/locomo, CC BY-NC 4.0) is downloaded to a cache at run time and never
committed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from adapters.embeddings.backend import EmbeddingBackend, OpenAICompatibleEmbeddingBackend
from core.schemas.memory import RetrievalQuery, SourceType

from bench.harness import build_env

LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
CACHE = Path(os.environ.get("AEGIS_BENCH_CACHE", Path.home() / ".cache" / "aegis-bench"))


class CachedEmbedding(EmbeddingBackend):
    """Batch-prefilled cache so a 6k-turn corpus costs ~100 API calls, not 6k."""

    def __init__(self, inner: EmbeddingBackend, dim: int) -> None:
        self._inner, self._dim, self._cache = inner, dim, {}

    @property
    def dimension(self) -> int:
        return self._dim

    async def prefill(self, texts: list[str]) -> None:
        todo = list(dict.fromkeys(t for t in texts if t not in self._cache))
        for i in range(0, len(todo), 64):
            chunk = todo[i:i + 64]
            for t, v in zip(chunk, await self._inner.embed(chunk)):
                self._cache[t] = v

    async def embed(self, texts: list[str]) -> list[list[float]]:
        missing = [t for t in texts if t not in self._cache]
        if missing:
            await self.prefill(missing)
        return [self._cache[t] for t in texts]


def load_locomo() -> list[dict[str, Any]]:
    path = CACHE / "locomo10.json"
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(LOCOMO_URL, path)  # noqa: S310 - fixed https URL
    return json.loads(path.read_text())


def _turns(sample: dict[str, Any]) -> list[dict[str, str]]:
    conv = sample["conversation"]
    out = []
    for key, val in conv.items():
        if key.startswith("session_") and isinstance(val, list):
            date = conv.get(f"{key}_date_time", "")
            for t in val:
                out.append({"dia_id": t["dia_id"], "text": f"[{date}] {t['speaker']}: {t['text']}"})
    return out


async def run(ks: tuple[int, ...] = (5, 10), conversations: int = 10) -> dict[str, Any]:
    dim = int(os.environ["AEGIS_BENCH_EMBED_DIM"])
    embed = CachedEmbedding(OpenAICompatibleEmbeddingBackend(
        os.environ["AEGIS_BENCH_EMBED_URL"], os.environ["AEGIS_BENCH_EMBED_MODEL"],
        os.environ.get("AEGIS_BENCH_EMBED_KEY", ""), dim), dim)
    data = load_locomo()[:conversations]
    kmax = max(ks)
    per_k: dict[int, dict[str, list[float]]] = {k: {"aegis_recall": [], "raw_recall": [], "aegis_hit": [],
                                                    "raw_hit": []} for k in ks}
    quarantined = turns_total = questions = 0
    t0 = time.time()

    for sample in data:
        env = await build_env(dim=dim)
        env.ingest._embed = env.retrieve._embed = embed
        user = sample["sample_id"]
        turns = _turns(sample)
        await embed.prefill([t["text"] for t in turns])
        id_to_dia: dict[str, str] = {}
        for t in turns:
            m = await env.ingest.ingest_text(t["text"], user_id=user, source_type=SourceType.USER_MESSAGE,
                                             metadata={"dia_id": t["dia_id"]})
            id_to_dia[m.memory_id] = t["dia_id"]
            quarantined += m.status == "pending"
        turns_total += len(turns)

        qas = [q for q in sample["qa"] if q.get("category") in (1, 2, 3, 4) and q.get("evidence")]
        await embed.prefill([q["question"] for q in qas])
        for q in qas:
            gold = set(q["evidence"])
            r = await env.retrieve.retrieve(RetrievalQuery(query_text=q["question"], user_id=user, top_k=kmax))
            aegis = [id_to_dia.get(c.memory.memory_id) for c in r.candidates]
            raw_hits = await env.raw_vs.search(await embed.embed_single(q["question"]), top_k=kmax,
                                               filter={"user_id": user})
            raw = [id_to_dia.get(h.id) for h in raw_hits]
            for k in ks:
                for name, ranked in (("aegis", aegis[:k]), ("raw", raw[:k])):
                    found = gold & set(ranked)
                    per_k[k][f"{name}_recall"].append(len(found) / len(gold))
                    per_k[k][f"{name}_hit"].append(1.0 if found else 0.0)
            questions += 1

    out: dict[str, Any] = {"conversations": len(data), "turns": turns_total, "questions": questions,
                           "turns_quarantined": quarantined,
                           "embedding_model": os.environ["AEGIS_BENCH_EMBED_MODEL"],
                           "seconds": round(time.time() - t0, 1)}
    for k in ks:
        for metric, vals in per_k[k].items():
            out[f"{metric}@{k}"] = round(statistics.mean(vals), 4)
        out[f"recall_delta@{k}"] = round(out[f"aegis_recall@{k}"] - out[f"raw_recall@{k}"], 4)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="bench.locomo")
    ap.add_argument("--k", nargs="+", type=int, default=[5, 10])
    ap.add_argument("--conversations", type=int, default=10)
    ap.add_argument("--out")
    args = ap.parse_args()
    logging.disable(logging.WARNING)
    for var in ("AEGIS_BENCH_EMBED_URL", "AEGIS_BENCH_EMBED_MODEL", "AEGIS_BENCH_EMBED_DIM"):
        if var not in os.environ:
            sys.exit(f"set {var} (see module docstring)")
    result = asyncio.run(run(tuple(args.k), args.conversations))
    print(json.dumps(result, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
