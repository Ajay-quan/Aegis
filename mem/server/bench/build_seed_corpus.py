"""Build the risk model's starting corpus from real, permissively licensed *training* data.

Replaces the 28 hand-written seed sentences (which taught the model that the word "assistant"
and helpful phrasing like "you should" were attack signals).

    python -m bench.build_seed_corpus           # writes domain/learning/seed_corpus.jsonl.gz

Sources (train/seed splits only; every evaluation set is disjoint):
    malicious  Lakera gandalf_ignore_instructions train (MIT), deepset/prompt-injections train label 1 (Apache-2.0),
               InjecAgent tool responses whose attacker instruction is in the seed half (MIT)
    benign     OpenAssistant oasst1 seed-split trees (Apache-2.0), deepset train label 0 (Apache-2.0)
"""
from __future__ import annotations

import gzip
import json
import random
from pathlib import Path

from bench import sources

OUT = Path(__file__).resolve().parents[1] / "domain" / "learning" / "seed_corpus.jsonl.gz"
MAX_CHARS = 1000


def build(n_benign_assistant: int = 2500, n_benign_user: int = 1500, seed: int = 0) -> dict[str, int]:
    rng = random.Random(seed)
    rows: list[dict] = []
    for r in sources.load_parquet("gandalf_train"):
        rows.append({"text": r["text"], "label": 1, "src": "gandalf"})
    for r in sources.load_parquet("deepset_train"):
        rows.append({"text": r["text"], "label": int(r["label"]), "src": "deepset"})
    for r in sources.load_injecagent("seed"):
        rows.append({"text": r["Tool Response"], "label": 1, "src": "injecagent"})
    oasst = sources.load_oasst("seed")
    assistant = [r for r in oasst if r["role"] == "assistant"]
    prompter = [r for r in oasst if r["role"] == "prompter"]
    for r in rng.sample(assistant, min(n_benign_assistant, len(assistant))):
        rows.append({"text": r["text"], "label": 0, "src": "oasst-assistant", "lang": r.get("lang")})
    for r in rng.sample(prompter, min(n_benign_user, len(prompter))):
        rows.append({"text": r["text"], "label": 0, "src": "oasst-prompter", "lang": r.get("lang")})
    rng.shuffle(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt") as f:
        for r in rows:
            f.write(json.dumps({"text": r["text"][:MAX_CHARS], "label": r["label"], "src": r["src"]}) + "\n")
    counts: dict[str, int] = {}
    for r in rows:
        counts[f"{r['src']}:{r['label']}"] = counts.get(f"{r['src']}:{r['label']}", 0) + 1
    return counts


if __name__ == "__main__":
    print(build())
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KiB)")
