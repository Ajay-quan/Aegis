#!/usr/bin/env python3
"""Continual-learning evaluation harness for AegisMem-CL.

This is the *promotion gate* and the evidence that the online ranking policy
(`domain.learning.online_scorer.OnlineRankingPolicy`) genuinely learns over a
stream of tasks **without catastrophic forgetting**.

Design (task-incremental, the standard CL protocol)
---------------------------------------------------
We construct T ranking "tasks". In each task, the relevant memory among a pool
of candidates is the one that maximizes a *task-specific* signal (task 0 rewards
semantic similarity, task 1 lexical, task 2 recency, task 3 importance). A single
shared policy is trained on the tasks **in sequence**. After finishing task t we
evaluate Precision@1 on **all** tasks 0..T-1, filling a performance matrix R
where ``R[t][i]`` = P@1 on task i after training through task t.

From R we compute Average Accuracy, Backward Transfer (BWT — negative means
forgetting), Forward Transfer, and Forgetting (Lopez-Paz & Ranzato, 2017).

Three arms are compared on the identical task stream and RNG:
    * static   — fixed settings weights, no learning (the current product).
    * cl_no_ewc — online learning with the EWC anchor disabled (ablation).
    * cl_ewc    — online learning with EWC anchoring (the proposed system).

The expected, defensible result: cl_ewc has the highest average accuracy and a
BWT >= cl_no_ewc (EWC reduces forgetting), both beating the static baseline.

Run:
    python scripts/continual_eval.py --tasks 4 --out docs/benchmarks
Outputs ``continual_eval.json`` and ``continual_eval.md``.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone

# Allow running as a plain script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from domain.learning.features import FEATURE_NAMES  # noqa: E402
from domain.learning.online_scorer import OnlineRankingPolicy  # noqa: E402
from domain.learning.cl_metrics import summarize_matrix  # noqa: E402

# Each task makes ONE feature the decisive signal for relevance.
TASK_SIGNALS = list(FEATURE_NAMES)  # semantic, lexical, recency, importance, access


def _sample_candidates(rng: random.Random, n: int) -> list[dict[str, float]]:
    """A pool of candidates, each a random feature vector in [0, 1]^5."""
    return [{f: rng.random() for f in FEATURE_NAMES} for _ in range(n)]


def _relevant_index(candidates: list[dict[str, float]], signal: str) -> int:
    """The 'correct' candidate is the one highest on this task's signal."""
    return max(range(len(candidates)), key=lambda i: candidates[i][signal])


def _rank(policy: OnlineRankingPolicy, ns: str, candidates: list[dict[str, float]]) -> list[int]:
    scored = [(i, policy.predict(ns, c)) for i, c in enumerate(candidates)]
    scored.sort(key=lambda t: t[1], reverse=True)
    return [i for i, _ in scored]


def _precision_at_1(policy, ns, rng, signal, pool, queries) -> float:
    hits = 0
    for _ in range(queries):
        cands = _sample_candidates(rng, pool)
        rel = _relevant_index(cands, signal)
        order = _rank(policy, ns, cands)
        if order[0] == rel:
            hits += 1
    return hits / queries


def _train_task(policy, ns, rng, signal, pool, steps) -> None:
    """Online updates: reward the truly-relevant candidate, penalize a decoy."""
    for _ in range(steps):
        cands = _sample_candidates(rng, pool)
        rel = _relevant_index(cands, signal)
        order = _rank(policy, ns, cands)
        # Positive signal on the relevant candidate.
        policy.update(ns, cands[rel], reward=1.0)
        # Negative signal on the current top pick if it is wrong.
        if order[0] != rel:
            policy.update(ns, cands[order[0]], reward=0.0)


def _run_arm(name, *, tasks, learn, ewc, base_weights, lr, ewc_lambda,
             pool, train_steps, eval_queries, seed) -> dict:
    """Run one experimental arm and return its performance matrix + metrics."""
    ns = "continual-eval"
    policy = OnlineRankingPolicy(
        base_weights=base_weights,
        learning_rate=lr,
        ewc_lambda=ewc_lambda if ewc else 0.0,
    )
    signals = [TASK_SIGNALS[i % len(TASK_SIGNALS)] for i in range(tasks)]

    # Evaluation uses a fixed seed so all arms see identical eval candidates.
    R: list[list[float]] = []
    for t in range(tasks):
        if learn:
            train_rng = random.Random(seed + 1000 * t)
            _train_task(policy, ns, train_rng, signals[t], pool, train_steps)
            policy.consolidate(ns)  # online-EWC task boundary
        row = []
        for i in range(tasks):
            eval_rng = random.Random(99_999 + 7 * i)  # same eval set across arms
            row.append(_precision_at_1(policy, ns, eval_rng, signals[i], pool, eval_queries))
        R.append(row)

    return {"arm": name, "matrix": R, "metrics": summarize_matrix(R), "final_weights": policy.weights(ns)}


def main() -> int:
    ap = argparse.ArgumentParser(description="AegisMem-CL continual-learning eval")
    ap.add_argument("--tasks", type=int, default=4)
    ap.add_argument("--pool", type=int, default=8, help="candidates per query")
    ap.add_argument("--train-steps", type=int, default=300)
    ap.add_argument("--eval-queries", type=int, default=200)
    ap.add_argument("--lr", type=float, default=0.1)
    ap.add_argument("--ewc-lambda", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="docs/benchmarks")
    args = ap.parse_args()

    base = {f: 1.0 / len(FEATURE_NAMES) for f in FEATURE_NAMES}  # neutral prior
    common = dict(
        tasks=args.tasks, base_weights=base, lr=args.lr, ewc_lambda=args.ewc_lambda,
        pool=args.pool, train_steps=args.train_steps, eval_queries=args.eval_queries,
        seed=args.seed,
    )

    arms = [
        _run_arm("static", learn=False, ewc=False, **common),
        _run_arm("cl_no_ewc", learn=True, ewc=False, **common),
        _run_arm("cl_ewc", learn=True, ewc=True, **common),
    ]

    static_acc = arms[0]["metrics"]["average_accuracy"]
    cl_acc = arms[2]["metrics"]["average_accuracy"]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {k: v for k, v in vars(args).items()},
        "arms": arms,
        "headline": {
            "static_avg_accuracy": static_acc,
            "cl_ewc_avg_accuracy": cl_acc,
            "lift_vs_static": round(cl_acc - static_acc, 4),
            "cl_ewc_bwt": arms[2]["metrics"]["backward_transfer"],
            "cl_no_ewc_bwt": arms[1]["metrics"]["backward_transfer"],
            "ewc_forgetting_reduction": round(
                arms[1]["metrics"]["forgetting"] - arms[2]["metrics"]["forgetting"], 4
            ),
        },
    }

    os.makedirs(args.out, exist_ok=True)
    json_path = os.path.join(args.out, "continual_eval.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    md_path = os.path.join(args.out, "continual_eval.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(_render_markdown(report))

    h = report["headline"]
    print(json.dumps(h, indent=2))
    print(f"\nWrote {json_path} and {md_path}")
    # Promotion gate: learned policy must beat static and not forget badly.
    ok = h["lift_vs_static"] >= 0 and h["cl_ewc_bwt"] >= -0.05
    print(f"PROMOTION GATE: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def _render_markdown(report: dict) -> str:
    h = report["headline"]
    lines = [
        "# AegisMem-CL Continual-Learning Evaluation",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "Task-incremental protocol: a single shared ranking policy is trained on a",
        "stream of tasks (each rewards a different retrieval signal) and evaluated on",
        "all tasks after each one. We report Average Accuracy (P@1), Backward Transfer",
        "(BWT; negative = forgetting), Forward Transfer (FWT), and Forgetting.",
        "",
        "## Headline",
        "",
        f"- Static (no learning) average P@1: **{h['static_avg_accuracy']}**",
        f"- AegisMem-CL (EWC) average P@1: **{h['cl_ewc_avg_accuracy']}**  "
        f"(lift vs static: **{h['lift_vs_static']:+}**)",
        f"- BWT with EWC: **{h['cl_ewc_bwt']:+}**  vs  without EWC: **{h['cl_no_ewc_bwt']:+}**",
        f"- Forgetting reduced by EWC: **{h['ewc_forgetting_reduction']:+}**",
        "",
        "## Per-arm metrics",
        "",
        "| Arm | Avg Acc | BWT | FWT | Forgetting |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for arm in report["arms"]:
        m = arm["metrics"]
        lines.append(
            f"| {arm['arm']} | {m['average_accuracy']} | {m['backward_transfer']:+} "
            f"| {m['forward_transfer']:+} | {m['forgetting']} |"
        )
    lines += [
        "",
        "Interpretation: the learned policy should beat the static baseline on average",
        "accuracy, and the EWC arm should show BWT >= the no-EWC arm — empirical evidence",
        "that anchoring mitigates catastrophic forgetting across the task stream.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
