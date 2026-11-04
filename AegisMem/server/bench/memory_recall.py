"""Memory-recall evaluation on real long-term conversation benchmarks (LongMemEval, LoCoMo).

Every turn goes through the *production* ingest pipeline (redaction, provenance, trust, rule and
risk-model screening, embedding, indexing). User turns are ingested as ``user_message``; assistant
turns as ``agent_observation``. Three systems are compared on identical data and vectors:

    aegis   full retrieval: dense + BM25 (RRF) -> integrity guard -> learned ranking
    dense   raw vector search over the same index (no AegisMem logic)
    bm25    BM25 over the same turns

Metrics per question (abstention questions excluded):
    recall_all@k   share of gold evidence turns in the top k
    hit@k          at least one gold evidence turn in the top k
    session@k      share of gold evidence sessions with at least one turn in the top k
Reported as means with 95% bootstrap CIs, by question type, plus paired aegis-minus-dense deltas.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.schemas.memory import RetrievalQuery, SourceType
from domain.memory.lexical import BM25Index

from bench import sources
from bench.harness import build_env, use_embedding
from bench.stats import mean_ci, paired_diff_ci

KS = (1, 3, 5, 10)
SYSTEMS = ("aegis", "dense", "bm25")


@dataclass
class Turn:
    turn_id: str
    session_id: str
    role: str
    text: str
    when: datetime | None = None  # real conversation time, sent as event_time like a live integration


@dataclass
class Question:
    qid: str
    qtype: str
    text: str
    evidence_turns: set[str]
    evidence_sessions: set[str]


@dataclass
class Corpus:
    """One memory owner (user) with a history and the questions asked over it."""
    key: str
    turns: list[Turn]
    questions: list[Question] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Dataset adapters
# ---------------------------------------------------------------------------

def lme_time(date: str) -> datetime:
    """LongMemEval dates look like '2023/05/20 (Sat) 02:21'."""
    d, _, hm = date.split(" ")
    return datetime.strptime(f"{d} {hm}", "%Y/%m/%d %H:%M").replace(tzinfo=timezone.utc)


def longmemeval(limit: int | None = None) -> list[Corpus]:
    data = sources.load_json("longmemeval_s")
    out = []
    for q in data:
        if q["question_id"].endswith("_abs"):
            continue  # abstention: no evidence to retrieve
        turns, ev_turns = [], set()
        for sid, date, sess in zip(q["haystack_session_ids"], q["haystack_dates"], q["haystack_sessions"]):
            for i, t in enumerate(sess):
                tid = f"{sid}:{i}"
                turns.append(Turn(tid, sid, t["role"], f"[{date}] {t['role']}: {t['content']}", lme_time(date)))
                if t.get("has_answer"):
                    ev_turns.add(tid)
        ev_sessions = set(q["answer_session_ids"])
        if not ev_turns:  # fall back to session-level evidence only
            ev_turns = {t.turn_id for t in turns if t.session_id in ev_sessions}
        out.append(Corpus(q["question_id"], turns, [Question(
            q["question_id"], q["question_type"], q["question"], ev_turns, ev_sessions)]))
        if limit and len(out) >= limit:
            break
    return out


def locomo(limit: int | None = None) -> list[Corpus]:
    out = []
    names = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop"}
    for sample in sources.load_json("locomo")[:limit]:
        conv = sample["conversation"]
        turns = []
        for key, val in conv.items():
            if key.startswith("session_") and isinstance(val, list):
                date = conv.get(f"{key}_date_time", "")
                for t in val:
                    turns.append(Turn(t["dia_id"], key, t["speaker"], f"[{date}] {t['speaker']}: {t['text']}"))
        sess_of = {t.turn_id: t.session_id for t in turns}
        qs = [Question(f"{sample['sample_id']}:{i}", names.get(q["category"], str(q["category"])), q["question"],
                       set(q["evidence"]), {sess_of[e] for e in q["evidence"] if e in sess_of})
              for i, q in enumerate(sample["qa"]) if q.get("category") in names and q.get("evidence")]
        out.append(Corpus(sample["sample_id"], turns, qs))
    return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _scores(ranked: list[str], q: Question, sess_of: dict[str, str]) -> dict[str, float]:
    out = {}
    for k in KS:
        top = ranked[:k]
        got = q.evidence_turns & set(top)
        out[f"recall_all@{k}"] = len(got) / len(q.evidence_turns)
        out[f"hit@{k}"] = 1.0 if got else 0.0
        sess = {sess_of[t] for t in top if t in sess_of}
        out[f"session@{k}"] = len(q.evidence_sessions & sess) / max(len(q.evidence_sessions), 1)
    return out


async def run(corpora: Iterable[Corpus], embed: Any, dataset: str, progress_every: int = 25) -> dict[str, Any]:
    corpora = list(corpora)
    per_q: dict[str, list[dict[str, Any]]] = {s: [] for s in SYSTEMS}
    quarantined = defaultdict(int)
    ingested = defaultdict(int)
    t0 = time.time()
    kmax = max(KS)

    for ci, corpus in enumerate(corpora, 1):
        env = await build_env(dim=embed.dimension)
        use_embedding(env, embed)
        await embed.prefill([t.text for t in corpus.turns] + [q.text for q in corpus.questions])
        user = f"u-{corpus.key}"
        mem_to_turn: dict[str, str] = {}
        sess_of = {t.turn_id: t.session_id for t in corpus.turns}
        for t in corpus.turns:
            src = SourceType.USER_MESSAGE if t.role == "user" or t.role not in ("assistant",) else SourceType.AGENT_OBSERVATION
            m = await env.ingest.ingest_text(t.text, user_id=user, source_type=src, event_time=t.when)
            mem_to_turn[m.memory_id] = t.turn_id
            ingested[t.role if t.role in ("user", "assistant") else "speaker"] += 1
            if m.status == "pending":
                quarantined[t.role if t.role in ("user", "assistant") else "speaker"] += 1
        bm25 = BM25Index.build([(t.turn_id, t.text) for t in corpus.turns])

        for q in corpus.questions:
            r = await env.retrieve.retrieve(RetrievalQuery(query_text=q.text, user_id=user, top_k=kmax))
            aegis = [mem_to_turn.get(c.memory.memory_id, "") for c in r.candidates]
            qv = await embed.embed_single(q.text)
            dense = [mem_to_turn.get(h.id, "") for h in
                     await env.raw_vs.search(qv, top_k=kmax, filter={"user_id": user})]
            lexical = [tid for tid, _ in bm25.search(q.text, top_k=kmax)]
            for name, ranked in (("aegis", aegis), ("dense", dense), ("bm25", lexical)):
                per_q[name].append({"qid": q.qid, "qtype": q.qtype, **_scores(ranked, q, sess_of)})
        if progress_every and (ci % progress_every == 0 or ci == len(corpora)):
            el = time.time() - t0
            print(f"  [{dataset}] {ci}/{len(corpora)} corpora, {len(per_q['aegis'])} questions, "
                  f"{el / 60:.1f} min elapsed, eta {el / ci * (len(corpora) - ci) / 60:.1f} min", flush=True)
        if hasattr(embed, "evict") and ci % 50 == 0:
            embed.evict()

    return summarize(per_q, dataset, {"ingested": dict(ingested), "quarantined": dict(quarantined),
                                      "corpora": len(corpora), "seconds": round(time.time() - t0, 1)})


def summarize(per_q: dict[str, list[dict[str, Any]]], dataset: str, extra: dict[str, Any]) -> dict[str, Any]:
    metrics = [m for m in per_q["aegis"][0] if m not in ("qid", "qtype")] if per_q["aegis"] else []
    out: dict[str, Any] = {"dataset": dataset, "questions": len(per_q["aegis"]), **extra,
                           "overall": {}, "by_type": {}, "aegis_vs_dense": {}, "aegis_vs_bm25": {}}
    for s in SYSTEMS:
        out["overall"][s] = {m: mean_ci([r[m] for r in per_q[s]]) for m in metrics}
    for m in metrics:
        out["aegis_vs_dense"][m] = paired_diff_ci([r[m] for r in per_q["aegis"]], [r[m] for r in per_q["dense"]])
        out["aegis_vs_bm25"][m] = paired_diff_ci([r[m] for r in per_q["aegis"]], [r[m] for r in per_q["bm25"]])
    for qtype in sorted({r["qtype"] for r in per_q["aegis"]}):
        out["by_type"][qtype] = {s: {m: mean_ci([r[m] for r in per_q[s] if r["qtype"] == qtype])
                                     for m in ("recall_all@5", "hit@5", "session@5")} for s in SYSTEMS}
    q = extra.get("quarantined", {})
    n = extra.get("ingested", {})
    out["benign_quarantine_rate"] = {role: q.get(role, 0) / n[role] for role in n}
    return out
