"""Registry of external evaluation datasets: where they come from, their license, and how to load them.

Datasets are downloaded at run time into ``~/.cache/aegis-bench`` (override: AEGIS_BENCH_CACHE) and are
never committed. Each file's SHA-256 is recorded in every report so results are tied to exact data.

Policy (see bench/VALIDATION.md):
  * Headline claims use permissively licensed datasets (MIT / Apache / CC BY-SA).
  * Datasets without an asserted license (LoCoMo, BIPIA) are used for internal evaluation only:
    downloaded at run time, never redistributed, reported with attribution.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

CACHE = Path(os.environ.get("AEGIS_BENCH_CACHE", Path.home() / ".cache" / "aegis-bench"))


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    file: str
    license: str
    use: str  # "headline" | "internal"
    citation: str


SOURCES: dict[str, Source] = {s.name: s for s in [
    Source("longmemeval_s", "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json",
           "longmemeval_s_cleaned.json", "MIT", "headline",
           "Wu et al., LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory (ICLR 2025)"),
    Source("locomo", "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json",
           "locomo10.json", "unasserted (research)", "internal",
           "Maharana et al., Evaluating Very Long-Term Conversational Memory of LLM Agents (ACL 2024)"),
    Source("beir_scifact", "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip",
           "scifact.zip", "CC BY-SA 4.0", "headline", "Thakur et al., BEIR (NeurIPS 2021); Wadden et al., SciFact"),
    Source("beir_nfcorpus", "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/nfcorpus.zip",
           "nfcorpus.zip", "CC BY-SA 4.0", "headline", "Thakur et al., BEIR (NeurIPS 2021); Boteva et al., NFCorpus"),
    Source("beir_fiqa", "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/fiqa.zip",
           "fiqa.zip", "CC BY-SA 4.0", "headline", "Thakur et al., BEIR (NeurIPS 2021); Maia et al., FiQA"),
    Source("injecagent_dh", "https://raw.githubusercontent.com/uiuc-kang-lab/InjecAgent/main/data/test_cases_dh_base.json",
           "injecagent/test_cases_dh_base.json", "MIT", "headline",
           "Zhan et al., InjecAgent: Benchmarking Indirect Prompt Injections in Tool-Integrated LLM Agents (ACL 2024)"),
    Source("injecagent_ds", "https://raw.githubusercontent.com/uiuc-kang-lab/InjecAgent/main/data/test_cases_ds_base.json",
           "injecagent/test_cases_ds_base.json", "MIT", "headline", "Zhan et al., InjecAgent (ACL 2024)"),
    Source("bipia_text_attacks", "https://raw.githubusercontent.com/microsoft/BIPIA/main/benchmark/text_attack_test.json",
           "bipia/text_attack_test.json", "unasserted (research)", "internal",
           "Yi et al., Benchmarking and Defending Against Indirect Prompt Injection Attacks on LLMs (BIPIA)"),
    Source("bipia_text_attacks_train", "https://raw.githubusercontent.com/microsoft/BIPIA/main/benchmark/text_attack_train.json",
           "bipia/text_attack_train.json", "unasserted (research)", "internal", "Yi et al., BIPIA"),
    *[Source(f"bipia_{sub}_{sp}", f"https://raw.githubusercontent.com/microsoft/BIPIA/main/benchmark/{sub}/{sp}.jsonl",
             f"bipia/{sub}_{sp}.jsonl", "unasserted (research)", "internal", "Yi et al., BIPIA")
      for sub in ("email", "table", "code") for sp in ("train", "test")],
    Source("oasst1", "https://huggingface.co/datasets/OpenAssistant/oasst1/resolve/main/2023-04-12_oasst_ready.messages.jsonl.gz",
           "oasst/ready.messages.jsonl.gz", "Apache-2.0", "headline",
           "Kopf et al., OpenAssistant Conversations (NeurIPS 2023 Datasets and Benchmarks)"),
    Source("spml", "https://huggingface.co/datasets/reshabhs/SPML_Chatbot_Prompt_Injection/resolve/main/spml_prompt_injection.csv",
           "spml/spml.csv", "MIT", "headline", "Sharma et al., SPML: A DSL for Defending Language Models Against Prompt Attacks"),
    *[Source(f"deepset_{sp}", f"https://huggingface.co/datasets/deepset/prompt-injections/resolve/main/data/{f}",
             f"deepset/{sp}.parquet", "Apache-2.0", "headline", "deepset/prompt-injections")
      for sp, f in (("train", "train-00000-of-00001-9564e8b05b4757ab.parquet"),
                    ("test", "test-00000-of-00001-701d16158af87368.parquet"))],
    *[Source(f"gandalf_{sp}", f"https://huggingface.co/datasets/Lakera/gandalf_ignore_instructions/resolve/main/data/{f}",
             f"gandalf/{sp}.parquet", "MIT", "headline", "Lakera, gandalf_ignore_instructions (human attacks)")
      for sp, f in (("train", "train-00000-of-00001-ded53be747ff55cd.parquet"),
                    ("validation", "validation-00000-of-00001-94481a2a09ff2fff.parquet"),
                    ("test", "test-00000-of-00001-bc92128b9288a6d1.parquet"))],
]}


def path(name: str) -> Path:
    return CACHE / SOURCES[name].file


def fetch(name: str) -> Path:
    """Download if missing; returns the local path."""
    src, p = SOURCES[name], path(name)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        urllib.request.urlretrieve(src.url, tmp)  # noqa: S310 - fixed https URLs above
        tmp.rename(p)
    return p


def sha256(name: str) -> str:
    h = hashlib.sha256()
    with open(fetch(name), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(names: list[str]) -> list[dict[str, Any]]:
    return [{"name": n, "license": SOURCES[n].license, "use": SOURCES[n].use, "url": SOURCES[n].url,
             "sha256": sha256(n), "citation": SOURCES[n].citation} for n in names]


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_json(name: str) -> Any:
    return json.loads(fetch(name).read_text())


def load_jsonl(name: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in fetch(name).read_text().splitlines() if line.strip()]


def load_beir(name: str, split: str = "test") -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, int]]]:
    """Returns (corpus id->text, queries id->text, qrels qid->{docid: rel})."""
    zpath = fetch(name)
    base = zpath.with_suffix("")
    if not base.exists():
        with zipfile.ZipFile(zpath) as z:
            z.extractall(zpath.parent)

    def rows(p: Path) -> Iterator[dict[str, Any]]:
        opener = gzip.open if p.suffix == ".gz" else open
        with opener(p, "rt") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)

    corpus = {r["_id"]: ((r.get("title") or "") + " " + r["text"]).strip() for r in rows(base / "corpus.jsonl")}
    queries = {r["_id"]: r["text"] for r in rows(base / "queries.jsonl")}
    qrels: dict[str, dict[str, int]] = {}
    for line in (base / "qrels" / f"{split}.tsv").read_text().splitlines()[1:]:
        qid, did, rel = line.split("\t")
        if int(rel) > 0:
            qrels.setdefault(qid, {})[did] = int(rel)
    queries = {q: t for q, t in queries.items() if q in qrels}
    return corpus, queries, qrels


def load_parquet(name: str) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq  # bench extra
    return pq.read_table(fetch(name)).to_pylist()


def tree_split(tree_id: str, seed_share: int = 10) -> str:
    """Deterministic split by conversation tree: ~10% "seed", rest "heldout" (no tree on both sides)."""
    return "seed" if int(hashlib.sha256(tree_id.encode()).hexdigest(), 16) % 100 < seed_share else "heldout"


def load_oasst(split: str) -> list[dict[str, Any]]:
    """oasst1 messages (deleted and failed-review messages removed), filtered to one split."""
    rows = []
    with gzip.open(fetch("oasst1"), "rt") as f:
        for line in f:
            r = json.loads(line)
            if r.get("deleted") or r.get("review_result") is False or not r.get("text"):
                continue
            if tree_split(r["message_tree_id"]) == split:
                rows.append(r)
    return rows


def _half(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % 2


def injecagent_split(row: dict[str, Any]) -> str | None:
    """Strict split: a case is "seed" only if BOTH its attacker instruction and its user tool are in
    the seed half, "heldout" only if BOTH are held out. Mixed cases are dropped, so no held-out case
    shares an attack text or a tool-response template with the seeds."""
    a, t = _half(row["Attacker Instruction"]), _half("tool:" + row["User Tool"])
    if a == 0 and t == 0:
        return "seed"
    if a == 1 and t == 1:
        return "heldout"
    return None


def load_injecagent(split: str) -> list[dict[str, Any]]:
    rows = load_json("injecagent_dh") + load_json("injecagent_ds")
    return [r for r in rows if injecagent_split(r) == split]
