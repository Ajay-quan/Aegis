"""Full-scale validation orchestrator (resumable). Results land in ``bench-results/validation``.

    python -m bench.validate --suites injection learning integrity            # embedding-light
    python -m bench.validate --suites recall beir --models all-minilm nomic-embed-text mxbai-embed-large
    python -m bench.report                                                     # -> bench/VALIDATION.md

Each (suite, dataset, model) result is written as JSON when it finishes; existing results are skipped,
so long runs can be interrupted and resumed. Embeddings are local (Ollama) and cached on disk.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from bench import sources

OUT = Path("bench-results/validation")
MODELS = {"all-minilm": 384, "nomic-embed-text": 768, "mxbai-embed-large": 1024}
BEIR = ("beir_scifact", "beir_nfcorpus", "beir_fiqa")


def _meta() -> dict[str, Any]:
    def sh(*cmd: str) -> str:
        try:
            return subprocess.check_output(cmd, text=True).strip()
        except Exception:
            return "unknown"
    from core.version import __version__
    return {"git_sha": sh("git", "rev-parse", "--short", "HEAD"), "version": __version__,
            "python": platform.python_version(), "machine": platform.platform(),
            "cpu": sh("sysctl", "-n", "machdep.cpu.brand_string"),
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def _save(name: str, result: dict[str, Any], datasets: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"meta": _meta(), "datasets": sources.manifest(datasets), "result": result}
    (OUT / f"{name}.json").write_text(json.dumps(payload, indent=2, default=str))
    print(f"  saved {name}.json", flush=True)


def _done(name: str) -> bool:
    return (OUT / f"{name}.json").exists()


async def run(suites: list[str], models: list[str], limit: int | None) -> None:
    from bench.embedcache import CachedEmbedding

    if "injection" in suites and not _done("injection"):
        from bench import injection_eval as IE
        from domain.learning.risk_model import OnlineRiskModel
        print("== injection screening (real held-out data)", flush=True)
        pos, neg = IE.positives(), IE.negatives()
        res = {"rules_only": IE.evaluate(IE.screener(None), pos, neg),
               "old_handwritten_seeds": IE.evaluate(IE.screener(IE.old_handwritten_model()), pos, neg),
               "real_data_seeds": IE.evaluate(IE.screener(OnlineRiskModel(hash_key=b"validation")), pos, neg)}
        sp, sn = IE.spml()
        res["spml_caveat"] = IE.evaluate(IE.screener(OnlineRiskModel(hash_key=b"validation")),
                                         {"spml": sp}, {"spml": sn})
        _save("injection", res, ["injecagent_dh", "injecagent_ds", "bipia_text_attacks", "gandalf_test",
                                 "gandalf_validation", "deepset_test", "oasst1", "longmemeval_s", "locomo", "spml"])

    if "learning" in suites and not _done("learning"):
        from bench import injection_learning as IL
        print("== reviewer learning (50 randomized runs per setting)", flush=True)
        _save("learning", await asyncio.to_thread(IL.run, 50), ["injecagent_dh", "injecagent_ds",
                                                                "bipia_text_attacks", "bipia_text_attacks_train", "oasst1"])

    if "integrity" in suites and not _done("integrity"):
        from bench import integrity_scale as IS
        print("== revocation and erasure at scale (real turns)", flush=True)
        emb = CachedEmbedding("all-minilm", MODELS["all-minilm"])
        res = {"revocation": await IS.revocation(emb, cases_per_kind=1000),
               "erasure": await IS.erasure(emb, subjects=2000), "embedding_model": "all-minilm"}
        _save("integrity", res, ["longmemeval_s"])

    for model in models:
        emb = CachedEmbedding(model, MODELS[model])
        if "recall" in suites:
            from bench import memory_recall as MR
            for ds, loader, names in (("longmemeval_s", MR.longmemeval, ["longmemeval_s"]),
                                      ("locomo", MR.locomo, ["locomo"])):
                name = f"recall-{ds}-{model}"
                if _done(name):
                    continue
                print(f"== recall {ds} / {model}", flush=True)
                corpora = loader(limit)
                await emb.prefill([t.text for c in corpora for t in c.turns] +
                                  [q.text for c in corpora for q in c.questions], progress=True)
                _save(name, await MR.run(corpora, emb, ds), names)
                emb.evict()
        if "beir" in suites:
            from bench import beir_eval as BE
            for ds in BEIR:
                name = f"beir-{ds}-{model}"
                if _done(name):
                    continue
                print(f"== BEIR {ds} / {model}", flush=True)
                _save(name, await BE.run(ds, emb), [ds])
                emb.evict()


def main() -> None:
    ap = argparse.ArgumentParser(prog="bench.validate")
    ap.add_argument("--suites", nargs="+", default=["injection", "learning", "integrity", "recall", "beir"])
    ap.add_argument("--models", nargs="+", default=list(MODELS), choices=list(MODELS))
    ap.add_argument("--limit", type=int, default=None, help="max corpora per recall dataset (debugging)")
    args = ap.parse_args()
    logging.disable(logging.WARNING)
    asyncio.run(run(args.suites, args.models, args.limit))


if __name__ == "__main__":
    main()
