"""Answer-level (outcome) evaluation on LongMemEval-S with open local models.

Does the memory layer make an agent *answer correctly*? For every question a reader model answers
from the memories each arm provides, and a different judge model grades the answer:

    no_memory   question only (lower bound)
    oracle      the gold evidence sessions, in full (LongMemEval's oracle setting; upper bound)
    bm25        top-k turns by BM25
    dense       top-k turns by raw vector search
    aegis       top-k turns from the full AegisMem retrieval pipeline

Prompts are LongMemEval's official ones, copied verbatim (MIT, Wu et al. 2024,
github.com/xiaowu0162/LongMemEval: src/generation/run_generation.py, src/evaluation/evaluate_qa.py).
Reader and judge are different model families to limit self-preference bias. Deterministic
exact-match / token-F1 are reported too, so results do not rest on an LLM judge alone.

Split (pre-registered, fixed before any tuning): dev = sha256(question_id) first byte even.
All method changes are tuned on dev only; test is reported once per release.

All model calls are cached in SQLite, so runs resume after interruption.

    python -m bench.answer_eval --split dev --phase generate
    python -m bench.answer_eval --split dev --phase judge
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sqlite3
import string
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

from bench import sources
from bench.stats import mean_ci, paired_diff_ci

OLLAMA = "http://localhost:11434/api/chat"
CACHE = Path.home() / ".cache/aegis-bench/llm.sqlite"
OUT = Path("bench-results/validation")
ARMS = ("no_memory", "oracle", "bm25", "dense", "aegis", "bm25_ctx", "aegis_ctx")
# *_ctx: same retrieved turns and official prompt; history rendered by the product's time-aware
# renderer (domain.memory.context) instead of LongMemEval's session format. Isolates presentation.
TOPK = 10
CONTEXT_CHARS = 100000  # ~27k tokens; fits qwen2.5 32k context. Sessions are never dropped.

# --- Official LongMemEval prompts (verbatim) ---------------------------------------------------
READER_NO_MEMORY = "{}"
READER = ("I will give you several history chats between you and a user. Please answer the question based on the "
          "relevant chat history.\n\n\nHistory Chats:\n\n{}\n\nCurrent Date: {}\nQuestion: {}\nAnswer:")
_J = ("I will give you a question, a correct answer, and a response from a model. Please answer yes if the response "
      "contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or "
      "contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only "
      "contains a subset of the information required by the answer, answer no. ")
JUDGE = {
    "default": _J + "\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only.",
    "temporal-reasoning": _J + "In addition, do not penalize off-by-one errors for the number of days. If the question "
        "asks for the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days "
        "when the answer is 18), the model's response is still correct. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel "
        "Response: {}\n\nIs the model response correct? Answer yes or no only.",
    "knowledge-update": "I will give you a question, a correct answer, and a response from a model. Please answer yes if "
        "the response contains the correct answer. Otherwise, answer no. If the response contains some previous "
        "information along with an updated answer, the response should be considered as correct as long as the updated "
        "answer is the required answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model "
        "response correct? Answer yes or no only.",
    "single-session-preference": "I will give you a question, a rubric for desired personalized response, and a "
        "response from a model. Please answer yes if the response satisfies the desired response. Otherwise, answer no. "
        "The model does not need to reflect all the points in the rubric. The response is correct as long as it recalls "
        "and utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\n"
        "Is the model response correct? Answer yes or no only.",
    "abstention": "I will give you an unanswerable question, an explanation, and a response from a model. Please answer "
        "yes if the model correctly identifies the question as unanswerable. The model could say that the information is "
        "incomplete, or some other information is given but the asked information is not.\n\nQuestion: {}\n\n"
        "Explanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the question as unanswerable? "
        "Answer yes or no only.",
}


def split_of(qid: str) -> str:
    return "dev" if hashlib.sha256(qid.encode()).digest()[0] % 2 == 0 else "test"


# --- Cached local model calls ------------------------------------------------------------------
class LLMCache:
    def __init__(self, path: Path = CACHE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, v TEXT)")

    async def chat(self, client: httpx.AsyncClient, model: str, prompt: str, num_predict: int) -> str:
        key = hashlib.sha256(f"{model}\x00{num_predict}\x00{prompt}".encode()).hexdigest()
        row = self.db.execute("SELECT v FROM c WHERE k=?", (key,)).fetchone()
        if row:
            return row[0]
        body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False, "think": False,
                "options": {"temperature": 0, "seed": 0, "num_ctx": 32768, "num_predict": num_predict}}
        r = await client.post(OLLAMA, json=body, timeout=600)
        r.raise_for_status()  # failures are loud; never substitute an answer
        text = r.json()["message"]["content"].strip()
        if not text:  # e.g. a thinking model spent its budget on hidden reasoning: fail, never score it
            raise RuntimeError(f"{model} returned empty output")
        self.db.execute("INSERT OR REPLACE INTO c VALUES (?,?)", (key, text))
        self.db.commit()
        return text


# --- Deterministic metrics (SQuAD-style normalisation) -----------------------------------------
def _norm(s: str) -> list[str]:
    s = s.lower()
    s = "".join(ch for ch in s if ch not in string.punctuation)
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return s.split()


def contains_em(pred: str, gold: str) -> float:
    g = " ".join(_norm(gold))
    return float(bool(g) and g in " ".join(_norm(pred)))


def token_f1(pred: str, gold: str) -> float:
    p, g = _norm(pred), _norm(gold)
    common = Counter(p) & Counter(g)
    same = sum(common.values())
    if not same:
        return 0.0
    pr, rc = same / len(p), same / len(g)
    return 2 * pr * rc / (pr + rc)


# --- Context construction per arm --------------------------------------------------------------
def _fit(turns: list[dict[str, str]], budget: int = CONTEXT_CHARS) -> dict[int, int]:
    """Per-turn char caps so the total fits: only the longest turns are shortened, none dropped."""
    lens = [len(t["content"]) for t in turns]
    if sum(lens) <= budget:
        return {i: n for i, n in enumerate(lens)}
    lo, hi = 0, max(lens)
    while lo < hi:  # largest cap c with sum(min(len, c)) <= budget
        c = (lo + hi + 1) // 2
        lo, hi = (c, hi) if sum(min(n, c) for n in lens) <= budget else (lo, c - 1)
    return {i: min(n, lo) for i, n in enumerate(lens)}


def format_turns(turns: list[dict[str, str]]) -> str:
    """Chronological, grouped by session, in LongMemEval's json-ish history style."""
    turns = sorted(turns, key=lambda t: (t["date"], t["sid"], t["idx"]))
    caps = _fit(turns)
    by_sess: dict[tuple[str, str], list[dict[str, str]]] = {}
    for i, t in enumerate(turns):
        c = t["content"] if caps[i] >= len(t["content"]) else t["content"][:caps[i]] + " ..."
        by_sess.setdefault((t["date"], t["sid"]), []).append({**t, "content": c})
    blocks = []
    for i, ((date, _), ts) in enumerate(by_sess.items(), 1):
        body = "\n".join(json.dumps({"role": t["role"], "content": t["content"]}) for t in ts)
        blocks.append(f"### Session {i}:\nSession Date: {date}\nSession Content:\n{body}")
    return "\n\n".join(blocks)


async def retrieve_contexts(q: dict[str, Any], embed: Any) -> dict[str, list[dict[str, str]]]:
    from bench.harness import build_env, use_embedding
    from core.schemas.memory import RetrievalQuery, SourceType
    from domain.memory.lexical import BM25Index
    from bench.memory_recall import lme_time

    turns = []
    for sid, date, sess in zip(q["haystack_session_ids"], q["haystack_dates"], q["haystack_sessions"]):
        for i, t in enumerate(sess):
            turns.append({"tid": f"{sid}:{i}", "sid": sid, "idx": i, "date": date, "role": t["role"],
                          "content": t["content"], "text": f"[{date}] {t['role']}: {t['content']}"})
    by_tid = {t["tid"]: t for t in turns}
    env = await build_env(dim=embed.dimension)
    use_embedding(env, embed)
    await embed.prefill([t["text"] for t in turns] + [q["question"]])
    user = f"qa-{q['question_id']}"
    mem_to_tid = {}
    for t in turns:
        src = SourceType.USER_MESSAGE if t["role"] == "user" else SourceType.AGENT_OBSERVATION
        m = await env.ingest.ingest_text(t["text"], user_id=user, source_type=src, event_time=lme_time(t["date"]))
        mem_to_tid[m.memory_id] = t["tid"]
    r = await env.retrieve.retrieve(RetrievalQuery(query_text=q["question"], user_id=user, top_k=TOPK))
    aegis = [mem_to_tid[c.memory.memory_id] for c in r.candidates if c.memory.memory_id in mem_to_tid]
    qv = await embed.embed_single(q["question"])
    dense = [mem_to_tid[h.id] for h in await env.raw_vs.search(qv, top_k=TOPK, filter={"user_id": user})
             if h.id in mem_to_tid]
    lexical = [tid for tid, _ in BM25Index.build([(t["tid"], t["text"]) for t in turns]).search(q["question"], top_k=TOPK)]
    gold = set(q["answer_session_ids"])
    return {"oracle": [t for t in turns if t["sid"] in gold],
            "bm25": [by_tid[x] for x in lexical], "dense": [by_tid[x] for x in dense],
            "aegis": [by_tid[x] for x in aegis]}


def render_product(turns: list[dict[str, str]]) -> str:
    from bench.memory_recall import lme_time
    from domain.memory.context import render_entries
    caps = _fit(turns)
    return render_entries([(lme_time(t["date"]), f"{t['role']}: {t['content'][:caps[i]]}")
                           for i, t in enumerate(turns)])


def reader_prompt(arm: str, q: dict[str, Any], ctx: list[dict[str, str]] | None) -> str:
    if arm == "no_memory":
        return READER_NO_MEMORY.format(q["question"])
    if arm.endswith("_ctx"):
        return READER.format(render_product(ctx or []), q["question_date"], q["question"])
    return READER.format(format_turns(ctx or []), q["question_date"], q["question"])


def parse_verdict(v: str) -> float:
    """Strict: the reply must start with yes or no. Anything else is an error, not a 'no'."""
    w = re.sub(r"[^a-z]", " ", v.lower()).split()
    if w and w[0] in ("yes", "no"):
        return float(w[0] == "yes")
    raise ValueError(f"unparseable judge verdict: {v!r}")


def judge_prompt(q: dict[str, Any], response: str) -> str:
    if q["question_id"].endswith("_abs"):
        tpl = JUDGE["abstention"]
    else:
        tpl = JUDGE.get(q["question_type"], JUDGE["default"])
    return tpl.format(q["question"], q["answer"], response)


# --- Phases ------------------------------------------------------------------------------------
def questions(split: str, limit: int | None) -> list[dict[str, Any]]:
    qs = [q for q in sources.load_json("longmemeval_s") if split == "all" or split_of(q["question_id"]) == split]
    qs.sort(key=lambda q: hashlib.sha256(q["question_id"].encode()).hexdigest())  # stable, type-mixed order
    return qs[:limit]


def _path(split: str, reader: str, embed_model: str) -> Path:
    return OUT / f"qa-{split}-{reader.replace(':', '_')}-{embed_model}.jsonl"


async def generate(split: str, reader: str, embed_model: str, limit: int | None) -> None:
    from bench.embedcache import CachedEmbedding
    from bench.validate import MODELS
    embed = CachedEmbedding(embed_model, MODELS[embed_model])
    cache = LLMCache()
    path = _path(split, reader, embed_model)
    done = {json.loads(l)["qid"] for l in path.open()} if path.exists() else set()
    qs = [q for q in questions(split, limit) if q["question_id"] not in done]
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    async with httpx.AsyncClient() as client:
        for i, q in enumerate(qs, 1):
            ctxs = await retrieve_contexts(q, embed)
            rec: dict[str, Any] = {"qid": q["question_id"], "qtype": q["question_type"],
                                   "abstention": q["question_id"].endswith("_abs"), "answer": str(q["answer"]),
                                   "gold_sessions": q["answer_session_ids"], "arms": {}}
            for arm in ARMS:
                ctx = ctxs.get(arm.removesuffix("_ctx"))
                resp = await cache.chat(client, reader, reader_prompt(arm, q, ctx), num_predict=400)
                rec["arms"][arm] = {"response": resp,
                                    "ctx_tids": [t["tid"] for t in ctx] if ctx and arm != "oracle" else None,
                                    "gold_session_in_ctx": (bool({t["sid"] for t in ctx} & set(q["answer_session_ids"]))
                                                            if ctx else False)}
            with path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            el = time.time() - t0
            print(f"  generated {i}/{len(qs)}  {el / 60:.1f} min, eta {el / i * (len(qs) - i) / 60:.1f} min", flush=True)
            if i % 25 == 0:
                embed.evict()


async def judge(split: str, reader: str, embed_model: str, judge_model: str) -> dict[str, Any]:
    cache = LLMCache()
    qmap = {q["question_id"]: q for q in sources.load_json("longmemeval_s")}
    recs = [json.loads(l) for l in _path(split, reader, embed_model).open()]
    rows: dict[str, list[dict[str, Any]]] = {a: [] for a in ARMS}
    async with httpx.AsyncClient() as client:
        for i, rec in enumerate(recs, 1):
            q = qmap[rec["qid"]]
            for arm in ARMS:
                resp = rec["arms"][arm]["response"]
                verdict = await cache.chat(client, judge_model, judge_prompt(q, resp), num_predict=16)
                rows[arm].append({"qid": rec["qid"], "qtype": "abstention" if rec["abstention"] else rec["qtype"],
                                  "judge": parse_verdict(verdict),
                                  "em": contains_em(resp, rec["answer"]), "f1": token_f1(resp, rec["answer"]),
                                  "gold_in_ctx": float(rec["arms"][arm]["gold_session_in_ctx"])})
            if i % 25 == 0:
                print(f"  judged {i}/{len(recs)}", flush=True)
    out: dict[str, Any] = {"split": split, "reader": reader, "judge": judge_model, "embedding": embed_model,
                           "top_k_turns": TOPK, "questions": len(recs), "overall": {}, "by_type": {}, "paired": {}}
    for arm in ARMS:
        out["overall"][arm] = {m: mean_ci([r[m] for r in rows[arm]]) for m in ("judge", "em", "f1", "gold_in_ctx")}
    for a, b in (("aegis", "bm25"), ("aegis", "dense"), ("aegis", "no_memory"), ("oracle", "aegis"),
                 ("aegis_ctx", "aegis"), ("bm25_ctx", "bm25")):
        out["paired"][f"{a}-{b}"] = paired_diff_ci([r["judge"] for r in rows[a]], [r["judge"] for r in rows[b]])
    for t in sorted({r["qtype"] for r in rows["aegis"]}):
        out["by_type"][t] = {arm: mean_ci([r["judge"] for r in rows[arm] if r["qtype"] == t]) for arm in ARMS}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="bench.answer_eval")
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--phase", choices=["generate", "judge"], required=True)
    ap.add_argument("--reader", default="qwen2.5:7b-instruct")
    ap.add_argument("--judge", default="gemma4:latest")
    ap.add_argument("--embedding", default="all-minilm")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    logging.disable(logging.WARNING)
    if a.phase == "generate":
        asyncio.run(generate(a.split, a.reader, a.embedding, a.limit))
    else:
        res = asyncio.run(judge(a.split, a.reader, a.embedding, a.judge))
        name = f"qa-{a.split}-{a.reader.replace(':', '_')}-{a.embedding}"
        (OUT / f"{name}.json").write_text(json.dumps({"datasets": sources.manifest(["longmemeval_s"]),
                                                      "result": res}, indent=2))
        print(json.dumps({k: v for k, v in res.items() if k in ("overall", "paired")}, indent=1))


if __name__ == "__main__":
    main()
