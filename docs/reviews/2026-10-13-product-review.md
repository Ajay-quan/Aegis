# AegisMem: evidence-based product review

Date: 2026-10-13 · Commit reviewed: `c4ccec0` (branch `validation/benchmarks`, based on `main` @ `3232415`) · Reviewer: Claude (AI agent)

**Conflict of interest:** I wrote most of this code. To avoid reviewing from memory, every material claim below was
re-verified against the code (file:line) or against results reproduced in this review. Where I could not verify, I say so.

---

## A. Executive assessment

**What AegisMem is today:** a FastAPI service plus SDKs that stores an agent's memories and returns ranked, filtered
memories (or a token-budgeted "handoff" briefing) on request. On every write it records provenance and screens content
for prompt injection. On every read it re-checks each candidate against the canonical record (superseded, expired,
quarantined, erased, wrong tenant). It also performs cascading, verifiable deletion. It contains **no base model, no
agent loop and no answer generation**. It is a memory layer that other agents call.

**What demonstrably works (reproduced in this review):**

1. **Isolation, deletion and revocation mechanics.**
   - **0 leaks in 4,000 revocation cases** built from real text, and 1,000/1,000 stale-index cases served the current version.
   - **0 residue across 2,000 erasure subjects (8,000 linked items)**, with 100% cascade.
   - Postgres row-level security enforced in a deployed database.
   - Isolation, auth, idempotency and repair outbox verified on real Postgres, Redis and Qdrant, and in a Kubernetes install.
2. **Retrieval clearly better than raw vector search** on held-out LongMemEval: recall@5 **0.640 vs 0.539**
   (+10.1 pts, 95% CI +7.3 to +12.8; n=470).
3. **Low false-alarm write screening:** 0.03% of 86,138 real harmless items held.
4. **Feedback-driven improvement of attack screening in simulation:** 17.6% → ~95% (InjecAgent) and 0% → 66–76% (BIPIA)
   on attacks never seen, over 50 runs.

**What remains unproven:**

1. **Whether memory improves an agent's actual answers.** No outcome-level evaluation exists. Every recall number is a
   retrieval proxy.
2. **The flagship "current facts" claim.** On LongMemEval *knowledge-update* questions, AegisMem retrieves the evidence
   **worse than plain BM25** (0.620 vs 0.815, n=72). Nothing detects updates automatically at ingest.
3. **The LLM-dependent features** (contradiction detection, reflection, LLM-judged updates). They are never evaluated
   with a real model, and production silently substitutes a mock LLM when none is configured.
4. **Two of the three continual-learning loops** (ranking weights, source trust). They have no evidence of benefit on
   real data.
5. **Any user value.** There are no users and no design partners.

**Maturity stage:** a **technical prototype with production-grade infrastructure**. The plumbing (tenancy, RLS,
migrations, Helm, SDKs, CI) is ahead of the product evidence. It is a credible *usable alpha* for one narrow scope:
a multi-tenant memory API with verifiable deletion and revocation-safe reads. The broader "trust layer that learns" is not
yet demonstrated.

**The most important next decision:** define success at the level of **agent outcomes**, and build the evaluation that
measures it, before adding any Q2 features.

---

## B. Product intent versus implemented reality

| Claim (README, ROADMAP, CHANGELOG) | Implementation | Evidence | Verdict |
|---|---|---|---|
| Revoked or updated facts are never served | Read-time guard `services/guard_service.py`; successor substitution; status sync and outbox | 0 leaks in 4,000 real-text cases (`bench/integrity_scale.py`); stale-index substitution 1,000/1,000 | **Demonstrated, for explicitly revoked facts** |
| Knows "what changed" | Updates only via explicit `/corrections`, `/update` (LLM) or `/contradictions/scan` (LLM). Ingest does no change detection (`services/ingest_service.py`: no contradiction call) | Knowledge-update recall@5 0.620 vs BM25 0.815 | **Partially implemented; underperforms when changes are not declared** |
| Provable erasure (GDPR) | `services/erasure_service.py` closure, purge, re-verify, HMAC receipt | 2,000 subjects / 8,000 items: 0 residue, 100% cascade, 0 collateral (in-memory stores); purge verified on Postgres earlier | **Demonstrated (backups excluded, as the receipt states)** |
| Poisoning resistance | Rules plus online risk model, trust-scaled thresholds, quarantine | Cold start: Gandalf 93.7%, InjecAgent 16.7%, BIPIA 0%; false alarms 0.03% | **Partial: strong on jailbreaks, weak on novel indirect injection until trained** |
| Learns from human decisions | Risk model, trust calibrator, ranking learner, event-sourced (`services/learning_runtime.py`) | Risk model: simulated gains (oracle reviewers). Trust and ranking: unit tests only | **Partially demonstrated** |
| EWC "no catastrophic forgetting" (CHANGELOG 0.3.0) | `domain/learning/online_scorer.py`, **not wired** into retrieval (only a settings flag) | `scripts/continual_eval.py` uses random synthetic feature vectors | **Aspirational; the claim is not supported** |
| Hybrid retrieval beats vector search | `services/retrieve_service.py` BM25 + RRF, then guard, then ranking | +10.1 pts vs dense on held-out LME; **ties BM25 alone** (0.640 vs 0.662) | **Partially supported** |
| Handoff packets improve context transfer | `services/handoff_service.py` | Unit tests only; no task-level evaluation | **Implemented, unevaluated** |
| Reflections and consolidation | `reflect_service.py` (on-demand, LLM); `consolidation_service.py` **called by nothing** | None | **Reflection unevaluated; consolidation is dead code** |
| PII redaction | `domain/privacy/redaction.py`, wired at ingest (off by default) | Unit tests | **Implemented (regex), coverage unmeasured** |
| Production-ready deployment | Docker, Compose, Kustomize, Helm, RLS, outbox, metrics, tracing | Compose and kind installs verified; CI green | **Infrastructure demonstrated; no production traffic** |

---

## C. Repository and architecture map

**Size:**

| Area | Files | Lines | Responsibility |
|---|---|---|---|
| `apps/` | 13 | 2.3K | API, auth, security, idempotency, rate limits, CLI |
| `services/` | 13 | 2.6K | Ingest, retrieve, guard, erasure, outcomes, feedback, handoff, learning runtime, vector sync, LLM services |
| `domain/` | 21 | 2.8K | Scoring, BM25 and RRF, provenance, receipts, redaction, risk model, trust calibrator, weight learner, EWC (unused) |
| `adapters/` | 22 | 2.8K | Postgres (+RLS), pgvector, Qdrant, Neo4j, in-memory stores, tenancy wrappers, embeddings, LLM clients |
| `bench/` + `audit/` | 19 | 2.1K | Validation suites, external integrity audit |
| `tests/` | 55 | 3.8K | 258 tests |

The API has 35 routes.

**Boundaries as implemented:**

| Layer | Present? | Where |
|---|---|---|
| Base model | **No** (external agent) | The LLM is used only by contradiction, reflection and update services |
| Prompting and context assembly | Partial | `handoff_service.py` (budgeted markdown); `/retrieve` `context_window` string |
| Retrieval | Yes | Dense (vector store) + BM25 over ≤2,000 newest active memories, fused by RRF, then guard, scoring and reranking |
| Short-term session state | No real implementation | `MemoryType.WORKING` exists but nothing uses it |
| Persistent memory | Yes | Postgres canonical store, control plane, pgvector or Qdrant |
| Learned parameters | Yes (small) | Risk-model weights, Beta trust per source/origin, per-user ranking weights, all event-sourced |
| Planning and tools | No | (n/a) |
| Evaluation and feedback | Yes | `/feedback`, `/corrections`, quarantine review, `bench/` |

**Core workflows (traced through code):**

- **Write:**
  1. `routers.ingest_memory`
  2. `IngestionService.ingest_observation`:
     1. PII redaction (optional)
     2. `_provenance`: learned trust, rule and risk-model screening, then active or pending
     3. `save_memory`
     4. embed and upsert (outbox on failure)
     5. graph node
- **Read:**
  1. `RetrievalService._retrieve`:
     1. `_semantic_search`, plus `_lexical_search` (BM25 built *per query*) when hybrid is on
     2. `_fuse` (RRF)
     3. `_enrich_candidates`: guard `resolve`, keep the best relevance, `score_memory_for_retrieval`
     4. filters, then `HeuristicReranker`, then `bump_access` and the ledger record
- **Learn:**
  - `/feedback`: atomic ledger consume, weight learner, `used` trust event, implicit benign risk label.
  - `/corrections` and quarantine release/reject: `OutcomeService`, which updates the trust calibrator and risk model and erases on reject.
  - All of these become `learning_events`, replayed by `LearningRuntime`.
- **Forget:** `ErasureService.forget`:
  1. closure (versions, derived, duplicates by cosine ≥0.95)
  2. purge from relational, vector and graph stores
  3. re-verify
  4. signed receipt

**Architecture assessment:**

- **Sound:**
  - The guard-at-read design is robust to index staleness (proven at scale).
  - Event-sourced learning gives replay, rollback and replica consistency.
  - Tenancy is enforced in two layers (wrappers and RLS).
- **Unnecessary complexity for the current stage:**
  - Four storage backends, Neo4j graph nodes that nothing reads for retrieval, Kustomize *and* Helm.
  - Two continual-learning systems: the event-sourced learners and the unwired EWC policy.
- **Brittle points:**
  - BM25 is rebuilt per query over up to 2,000 memories, which is O(n) per query and silently ignores older memories beyond the pool.
  - Recency is computed from `updated_at`, which every retrieval rewrites (`core/schemas/memory.py:138–141`, `bump_access`).
  - There are **65 broad `except Exception` handlers**. Retrieval enrichment logs failures at *debug* level and drops the candidate (`services/retrieve_service.py`, `_enrich_candidates`). That is how the earlier negative-cosine bug silently removed results.
- **Information-flow gap:** the learning signals (feedback, corrections) never reach anything that changes *what is stored*: extraction, typing, or detecting updates. They only change ranking and screening.

---

## D. Continual learning assessment

**What "continual learning" means here: no model weights change.** Four mechanisms exist:

| Mechanism | Triggered by | Validation of feedback | Persisted / versioned / rollback | Evidence of benefit |
|---|---|---|---|---|
| Write-risk model (online logistic, hashed n-grams) | Quarantine reviews, `malicious` corrections, implicit "used" signal | None. Reviewers are trusted; implicit labels are capped at once per memory | Event log, replay, rebuild, per tenant; no automated per-tenant regression gate | **Simulation, 50 runs:** InjecAgent 17.6% → 95.3–95.5%; BIPIA 0% → 66.1–75.7%; false alarms 0.1–0.5% |
| Trust calibrator (Beta per source/origin) | Reviews, corrections, confirms, usage | None beyond event types | Event log | **Unit tests only** (retroactive distrust); no real-data evaluation |
| Per-user ranking weights | `/feedback` used/unused | Atomic replay protection | Event log; reset per user; active after 20 events | **None**: never shown to improve retrieval |
| EWC ranking policy | (n/a) | (n/a) | (n/a) | **Not wired**; evaluated only on synthetic random vectors |

**Caveats on the strongest result (risk-model learning):**

- **Reviewers are oracles.** Their labels equal the ground truth; real reviewer error is untested.
- **The attack base rate is unrealistic.** The stream is 20% attacks (benign ratio 4:1). At realistic rates (≤1%), "reviews per 100 writes" (12–19 here) would mostly be false-alarm reviews.
- **The InjecAgent gain is insensitive to how many missed attacks are reported** (95.3% at 20% and at 100%). That points to learning the deployment's *tool-response templates* (shared between stream and future by design) rather than attack semantics. BIPIA, which is fully disjoint, is the more trustworthy figure: **66–76%**.

**What prevents regression or forgetting:**
- Experience replay against seed anchors.
- Cost-asymmetric threshold tuning.
- L2 pull toward defaults (ranking weights).
- Spillover limits (trust).

There is **no shadow mode, canary or automatic rollback** for a tenant model, although the plan calls for them.

**Persistence:** improvement survives restarts and replicas (event-sourced; verified on Postgres in Sessions 6–8).

**Verdict:** *partially implemented and partially demonstrated.* Screening adaptation is demonstrated in idealized simulation.
Retrieval-side learning is implemented but undemonstrated.

**Smallest credible experiment (retrieval-side learning):** LoCoMo has about 150 questions per conversation. Process
questions in chronological order per conversation, and after each one send `/feedback` marking the gold evidence turns
as used.
- **Baseline:** the static ranking.
- **Intervention:** the learned per-user weights.
- **Held-out:** each later question is scored before its own feedback.
- **Regression check:** recall on the first-session questions after learning.
- **Success:** a positive recall@5 delta whose 95% cluster-bootstrap CI excludes 0, with no drop greater than 2 pts on early questions.

Cost: about 1 day, local.

---

## E. Persistent memory assessment

**Correct and complete:**
- Tenant/user isolation in two layers (verified with a non-superuser role in a real database).
- Provenance on every write.
- Explicit revocation honoured at read time.
- Verifiable cascading erasure with receipts.
- Idempotent writes.
- Durable index repair.
- PII redaction (optional).
- Audit trail.

**Gaps and failure modes (evidence):**

1. **No memory extraction.** The API stores what it is given (raw turns). There is no fact extraction, entity resolution or deduplication at write time (deduplication happens only during erasure).
2. **Time is wrong by construction.**
   - `IngestRequest` has no event-time field, so `observed_at` defaults to *now*.
   - Recency uses `updated_at`, which every retrieval refreshes (`bump_access`).
   - Imported histories look equally fresh, and frequently retrieved memories look "recent".
   - This plausibly contributes to the temporal-reasoning gap (AegisMem 0.573 vs BM25 0.660, n=127).
3. **Updates are only honoured when declared.** Knowledge-update recall@5 is 0.620 vs BM25 0.815 (n=72). The guard cannot revoke what nobody marked as superseded, and ingest does not detect contradictions.
4. **Silent mock LLM** (`apps/api/dependencies.py:214–220`). If the LLM client fails to initialize, *in any environment*, contradiction scans, reflections and LLM updates run against `MockLLMClient` and return fabricated outputs. `validate_runtime_config` does not check this.
5. **Consolidation** exists (`services/consolidation_service.py`) but is called by nothing.
6. **Preference questions:** hybrid hurts here (AegisMem 0.539 vs dense 0.639, n=30). Lexical matching is a poor signal for implicit preferences.
7. **No export or DSAR endpoint.** Users can list and erase but not export.
8. **Scaling:** BM25 rebuilt per query over the newest ≤2,000 memories. Older memories become invisible to the lexical arm.

**Does memory improve outcomes?** *Unknown.* We know that AegisMem retrieves gold evidence turns better than raw vector
search and about as well as BM25. We do not know whether an agent answers better with it.

**Proposed memory evaluations:**

| Evaluation | How | Pass criterion |
|---|---|---|
| Answer accuracy | LongMemEval QA with a local LLM (e.g. llama3.2 or gemma via Ollama) given AegisMem top-k, vs stateless, full-history, BM25-only and dense-only | Full system > best ablation, CI excluding 0 |
| Revision | LongMemEval knowledge-update *answers* (not only retrieval), with and without automatic update detection | ≥ BM25 on knowledge-update recall, and answer accuracy improving |
| Cross-user leakage | Existing ISO and RLS tests, plus fuzzed tenant/user ids at scale | 0 |
| Poisoned memory | Insert BIPIA/InjecAgent payloads into histories; measure whether the downstream LLM follows them, with and without AegisMem | Attack success rate reduced, CI excluding 0 |
| Deletion | Existing erasure suite, plus the "answers about the erased fact" rate in the QA loop | 0 erased facts answered |

---

## F. Validation dataset and evaluation assessment

**Can establish (reproduced here):**
- Retrieval quality on real long-term chats (LongMemEval, MIT, held out, 470 questions, 231K turns).
- Write-screening false-alarm rates on 86K real harmless items.
- Cold-start detection on held-out real attacks.
- Mechanism correctness for revocation and erasure on real text.

**Cannot establish:**
- Answer quality or agent task success (no LLM-in-the-loop evaluation).
- Value of the handoff, reflection and contradiction features.
- Behaviour with real reviewers or real attack base rates.
- Detection of *undeclared* fact changes.
- Value to real users.

**Where evaluation can mislead:**

1. **Repository artifacts from the earlier branch are not credible and should be removed or relabelled:**
   - `docs/benchmarks/ir_benchmark.json`: "+22 pts recall@5" from **2 users, 14 memories, 9 queries, mock embeddings**.
   - `docs/benchmarks/latency.csv`: 10 queries, retired FAISS stack.
   - `docs/benchmarks/continual_eval.json` and the CHANGELOG EWC claim: **synthetic random vectors**.
2. **README headline** (LoCoMo recall@5 0.565, +5.1 pts) was measured on the set the hybrid weights were *tuned on*.
3. **LoCoMo CIs** are per-question bootstrap, but its 1,536 questions come from **10 conversations**. The intervals understate uncertainty; use cluster bootstrap.
4. **Embedding confound:** all-minilm truncates real turns to about 736 characters (learned limit). Dense results with this model are pessimistic. The nomic and mxbai runs (in progress) will show sensitivity.
5. **Procedurally constructed suites** (revocation, erasure) prove the *mechanism* given correct revocation signals. They say nothing about detecting changes.
6. **InjecAgent learning results** share tool templates between stream and future (realistic for a fixed deployment, but it inflates generality).
7. The **52-example hand-written suite** is now a smoke gate only. Good.

**Leakage and splits (verified):**
- Seed corpus is disjoint from all evaluation sets:
  - InjecAgent split by instruction *and* tool, 0 overlap.
  - oasst1 split by conversation tree.
  - Gandalf and deepset train vs test.
- LongMemEval is never used for tuning.
- LoCoMo **was** used for tuning (disclosed).
- Learning evaluation respects order: the stream comes before future evaluation, with disjoint attack texts.

**Missing baselines and ablations:**
- Stateless LLM.
- Full history in context (LongMemEval-S, about 115K tokens, fits long-context models).
- BM25-only and dense-only *at the answer level*.
- AegisMem without the guard.
- AegisMem without learning (static vs learned weights).

---

## G. Findings by severity

| # | Severity | Finding | Evidence | Consequence | Action |
|---|---|---|---|---|---|
| 1 | **Critical (credibility)** | No outcome-level evaluation; the central value proposition is unmeasured | No LLM-in-loop evaluation anywhere in `bench/` | Every recall number is a proxy; cannot claim memory improves agents | Build the answer-level LongMemEval harness with ablations (Section I, E1) |
| 2 | **High (correctness)** | Silent mock-LLM fallback in all environments | `apps/api/dependencies.py:214–220` | Contradiction, reflection and update return fabricated results without error | Fail closed in staging/production; surface "LLM unavailable" in responses |
| 3 | **High (core claim)** | Undeclared fact changes are not detected; knowledge-update retrieval trails BM25 by 20 pts | LME knowledge-update 0.620 vs 0.815 (n=72); no contradiction check at ingest | The "never serves stale facts" promise holds only when someone declares the change | Detect updates at ingest (same-subject candidate plus LLM or heuristic), then evaluate on knowledge-update |
| 4 | **High (credibility)** | Misleading benchmark artifacts and claims in the repo | `docs/benchmarks/*`, CHANGELOG EWC claim, README LoCoMo headline | Any diligence reviewer finds unsupported claims | Remove or relabel; README cites only `bench/VALIDATION.md` held-out results |
| 5 | **High (temporal)** | Event time missing; recency = last access | `schemas.IngestRequest`; `bump_access` sets `updated_at` | Wrong temporal ordering; imported data looks new; retrieval feeds recency | Add `event_time` to API and SDK; compute recency from event time; stop `bump_access` touching `updated_at` |
| 6 | Medium | The ranking stack does not beat BM25 on held-out data | LME recall@5 0.640 vs 0.662 (CIs overlap) | The added complexity is not yet earning its keep | Re-tune on a dev split; evaluate per question type; consider query-type routing |
| 7 | Medium | Cold-start detection of novel indirect injection is low | InjecAgent 16.7% (n=240), BIPIA 0% (n=600) | New deployments are exposed until reviewers train them | Context-aware detection (instruction-in-data); embedding head; evaluate on the same splits |
| 8 | Medium | Ranking learner and trust calibrator benefit is undemonstrated | No real-data evaluation | Continual-learning claims for retrieval are unsupported | Section I, E3 |
| 9 | Medium | Dead or unwired code | `consolidation_service.py`, EWC `online_scorer.py` and `replay.py` | Maintenance cost; confusing claims | Wire behind evaluation or delete |
| 10 | Medium | Broad exception swallowing in hot paths | 65 `except Exception`; enrichment logs at debug | Silent result loss (has happened once already) | Count dropped candidates as a metric; raise in tests |
| 11 | Medium | Statistics: LoCoMo CIs not clustered | 10 conversations | Overconfident intervals | Cluster bootstrap |
| 12 | Low | BM25 rebuilt per query; pool caps lexical recall | `_lexical_search` | Latency and recall degrade with history size | Postgres full-text index |
| 13 | Low | iCloud sync duplicates (183 files) | Working tree | Test pollution (mitigated) | Move the repo out of iCloud |

---

## H. Prioritized development plan

Assumption: one engineer and this agent, local compute only.

1. **Outcome-level evaluation (1–2 weeks).** It comes first because every other decision depends on it.
   - LongMemEval QA with a local LLM answering from AegisMem context vs ablations, judged by exact match plus a local LLM judge, calibrated on 100 human-checked items.
   - **Accept when:** full system beats the best ablation on answer accuracy with CI excluding 0, *or* we learn it doesn't, and pivot.
2. **Correctness of time and change (2–3 weeks).**
   - Event time in the API and SDK; recency from event time.
   - Automatic update detection at ingest.
   - Remove the silent mock LLM fallback.
   - **Accept when:** knowledge-update recall ≥ BM25 and temporal-reasoning recall ≥ BM25 on held-out LME, with an answer-level gain.
3. **Honest retrieval tuning (≈1 week).**
   - Dev/test split of LongMemEval; re-tune the blend and weights on dev only.
   - Cluster CIs.
   - Report all three embedding models.
   - **Accept when:** AegisMem ≥ max(BM25, dense) on the test split for every question type with n ≥ 30, or a per-type router is introduced.
4. **Continual-learning evidence (≈2 weeks).**
   - The ranking-feedback experiment (Section D).
   - Noisy-reviewer and realistic-base-rate simulation for the risk model.
   - A trust-calibrator evaluation using origins from InjecAgent tools.
   - **Accept when:** each loop shows a CI-backed gain under noisy reviewers (10% label noise) at ≤1% attack base rate, with a false-alarm increase ≤0.1 pt.
5. **Credibility cleanup (2–3 days, can start now).**
   - Remove or relabel the earlier benchmark artifacts.
   - README, CHANGELOG and ROADMAP cite only `bench/VALIDATION.md`.

**Defer until 1–3 pass:** the rest of the Q2 roadmap (gateway, reviewer console, policy engine), the Q3/Q4 platform items, further deployment polish, the EWC research track and graph features.

---

## I. Experiments and acceptance criteria

| ID | Question | Design | Baseline | Success criterion |
|---|---|---|---|---|
| E1 | Does memory improve answers? | LME-S, 470 q; local LLM answers with top-k context; abstention q's scored separately | Stateless; full history; BM25-k; dense-k | Full > best baseline, paired CI excluding 0; report per type and cost/latency |
| E2 | Are changes handled? | E1 on knowledge-update and temporal questions, with and without update detection and event time | BM25 | ≥ BM25 retrieval, and answer gain with CI excluding 0 |
| E3 | Does feedback improve retrieval? | LoCoMo online protocol (Section D) | Static weights | +recall@5, cluster CI excluding 0; early-question regression ≤2 pts |
| E4 | Does screening learning survive real conditions? | 50-run simulation with 10–20% reviewer label noise, 0.1–1% attack rate | Current oracle results | Detection gain ≥ 30 pts on BIPIA future; false alarms ≤ 0.2%; reviews/100 writes reported |
| E5 | Does AegisMem reduce downstream injection success? | Histories with BIPIA/InjecAgent payloads; measure LLM compliance with the payload | Same histories via raw retrieval | Attack-success rate reduced, CI excluding 0, with no answer-accuracy loss |
| E6 | Model sensitivity | Rerun E1 and the recall suites with nomic and mxbai | all-minilm | Conclusions stable across models |

---

## J. Coverage and limitations

**Inspected deeply:**
- `services/` (ingest, retrieve, guard, erasure, outcome, feedback, learning runtime, vector sync).
- `domain/learning/*`, `domain/integrity/*`, `domain/memory/scoring.py` and `lexical.py`.
- `apps/api/{dependencies,auth,security,routers,main}.py`.
- `adapters/tenancy.py` and the relational/vector stores.
- `core/schemas/memory.py` and `core/config/settings.py`.
- `bench/*`, `scripts/continual_eval.py`, `docs/benchmarks/*`.

**Sampled:**
- `services/{contradiction,reflect,update,handoff,consolidation}_service.py`: entry points and callers only.
- `adapters/llm/*`, `integrations/*`, `sdk/*`, `infra/*` (verified by earlier deployment runs).
- The Next.js `src/` site: not inspected.

**Ran in this review:**
- Full LME-S recall (all-minilm, 470 q, 231,606 turns ingested through the production pipeline).
- Injection screening (1,123 attacks / 86,138 harmless).
- Learning simulation (50 runs × 3 settings × 2 environments).
- Dataset audits (label coverage, splits, clustering).
- Code verification of every finding.

**From earlier sessions, not rerun here:** real Postgres/Redis/Qdrant suites, Compose and Helm installs, the integrity audit (7/7), the Mem0 comparison, LoCoMo.

**Also run (full scale):** revocation (4,000 cases) and erasure (2,000 subjects, 8,000 items).

**Still running at writing time:** recall and BEIR with nomic-embed-text and mxbai-embed-large.

Results will land in `bench-results/validation/`. Run `python -m bench.report` to produce `bench/VALIDATION.md`.

**Unknown:**
- Answer-level value.
- Real reviewer behaviour.
- Real attack base rates.
- Cost and latency at production scale (only in-memory benchmarks exist).
- Any user's workflow.

---

## Direct answers

- **What can the product reliably do today?** Store and retrieve memories per tenant and user with strong isolation; never
  serve memories that were explicitly revoked, expired, quarantined or erased; delete verifiably, with receipts; and hold
  very few harmless writes (0.03%).
- **Strongest demonstrated capability:** revocation-safe reads and verifiable cascading erasure (0 leaks in 4,000 cases,
  0 residue across 2,000 subjects, reproduced on real text and real infrastructure). Second: retrieval +10 pts over raw vector search.
- **Largest gap between ambition and reality:** the product claims to make agent memory *trustworthy and current*, but it
  never measures agent outcomes, does not detect undeclared fact changes (knowledge-update trails BM25 by 20 pts), and
  silently uses a mock LLM for its reasoning features.
- **Is continual learning demonstrated?** *Partially.* Screening adaptation is demonstrated in an idealized simulation
  (oracle reviewers). Ranking and trust learning are implemented but undemonstrated. Model-weight learning is absent by
  design. The EWC claim is unsupported.
- **Does persistent memory improve outcomes?** Unknown. It improves *evidence retrieval* over raw vector search
  (+10.1 pts, CI +7.3 to +12.8) but only ties BM25, and answer quality is unmeasured.
- **Can the validation data support the central claims?** It supports retrieval, screening and deletion claims at
  credible scale. It cannot support "improves agents", "handles changing facts" or "learns to retrieve better"
  without E1–E3.
- **What to focus on next:** E1 (answer-level evaluation), then time and change correctness, then honest retrieval
  tuning, then continual-learning evidence.
- **Stop or defer:** new platform features (gateway, console, policy engine, threat network), deployment polish, graph
  features and EWC research, until E1–E3 produce results.
- **Evidence to move to "usable alpha" for the full trust-layer scope:**
  - E1 shows an answer-accuracy gain over the best ablation (CI excluding 0).
  - E2 shows knowledge-update at least at parity with BM25.
  - E3 or E4 show learning gains under noisy reviewers.
  - The silent-mock fallback and misleading artifacts are removed.
  - One design partner runs it on real traffic for 2+ weeks, and false alarms and reviewer load are measured.
