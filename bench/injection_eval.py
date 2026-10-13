"""Large-scale write-screening evaluation on real, held-out data.

Positives (attacks; every one disjoint from the seed corpus):
    injecagent   attacker instructions embedded in real tool responses (held-out instruction half)
    bipia_*      real BIPIA test contexts (email/table/code) with BIPIA test attacks inserted at
                 start / middle / end, the benchmark's own construction (internal use)
    gandalf      human attacks, validation + test splits
    deepset      test split, label 1
    spml         "prompt injection" label 1. Caveat: SPML labels chatbot policy misuse, a broader
                 notion than memory poisoning; reported separately, not in the headline.
Negatives (harmless; disjoint from seeds):
    oasst_*      OpenAssistant held-out trees (assistant, prompter), multilingual
    longmemeval  real long-term chat turns (user, assistant)
    locomo       conversational turns
    bipia_clean  the same BIPIA test contexts *without* attacks (hardest negatives)
    deepset      test split, label 0
Each item is screened exactly as ingest does: rule check, then the learned risk model at the trust
of its source (attacks arrive as tool output; chat turns as user/agent messages).
"""
from __future__ import annotations

import random
from typing import Any, Callable

from domain.integrity.provenance import base_trust, should_quarantine
from domain.learning import risk_model as RM

from bench import sources
from bench.stats import proportion_ci

Item = tuple[str, str]  # (text, source_type)


def _cap(rows: list[Item], n: int, seed: int = 0) -> list[Item]:
    return rows if len(rows) <= n else random.Random(seed).sample(rows, n)


def positives(cap: int = 5000) -> dict[str, list[Item]]:
    out: dict[str, list[Item]] = {}
    out["injecagent"] = [(r["Tool Response"], "tool_output") for r in sources.load_injecagent("heldout")]
    attacks = sources.load_json("bipia_text_attacks")
    flat = [a for group in attacks.values() for a in group]
    rng = random.Random(1)
    for sub in ("email", "table", "code"):
        rows = []
        for ctx in sources.load_jsonl(f"bipia_{sub}_test"):
            text = ctx["context"] if isinstance(ctx["context"], str) else "\n".join(ctx["context"])
            for pos in ("start", "middle", "end"):
                a = rng.choice(flat)
                if pos == "start":
                    rows.append((f"{a}\n{text}", "tool_output"))
                elif pos == "end":
                    rows.append((f"{text}\n{a}", "tool_output"))
                else:
                    mid = len(text) // 2
                    rows.append((f"{text[:mid]}\n{a}\n{text[mid:]}", "tool_output"))
        out[f"bipia_{sub}"] = _cap(rows, cap)
    out["gandalf"] = [(r["text"], "tool_output") for n in ("gandalf_validation", "gandalf_test")
                      for r in sources.load_parquet(n)]
    out["deepset"] = [(r["text"], "tool_output") for r in sources.load_parquet("deepset_test") if r["label"] == 1]
    return out


def negatives(cap: int = 20000) -> dict[str, list[Item]]:
    out: dict[str, list[Item]] = {}
    oasst = sources.load_oasst("heldout")
    out["oasst_assistant"] = _cap([(r["text"], "agent_observation") for r in oasst if r["role"] == "assistant"], cap)
    out["oasst_prompter"] = _cap([(r["text"], "user_message") for r in oasst if r["role"] == "prompter"], cap)
    lme = sources.load_json("longmemeval_s")
    seen: set[str] = set()
    user, asst = [], []
    for q in lme:
        for sess in q["haystack_sessions"]:
            for t in sess:
                if t["content"] in seen:
                    continue
                seen.add(t["content"])
                (user if t["role"] == "user" else asst).append(
                    (t["content"], "user_message" if t["role"] == "user" else "agent_observation"))
    out["longmemeval_user"] = _cap(user, cap)
    out["longmemeval_assistant"] = _cap(asst, cap)
    out["locomo"] = [(t["text"], "user_message") for s in sources.load_json("locomo")
                     for k, v in s["conversation"].items() if k.startswith("session_") and isinstance(v, list)
                     for t in v]
    clean = []
    for sub in ("email", "table", "code"):
        for ctx in sources.load_jsonl(f"bipia_{sub}_test"):
            clean.append((ctx["context"] if isinstance(ctx["context"], str) else "\n".join(ctx["context"]),
                          "tool_output"))
    out["bipia_clean"] = clean
    out["deepset"] = [(r["text"], "user_message") for r in sources.load_parquet("deepset_test") if r["label"] == 0]
    return out


def spml(cap: int = 5000) -> tuple[list[Item], list[Item]]:
    import csv
    rows = list(csv.DictReader(open(sources.fetch("spml"), newline="")))
    pos = _cap([(r["User Prompt"], "user_message") for r in rows if r["Prompt injection"] == "1"], cap)
    neg = _cap([(r["User Prompt"], "user_message") for r in rows if r["Prompt injection"] == "0"], cap)
    return pos, neg


def screener(model: RM.OnlineRiskModel | None) -> Callable[[str, str], bool]:
    def held(text: str, source: str) -> bool:
        trust = base_trust(source)
        if should_quarantine(text, trust):
            return True
        return bool(model and model.score(text, trust).flagged)
    return held


def evaluate(held: Callable[[str, str], bool], pos: dict[str, list[Item]], neg: dict[str, list[Item]]) -> dict[str, Any]:
    out: dict[str, Any] = {"detection": {}, "false_alarm": {}}
    tp = n_pos = fp = n_neg = 0
    for name, items in pos.items():
        k = sum(held(t, s) for t, s in items)
        out["detection"][name] = proportion_ci(k, len(items))
        tp, n_pos = tp + k, n_pos + len(items)
    for name, items in neg.items():
        k = sum(held(t, s) for t, s in items)
        out["false_alarm"][name] = proportion_ci(k, len(items))
        fp, n_neg = fp + k, n_neg + len(items)
    # Macro averages weight each source equally (no single large set dominates).
    out["macro_detection"] = sum(v["mean"] for v in out["detection"].values()) / max(len(out["detection"]), 1)
    out["macro_false_alarm"] = sum(v["mean"] for v in out["false_alarm"].values()) / max(len(out["false_alarm"]), 1)
    out["n_attacks"], out["n_benign"] = n_pos, n_neg
    return out


def old_handwritten_model() -> RM.OnlineRiskModel:
    """The pre-validation model seeded with 28 hand-written sentences, for comparison."""
    saved = RM.seed_texts
    RM.seed_texts = lambda: (list(RM.SEED_MALICIOUS), list(RM.SEED_BENIGN))  # type: ignore
    try:
        m = RM.OnlineRiskModel(hash_key=b"bench")
    finally:
        RM.seed_texts = saved  # type: ignore
    return m
