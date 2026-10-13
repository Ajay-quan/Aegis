"""Revocation and erasure at scale, built procedurally from real conversation turns (no generated text).

Revocation (per case, inside realistic histories of real distractor turns):
    corrected   a real fact is corrected via the outcomes API with another real turn as replacement
    expired     a real fact gets a validity window that has passed
    erased      a real fact is erased via /forget
  Every case is queried with the *old* text itself (the strongest possible match). Leak = the revoked
  memory is served; replacement = the correction is served instead (corrected cases).

Erasure (per subject): a real fact with a prior version (real text), an exact duplicate, a derived
reflection (real text, linked by derivation ids), and an unrelated memory that must survive.
Measured on the raw stores after /forget: residue in relational/vector/graph, cascade recall,
collateral erasures, receipt validity.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from core.schemas.memory import MemoryItem, MemoryType, RetrievalQuery, SourceType

from bench import sources
from bench.harness import build_env, use_embedding
from bench.stats import proportion_ci


def real_turns(n: int, seed: int = 0, min_chars: int = 40, max_chars: int = 600) -> list[str]:
    seen: set[str] = set()
    pool = []
    for q in sources.load_json("longmemeval_s"):
        for sess in q["haystack_sessions"]:
            for t in sess:
                c = t["content"].strip()
                if t["role"] == "user" and min_chars <= len(c) <= max_chars and c not in seen:
                    seen.add(c)
                    pool.append(c)
    random.Random(seed).shuffle(pool)
    if len(pool) < n:
        raise ValueError(f"need {n} turns, have {len(pool)}")
    return pool[:n]


async def revocation(embed: Any, cases_per_kind: int = 1000, per_user: int = 20, distractors: int = 60,
                     seed: int = 0) -> dict[str, Any]:
    kinds = ("corrected", "stale_index", "expired", "erased")
    need = len(kinds) * cases_per_kind * 2 + (len(kinds) * cases_per_kind // per_user + 1) * distractors
    texts = iter(real_turns(need, seed))
    await embed.prefill(real_turns(need, seed))
    leaks = {k: 0 for k in kinds}
    replaced = 0
    t0 = time.time()
    total = {k: 0 for k in kinds}
    for start in range(0, cases_per_kind * len(kinds), per_user):
        env = await build_env(dim=embed.dimension)
        use_embedding(env, embed)
        user = f"rev-{start}"
        for _ in range(distractors):
            await env.ingest.ingest_text(next(texts), user_id=user)
        cases = []
        for j in range(per_user):
            kind = kinds[(start + j) % len(kinds)]
            old = await env.ingest.ingest_text(next(texts), user_id=user)
            new_text = next(texts)
            replacement = None
            if kind == "corrected":
                out = await env.outcomes.correct(user, old.memory_id, "outdated", corrected_text=new_text)
                replacement = out["replacement_memory_id"]
            elif kind == "stale_index":
                # Superseded in the canonical store while the vector index still says "active"
                # (e.g. an index write that has not been repaired yet): the guard must swap in the
                # current version even though the old one is the best vector match.
                new = await env.ingest.ingest_text(new_text, user_id=user)
                old.status, old.metadata["superseded_by"] = "superseded", new.memory_id
                await env.raw_db.update_memory(old)
                replacement = new.memory_id
            elif kind == "expired":
                old.valid_to = datetime.now(timezone.utc) - timedelta(days=1)
                await env.db.update_memory(old)
            else:
                await env.erase.forget(user_id=user, memory_ids=[old.memory_id], include_duplicates=False)
            cases.append((kind, old, replacement))
        for kind, old, replacement in cases:
            r = await env.retrieve.retrieve(RetrievalQuery(query_text=old.content, user_id=user, top_k=10))
            served = {c.memory.memory_id for c in r.candidates}
            total[kind] += 1
            leaks[kind] += old.memory_id in served
            if kind == "stale_index":
                replaced += replacement in served
    return {
        "cases": sum(total.values()), "seconds": round(time.time() - t0, 1),
        "leak_rate": {k: proportion_ci(leaks[k], total[k]) for k in kinds},
        "leaks_total": sum(leaks.values()),
        # Only meaningful where the old memory is still a candidate (stale index): the guard must
        # substitute its successor. (For synced corrections the old one is simply never a candidate.)
        "stale_index_replacement_rate": proportion_ci(replaced, total["stale_index"]),
    }


async def erasure(embed: Any, subjects: int = 1000, per_user: int = 25, seed: int = 1) -> dict[str, Any]:
    texts = real_turns(subjects * 5, seed)
    await embed.prefill(texts)
    it = iter(texts)
    residue = cascade_hit = cascade_total = collateral = valid = 0
    t0 = time.time()
    for start in range(0, subjects, per_user):
        env = await build_env(dim=embed.dimension)
        use_embedding(env, embed)
        user = f"del-{start}"
        plan = []
        for _ in range(min(per_user, subjects - start)):
            v1 = await env.ingest.ingest_text(next(it), user_id=user)
            v2_text = next(it)
            v2 = MemoryItem(namespace=f"user:{user}", user_id=user, content=v2_text,
                            parent_memory_ids=[v1.memory_id], version=2)
            await env.db.save_memory(v2)
            await env.vs.upsert(v2.memory_id, await embed.embed_single(v2_text),
                                {"user_id": user, "status": "active"})
            dup = await env.ingest.ingest_text(v2_text, user_id=user)
            refl = await env.ingest.ingest_text(next(it), user_id=user, memory_type=MemoryType.REFLECTION,
                                                source_type=SourceType.REFLECTION,
                                                metadata={"derivation_ids": [v2.memory_id]})
            keep = await env.ingest.ingest_text(next(it), user_id=user)
            plan.append((v2.memory_id, {v1.memory_id, v2.memory_id, dup.memory_id, refl.memory_id}, keep.memory_id))
        for seed_id, expected, keep_id in plan:
            r = await env.erase.forget(user_id=user, memory_ids=[seed_id], reason="bench")
            got = {e["memory_id"] for e in r["body"]["erased"]}
            cascade_total += len(expected)
            cascade_hit += len(expected & got)
            valid += int(env.erase.verify_receipt(r) and r["body"]["verified"])
            for mid in expected:
                residue += int(mid in env.raw_db._memories) + int(await env.raw_vs.get(mid) is not None) \
                    + int(await env.graph.has_memory_node(mid))
            collateral += int(keep_id not in env.raw_db._memories)
    return {
        "subjects": subjects, "items_expected": cascade_total, "seconds": round(time.time() - t0, 1),
        "residue": residue, "cascade_recall": proportion_ci(cascade_hit, cascade_total),
        "collateral_erasures": collateral, "receipts_valid": proportion_ci(valid, subjects),
    }
