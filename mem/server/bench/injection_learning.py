"""Does reviewer feedback teach a deployment to catch *new* attacks, without raising false alarms?

Protocol per environment, repeated over many randomized runs:
  1. A fresh tenant model (real-data seeds, run-specific hash key).
  2. A deployment stream: attacks from the environment's *stream* split, interleaved with harmless
     traffic (``benign_ratio`` x attacks). Reviewers judge every held item (reject / release);
     missed attacks are reported as malicious with probability ``report_rate``; harmless memories the
     agent uses produce implicit benign signals with probability ``use_rate``.
  3. Evaluate on the environment's *future* split (attack texts never seen in the stream) and on a
     separate harmless set, recording detection and false-alarm rate.

Environments (stream and future are disjoint by attack text):
  injecagent  held-out tools only (never in seeds); attacker instructions split stream/future
  bipia       BIPIA train contexts x train attacks -> BIPIA test contexts x test attacks
"""
from __future__ import annotations

import random
import statistics
from typing import Any

from domain.learning.risk_model import OnlineRiskModel

from bench import sources
from bench.injection_eval import Item, negatives, screener
from bench.stats import mean_ci


def _bipia(split: str, rng: random.Random) -> list[Item]:
    attacks = sources.load_json("bipia_text_attacks" if split == "test" else "bipia_text_attacks_train")
    flat = [a for group in attacks.values() for a in group]
    rows = []
    for sub in ("email", "table", "code"):
        for ctx in sources.load_jsonl(f"bipia_{sub}_{split}"):
            text = ctx["context"] if isinstance(ctx["context"], str) else "\n".join(ctx["context"])
            a = rng.choice(flat)
            pos = rng.choice(("start", "middle", "end"))
            mid = len(text) // 2
            rows.append(({"start": f"{a}\n{text}", "end": f"{text}\n{a}",
                          "middle": f"{text[:mid]}\n{a}\n{text[mid:]}"}[pos], "tool_output"))
    return rows


def environments(rng: random.Random) -> dict[str, tuple[list[Item], list[Item]]]:
    held = sources.load_injecagent("heldout")
    instr = sorted({r["Attacker Instruction"] for r in held})
    rng.shuffle(instr)
    stream_instr = set(instr[: len(instr) // 2])
    inj_stream = [(r["Tool Response"], "tool_output") for r in held if r["Attacker Instruction"] in stream_instr]
    inj_future = [(r["Tool Response"], "tool_output") for r in held if r["Attacker Instruction"] not in stream_instr]
    return {"injecagent": (inj_stream, inj_future),
            "bipia": (_bipia("train", rng), _bipia("test", rng))}


def run_once(stream: list[Item], future: list[Item], benign_stream: list[Item], benign_eval: list[Item],
             seed: int, report_rate: float, use_rate: float, benign_ratio: int) -> dict[str, float]:
    rng = random.Random(seed)
    model = OnlineRiskModel(hash_key=f"run-{seed}".encode())
    held = screener(model)
    items = [(t, s, 1) for t, s in stream] + [(t, s, 0) for t, s in rng.sample(
        benign_stream, min(len(benign_stream), benign_ratio * len(stream)))]
    rng.shuffle(items)
    reviews = 0
    import asyncio

    async def feed() -> None:
        nonlocal reviews
        for text, src, y in items:
            if held(text, src):
                reviews += 1
                await model.learn(text, malicious=bool(y), held_by_model=True)
            elif y and rng.random() < report_rate:
                await model.learn(text, malicious=True, missed=True)
            elif not y and rng.random() < use_rate:
                await model.learn(text, malicious=False, implicit=True)
    before_det = statistics.fmean(held(t, s) for t, s in future)
    asyncio.run(feed())
    return {
        "detection_before": before_det,
        "detection_after": statistics.fmean(held(t, s) for t, s in future),
        "false_alarm_after": statistics.fmean(held(t, s) for t, s in benign_eval),
        "reviews_per_100_writes": 100 * reviews / len(items),
    }


def run(runs: int = 50, report_rates: tuple[float, ...] = (1.0, 0.5, 0.2), use_rate: float = 0.3,
        benign_ratio: int = 4, benign_eval_n: int = 5000) -> dict[str, Any]:
    neg = negatives(cap=20000)
    pool = neg["oasst_assistant"] + neg["oasst_prompter"]
    rng = random.Random(7)
    rng.shuffle(pool)
    benign_stream, benign_eval_pool = pool[: len(pool) // 2], pool[len(pool) // 2:]
    benign_eval = benign_eval_pool[:benign_eval_n] + random.Random(8).sample(
        neg["longmemeval_assistant"], benign_eval_n // 2)
    out: dict[str, Any] = {"runs": runs, "benign_ratio": benign_ratio, "use_rate": use_rate,
                           "benign_eval_n": len(benign_eval), "environments": {}}
    for rate in report_rates:
        per_env: dict[str, list[dict[str, float]]] = {}
        for i in range(runs):
            envs = environments(random.Random(1000 + i))
            for name, (stream, future) in envs.items():
                per_env.setdefault(name, []).append(run_once(
                    stream, future, benign_stream, benign_eval, seed=i, report_rate=rate,
                    use_rate=use_rate, benign_ratio=benign_ratio))
        for name, rows in per_env.items():
            out["environments"].setdefault(name, {})[f"report_{int(rate * 100)}"] = {
                k: mean_ci([r[k] for r in rows]) for k in rows[0]}
            out["environments"][name]["stream_size"] = len(environments(random.Random(1000))[name][0])
            out["environments"][name]["future_size"] = len(environments(random.Random(1000))[name][1])
    return out
