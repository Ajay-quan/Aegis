"""Render bench-results/validation/*.json into bench/VALIDATION.md (python -m bench.report)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bench.stats import fmt

RES = Path("bench-results/validation")
OUT = Path(__file__).with_name("VALIDATION.md")
MODEL_ORDER = ("all-minilm", "nomic-embed-text", "mxbai-embed-large")


def _load(name: str) -> dict[str, Any] | None:
    p = RES / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def _pct(ci: dict[str, float]) -> str:
    return fmt(ci, pct=True)


def _delta(ci: dict[str, float]) -> str:
    return f"{ci['mean'] * 100:+.1f} pts [{ci['lo'] * 100:+.1f}, {ci['hi'] * 100:+.1f}]"


def recall_section(lines: list[str]) -> None:
    lines += ["## 1. Memory recall on real long-term conversations", "",
              "Full production pipeline (screening, guard, hybrid retrieval, ranking) vs. raw dense search and BM25",
              "over identical data and vectors. recall_all@5 = share of gold evidence turns in the top 5;",
              "session@5 = share of gold evidence sessions hit. Means with 95% bootstrap CIs over questions.", ""]
    for ds, label, role in (("longmemeval_s", "LongMemEval-S (MIT), held out: never used for tuning", "headline"),
                            ("locomo", "LoCoMo: the set hybrid weights were tuned on (reported for transparency)", "tuning")):
        lines += [f"### {label}", "",
                  "| Embedding model | Questions | AegisMem recall@5 | Dense recall@5 | BM25 recall@5 | AegisMem - dense | AegisMem session@5 | Benign turns quarantined |",
                  "|---|---|---|---|---|---|---|---|"]
        for m in MODEL_ORDER:
            r = _load(f"recall-{ds}-{m}")
            if not r:
                lines.append(f"| {m} | pending | | | | | | |")
                continue
            r = r["result"]
            o = r["overall"]
            q = r.get("quarantined", {})
            n = r.get("ingested", {})
            quar = f"{sum(q.values())} / {sum(n.values())}"
            lines.append(f"| {m} | {r['questions']} | {_pct(o['aegis']['recall_all@5'])} | {_pct(o['dense']['recall_all@5'])} "
                         f"| {_pct(o['bm25']['recall_all@5'])} | {_delta(r['aegis_vs_dense']['recall_all@5'])} "
                         f"| {_pct(o['aegis']['session@5'])} | {quar} |")
        best = next((_load(f"recall-{ds}-{m}") for m in reversed(MODEL_ORDER) if _load(f"recall-{ds}-{m}")), None)
        if best:
            bt = best["result"]["by_type"]
            lines += ["", f"By question type ({best['result'].get('dataset')}, largest available model), recall@5:", "",
                      "| Type | AegisMem | Dense | BM25 |", "|---|---|---|---|"]
            for t, d in bt.items():
                lines.append(f"| {t} (n={d['aegis']['recall_all@5']['n']}) | {_pct(d['aegis']['recall_all@5'])} "
                             f"| {_pct(d['dense']['recall_all@5'])} | {_pct(d['bm25']['recall_all@5'])} |")
        lines.append("")


def beir_section(lines: list[str]) -> None:
    lines += ["## 2. General retrieval (BEIR, CC BY-SA)", "",
              "nDCG@10 with 95% CIs. Published BM25 (Thakur et al. 2021) is a correctness check for our BM25.", "",
              "| Dataset | Model | Docs / queries | AegisMem | Dense | BM25 (ours) | BM25 (published) |",
              "|---|---|---|---|---|---|---|"]
    for ds in ("beir_scifact", "beir_nfcorpus", "beir_fiqa"):
        for m in MODEL_ORDER:
            r = _load(f"beir-{ds}-{m}")
            if not r:
                continue
            r = r["result"]
            o = r["overall"]
            lines.append(f"| {ds.removeprefix('beir_')} | {m} | {r['docs']} / {r['queries']} | {fmt(o['aegis']['ndcg@10'])} "
                         f"| {fmt(o['dense']['ndcg@10'])} | {fmt(o['bm25']['ndcg@10'])} | {r['published_bm25_ndcg10']} |")
    lines.append("")


def injection_section(lines: list[str]) -> None:
    r = _load("injection")
    lines += ["## 3. Write screening on real, held-out data", ""]
    if not r:
        lines += ["_pending_", ""]
        return
    r = r["result"]
    lines += [f"{r['real_data_seeds']['n_attacks']:,} attacks and {r['real_data_seeds']['n_benign']:,} harmless items, all disjoint from the seed corpus.", "",
              "| Configuration | Macro detection | Macro false alarm |", "|---|---|---|"]
    for k, label in (("rules_only", "Rules only"), ("old_handwritten_seeds", "Old 28 hand-written seeds"),
                     ("real_data_seeds", "Real-data seeds (current)")):
        lines.append(f"| {label} | {r[k]['macro_detection'] * 100:.1f}% | {r[k]['macro_false_alarm'] * 100:.2f}% |")
    cur = r["real_data_seeds"]
    lines += ["", "Current model, per source (95% CI):", "", "| Attack source | n | Detected |", "|---|---|---|"]
    for k, v in cur["detection"].items():
        lines.append(f"| {k} | {v['n']} | {_pct(v)} |")
    lines += ["", "| Harmless source | n | Falsely held |", "|---|---|---|"]
    for k, v in cur["false_alarm"].items():
        lines.append(f"| {k} | {v['n']} | {_pct(v)} |")
    sp = r.get("spml_caveat")
    if sp:
        lines += ["", f"SPML (caveat: labels chatbot policy misuse, broader than memory poisoning): detected "
                      f"{_pct(sp['detection']['spml'])}, falsely held {_pct(sp['false_alarm']['spml'])}."]
    lines.append("")


def learning_section(lines: list[str]) -> None:
    r = _load("learning")
    lines += ["## 4. Continual learning from reviewer decisions", ""]
    if not r:
        lines += ["_pending_", ""]
        return
    r = r["result"]
    lines += [f"{r['runs']} randomized runs per setting. Stream = attacks + {r['benign_ratio']}x harmless traffic; reviewers judge held",
              "items; a share of missed attacks is reported; agents use some harmless memories. Evaluated on *future*",
              f"attack texts never seen in the stream, and on {r['benign_eval_n']:,} separate harmless items.", "",
              "| Environment | Missed attacks reported | Detection before | Detection after | False alarms after | Reviews per 100 writes |",
              "|---|---|---|---|---|---|"]
    for env, d in r["environments"].items():
        for key in sorted(k for k in d if k.startswith("report_")):
            x = d[key]
            lines.append(f"| {env} (stream {d['stream_size']}, future {d['future_size']}) | {key.split('_')[1]}% "
                         f"| {_pct(x['detection_before'])} | {_pct(x['detection_after'])} | {_pct(x['false_alarm_after'])} "
                         f"| {x['reviews_per_100_writes']['mean']:.1f} |")
    lines.append("")


def integrity_section(lines: list[str]) -> None:
    r = _load("integrity")
    lines += ["## 5. Revocation and erasure at scale (built from real conversation turns)", ""]
    if not r:
        lines += ["_pending_", ""]
        return
    r = r["result"]
    rv, er = r["revocation"], r["erasure"]
    lines += [f"Revocation: {rv['cases']:,} cases, each queried with the revoked text itself. Leaks: **{rv['leaks_total']}**.", "",
              "| Scenario | Leak rate |", "|---|---|"]
    for k, v in rv["leak_rate"].items():
        lines.append(f"| {k} | {_pct(v)} (n={v['n']}) |")
    lines += ["", f"Stale index (canonical record superseded, vector index not yet updated): current version served "
                  f"{_pct(rv['stale_index_replacement_rate'])}.", "",
              f"Erasure: {er['subjects']:,} subjects, {er['items_expected']:,} linked items (prior versions, duplicates, "
              f"derived memories). Residue in any store: **{er['residue']}**; cascade recall {_pct(er['cascade_recall'])}; "
              f"collateral erasures {er['collateral_erasures']}; valid receipts {_pct(er['receipts_valid'])}.", ""]


def provenance_section(lines: list[str]) -> None:
    seen: dict[str, dict[str, Any]] = {}
    meta = None
    for p in sorted(RES.glob("*.json")):
        d = json.loads(p.read_text())
        meta = meta or d.get("meta")
        for ds in d.get("datasets", []):
            seen[ds["name"]] = ds
    lines += ["## Datasets and reproducibility", "",
              "| Dataset | License | Use | SHA-256 (prefix) | Citation |", "|---|---|---|---|---|"]
    for ds in sorted(seen.values(), key=lambda x: x["name"]):
        lines.append(f"| {ds['name']} | {ds['license']} | {ds['use']} | `{ds['sha256'][:12]}` | {ds['citation']} |")
    if meta:
        lines += ["", f"Run: AegisMem {meta['version']} at `{meta['git_sha']}`, Python {meta['python']}, {meta['cpu']}. "
                      "Embeddings: local Ollama models. Reproduce: `python -m bench.validate && python -m bench.report`."]
    lines.append("")


def main() -> None:
    lines = ["# AegisMem validation report", "",
             "Every number below comes from public, human-made datasets, evaluated on data never used for seeding or",
             "tuning (except LoCoMo, labelled as the tuning set). All figures carry 95% bootstrap confidence intervals.",
             "Generated by `python -m bench.report` from `bench-results/validation/`.", ""]
    for section in (recall_section, beir_section, injection_section, learning_section, integrity_section,
                    provenance_section):
        section(lines)
    lines += ["## Known limitations (stated, not hidden)", "",
              "- Cold-start screening catches classic jailbreaks but most *novel* indirect injections only after a deployment",
              "  learns from reviewer feedback (section 4). BIPIA-style task hijacks are undetectable from content alone at cold start.",
              "- Embeddings are small local models; larger hosted models typically raise absolute recall for all systems.",
              "- LoCoMo and BIPIA have no asserted license: used for internal evaluation only, never redistributed.", ""]
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
