# AegisMem Project Log

Handover log for humans and AI agents. Read this first, then `ROADMAP.md`. Append new entries at the
bottom, newest last. Each entry should cover what was done, why, where in the code, and what is still open.

## Orientation (keep current)

- **What it is:** a governed memory service for LLM agents. FastAPI app with typed memories, hybrid retrieval,
  LLM-judged updates and contradiction checks, reflections, and an eval harness.
- **Strategic bet (since Session 2):** the *integrity layer for agent memory*: provenance and trust, quarantine, a read-time
  guard against revoked or superseded data, and verifiable cascading erasure with signed receipts. Handoff and continual learning sit
  on top. It does not compete with Mem0 or Zep on recall (see `ROADMAP.md`).
- **Layout:** `core/` (schemas, config), `domain/` (pure logic: scoring, reranker, learning, evaluator),
  `services/` (orchestration), `adapters/` (LLM, embeddings, Postgres/Qdrant/Neo4j), `apps/api` (FastAPI routes and DI).
- **Run tests:** `.venv/bin/python -m pytest -q` from `aegismem/`. Mock backends are used and no services are needed.
- **Repo:** git root is `aegismem/` (remote `github.com/Ajay-quan/AegisMem`). The parent folder holds PDFs, screenshots and a tarball, which are not code.
- **Conventions:** async services; stores are injected; tests use `tests/fixtures/conftest.py::MockPostgresStore`;
  scoring weights come from `core/config/settings.py`.

## Log

### 2026-10-10 · Session 1: Review, roadmap, Phase 1 features

**Interaction:** The user asked for a repo review and a merit assessment. Then they asked for a startup-grade plan
focused on novelty, easier context handoff, small real problems a basic user hits, and continual learning,
plus this log file.

**Assessment:** The architecture is solid, but the feature set overlaps Mem0, Zep and Letta. Differentiation must come
from handoff, truth maintenance and learning, proven with benchmarks. Baseline: 58 tests passing.

**Built:**
1. `ROADMAP.md`: positioning, a table of 10 "unnoticed problems" mapped to features, a 3-layer continual-learning
   strategy (retrieval weights, then memory utility priors, then procedural learning; model weights stay frozen), and phases P1 to P3.
2. **Handoff packets**: `services/handoff_service.py`, `POST /api/v1/handoff`.
   - Priority-ordered sections: open_questions, recent_changes (shows the previous value through
     `parent_memory_ids[0]`), profile (semantic layer or fact/procedure/reflection/summary), task_relevant (hybrid
     retrieval), recent_activity.
   - Token budget (estimated at about 4 chars per token), dedupe across sections, per-section cap, `omitted` counts, `since` filter,
     and markdown output with `[memory_id[:8]]` citations. Deterministic, with no LLM calls.
3. **Continual learning v1**:
   - `domain/learning/weight_learner.py`: `OnlineWeightLearner` is per-user online logistic SGD over the signals
     (semantic, recency, importance, access). Guardrails: `min_events=20` before it is served, L2 pull toward the defaults,
     a floor of 0.05 and renormalisation to sum to 1, plus a per-user reset.
   - `services/feedback_service.py`: `RetrievalLedger` is an LRU of the signals scored for each `retrieval_id`.
     `FeedbackService.submit` validates the user, memory ids and one-time use; updates
     `retrieval_count` and `successful_retrieval_count`; and trains the learner.
   - `RetrievalResult.retrieval_id` was added (`core/schemas/memory.py`). `RetrievalService` now takes optional
     `learner` and `ledger` and scores with learned weights when they are active (`score_memory_for_retrieval(weights=...)`).
   - Endpoints: `POST /api/v1/feedback`, `GET` and `DELETE /api/v1/learning/{user_id}`. `/retrieve` now returns `retrieval_id`.
   - DI: module-level `_learner` and `_ledger` singletons in `apps/api/dependencies.py`.
4. Tests: `tests/unit/test_learning.py`, `tests/unit/test_handoff.py`, `tests/api/test_handoff_feedback_api.py`.
   Total is 69 passing.

**Known gaps and next steps (priority order):**
- Learner state and the ledger are **process-local**. They are lost on restart and not shared across workers. Next step: a Postgres
  table for feedback events and user weights (an Alembic migration), plus a `LearningStore` protocol implementation.
- Build an offline replay evaluator: replay logged feedback and compare MRR and recall@k for learned vs. default weights. This gates turning learning on by default.
- Handoff scans up to 500 active memories per call, which is fine for now. It needs indexed queries (by status or contradiction, and by `updated_at`) at scale.
- `access` signal normalisation is duplicated in `scoring.compute_composite_score` and `RetrievalLedger.record`. Extract a shared helper.
- Repo hygiene: there is no `.gitignore`. `__pycache__`, `.DS_Store` and `.env` are tracked. The current `.env` has only placeholder or local values,
  but it should still be untracked. This has not been changed yet and needs the owner's approval.
- After that: the P2 items in `ROADMAP.md` (score explanations, validity windows, memory inbox, PII, SDK).

### 2026-10-10 · Session 2: Pivot to "integrity layer for agent memory"

**Interaction:** The user does not want a Mem0 lookalike and asked for internet research into the space to find a new niche, and
then to start building. "Top 1000" was not literally feasible. I ran targeted searches over the vendor landscape (Mem0, Zep, Letta,
Cognee, Supermemory, LangMem, SurrealDB), 2026 arXiv work on memory security, governance and erasure, and multi-agent handoff.

**Findings → decision:** Recall is commoditised. Unsolved in products: memory poisoning and provenance laundering, revoked facts
still being served, and unverifiable deletion (GDPR). Only fragments exist (SurrealDB enterprise forget, the Attestari OSS package,
the SuperLocalMemory paper). **New positioning: the trust and compliance layer for agent memory.** See `ROADMAP.md`, which was rewritten.

**Bugs found in AegisMem itself (all fixed):**
1. *Revoked-but-authoritative:* superseded memories kept `status=active` in the vector payload and were served. A repro returned
   only the old address. The fix is the read-time guard plus a status sync on supersede (`VectorStore.update_payload`).
2. *Silent result loss:* negative cosine similarity failed the `semantic_score>=0` validation, and the candidate was swallowed. Now clamped
   in `score_memory_for_retrieval`.
3. *Qdrant ids from `hash()`:* these are salted per process, so ids changed on restart and deletes missed. Now `uuid5` (`_point_id`).
   **Existing Qdrant collections need re-indexing.**
4. *Delete was soft:* content and vectors were retained. A new `purge_memory` hard-deletes the row and its contradiction rows.

**Built:**
- `domain/integrity/provenance.py`: trust by source, non-amplification (`derived_trust`), and injection heuristics with a quarantine rule
  (trust < 0.7 and instruction-like). Stored in `metadata["provenance"]` and `metadata["quarantine"]`.
- `services/ingest_service.py::_provenance`: attaches provenance; callers may lower trust but never raise it; quarantined memories get `status=pending`.
- `services/guard_service.py::MemoryGuard`: canonical re-check of every candidate. It serves, replaces with a successor (via `superseded_by` /
  `merged_into` pointers or the `parent_memory_ids` index), or withholds (erased, owner mismatch, quarantined, expired, trust floor).
  It is always on in `RetrievalService`. `RetrievalResult.guard_report` and the `/retrieve` response explain what was withheld.
- `services/erasure_service.py`: `forget` computes the closure (requested, prior_version, derived, duplicate with cosine ≥ 0.95), purges from
  the relational, vector and graph stores, re-verifies each store, and issues an HMAC-signed receipt with keyed-HMAC fingerprints (no content).
- Contradiction temporal supersede now records `superseded_by`. Graph store has `delete_memory_node` and `has_memory_node`.
- API: `POST /forget`, `GET /receipts/{id}`, `POST /receipts/verify`, `GET /quarantine/{user_id}`, `POST /quarantine/{id}/release?user_id=`.
- Tests: `tests/unit/test_integrity.py`, `tests/api/test_integrity_api.py`. Total is **83 passing**.

**Open / next (priority):** persist receipts, quarantine, learner and ledger (all currently in-process); build `scripts/integrity_audit.py`
(the backend-agnostic audit is the go-to-market wedge); add signed handoff packets with per-item provenance; Ed25519 receipts; a pgvector-only mode.
Known limits:
- The injection detector is regex-based (precision and recall are unmeasured), so an eval set is needed.
- `PostgresStore.update_memory` does not persist `parent_memory_ids` or `valid_to` changes.
- Erasure doesn't cover backups (stated in the receipt) or the `facts` / `reflections` tables.
- The successor index scans up to 1000 active memories.

### 2026-10-10 · Session 3: Continual learning from outcomes (calibrated trust)

**Interaction:** The user asked for a "very VERY useful" continual-learning integration and to start immediately.

**Decision:** The most valuable signal is the human decisions the product already collects (quarantine approve/reject,
corrections, confirmations, usage). The system learns *which sources and origins to believe*. That compounds with the integrity niche:
fewer items need review over time, poisoned origins get shut out deployment-wide, and the effect is retroactive.

**Built:**
- `domain/learning/trust_calibrator.py`: `TrustCalibrator` keeps a Beta posterior per `source` and per `source|origin`. Origins
  shrink toward their source (a new origin starts at the source's *learned* trust). The source learns at half rate when an origin is known.
  Event weights are in `EVENT_WEIGHTS` (reject β+4, release α+2, corrected β+2, confirmed α+1, used α+0.25). Prior strength k=10,
  with source priors from `SOURCE_TRUST`. `InMemoryTrustStore` is process-local.
- Ingest (`IngestionService(trust_calibrator=...)`): trust is the calibrated value for `(source, origin)`. `origin` comes from
  `metadata.origin` or `metadata.provenance.origin`, is stored in `metadata.provenance.origin`, and stays capped by the caller-supplied trust.
- Guard (`MemoryGuard(trust_calibrator=...)`): `effective_trust = min(stored, live learned)`, so learned distrust is retroactive.
  The default floor is `settings.guard_min_trust = 0.2`. `servable` is now **async**.
- `services/outcome_service.py`: `OutcomeService.correct(kind=wrong|outdated, corrected_text)` supersedes the memory, links
  `superseded_by` to the replacement, penalises the origin only for `wrong`, and flags transitively derived memories
  (`contradiction_status=suspected`, confidence halved). It also has `confirm`, `release` (now used by the existing release endpoint) and
  `reject` (penalise plus erase with a receipt).
- `FeedbackService` records `used` for the origin of each used memory.
- API: `POST /corrections`, `POST /memories/{id}/confirm?user_id=`, `POST /quarantine/{id}/reject?user_id=`,
  `GET /trust/sources` (least-trusted first). DI: the `_calibrator` singleton is injected via `Depends(get_calibrator)`
  into the ingest, retrieve (guard), feedback and outcome services, so tests can override it.
- Tests: `tests/unit/test_trust_learning.py` (retroactive distrust, origin isolation, release builds trust, wrong vs outdated,
  blast radius, cross-user protection) and an API test in `tests/api/test_integrity_api.py`. Total is **92 passing**.

**Known limits / next:**
- Calibrator state is in-process and should be persisted with the other learning state.
- Trust is per deployment. Per-tenant scoping is needed for multi-tenant SaaS (key prefix by tenant).
- Event weights are hand-set. Fit them from reviewer data once it exists.
- `used` events could be gamed by a compromised agent. Consider capping the positive mass from `used` per origin per day.
- Add a time decay so origins can recover, and an audit trail of trust changes (who or what moved it).

### 2026-10-10 · Session 4: Self-improving write-risk model (continual learning #2)

**Interaction:** The user set a standing persona (world-class AI-startup PM plus top engineer) and repeated the request for a very useful
continual-learning integration. Saved as a memory preference.

**Product rationale:** Calibrated trust (Session 3) learns *who* to believe. Screening *what* gets held was still a fixed regex,
and reviewer workload (false positives) and missed attacks (false negatives) are the core cost and liability of a HITL product.
So reviewer decisions now train the screener.

**Built:**
- `domain/learning/risk_model.py`: `OnlineRiskModel` uses crc32-hashed word unigrams and bigrams (2^18 dims), AdaGrad logistic regression
  with L2, and a seed corpus (`SEED_MALICIOUS`/`SEED_BENIGN`) for cold start. `threshold(trust) = 0.5 + 0.4·trust + precision_adjust`,
  where precision_adjust = (0.5 − precision of model-held items) × 0.4 after 5 or more reviewed holds, clamped to [0.2, 0.95]. `score()` returns
  the probability, threshold, flag and top positive features (stopwords excluded) for explanations. `stats()` backs `GET /api/v1/risk-model`.
- Ingest: rule check first (`trigger: "rule"`), then the model (`trigger: "model"`, reason plus `features`). `metadata.risk = {p, threshold}`
  is stored on every write.
- `OutcomeService`: release and confirm train benign, reject trains malicious (before erasure). The new correction kind **`malicious`**
  covers an attack that slipped through: it penalises the origin like a rejection, trains the model, increments `missed_attacks`, and erases the memory
  plus duplicates and derivatives with a receipt. This is the only path by which recall improves.
- DI: the `_risk_model` singleton is injected via `Depends(get_risk_model)` into the ingest and outcome services.
- Route note: the stats endpoint is `/risk-model`, not `/learning/risk-model`, because `/learning/{user_id}` would capture that path.
- Tests: `tests/unit/test_risk_model.py` covers cold start, recall gained from missed-attack reports (a new variant from an unseen
  origin gets held), false positives dropping after releases, threshold self-tuning both ways, explainability and determinism. Total is **102 passing**.

**Observations / limits:**
- At cold start, "Our refund policy changed: refunds are never allowed" (tool output) is held at p = 0.76. That may be a false positive
  for support bots. The release loop corrects it per deployment, but the seed corpus needs real-world tuning and a held-out eval set.
- The model is per deployment, in-process and unpersisted, like the other learning state. **Persisting all learning state is now the #1 P1 gap.**
- Reviewer-poisoning risk: a malicious reviewer could release attacks to train them in. Add an audit trail and per-reviewer weighting later.
- Bag-of-n-grams is easy to evade with paraphrases. A small embedding-based head (using the existing embedding backend) is the upgrade path.

### 2026-10-10 · Session 5: 12-month product plan

**Interaction:** The user wants production-grade solutions, not demos or small-scale ones, and asked for a full one-year plan for incrementally
expanding scope and usefulness.

**Output:** `PRODUCT_PLAN_12M.md` (Nov 2026 – Oct 2027). It covers the thesis, ICP and personas, principles, quarterly epics with exit criteria,
the continual-learning plan with safety gates, KPIs and the north star, GTM and pricing hypotheses, the team plan, risks, and a 30-day sprint. Scope path:
memory integrity → gateway for any memory store → compliance-grade governance (crypto-erasure, DSAR, SOC 2) → context integrity platform plus a
cross-tenant threat network (the moat).

**Implication for engineering:** the next work is Q1 "production core" and starts with durable, tenant-scoped, event-sourced learning
state (remove the in-process singletons in `apps/api/dependencies.py`), auth, pgvector mode, the outbox sync and `aegis-bench`. No new
features until that lands. An open decision for the founders is hosted-first vs self-host-first (recommendation: hosted, with a VPC option).

### 2026-10-10 · Session 6: Q1 execution, checkpoints CP0–CP4 (branch `q1/production-core`)

**Interaction:** The user asked to start Q1 work immediately, in professional checkpoints, with a progress percentage and a full update at the end.

**Environment notes:**
- Docker was not running and there was no local Postgres. SQL code is tested on SQLite through the same SQLAlchemy async path. Postgres is
  covered by CI (`.github/workflows/ci.yml` runs the Postgres 16 service, the alembic round-trip and the integration tests against it), but **CI has not run yet**
  because nothing has been pushed.
- The venv was moved from another path, so `.venv/bin/pip` has a broken shebang. Use `.venv/bin/python -m pip`.
- `greenlet` was missing, which made every async SQLAlchemy call fail. That means `PostgresStore` had never worked in this venv. It is now a declared dependency.

**Checkpoints (git commits):**
- `505cdf7` CP0: committed sessions 1–5 and repo hygiene (.gitignore; untracked `__pycache__`, `.DS_Store`, `.env`).
- `59af93f` CP1: durable learning state. Components are deterministic state machines (`apply`/`to_state`/`from_state`).
  `services/learning_runtime.py` handles append → catch-up replay, so replicas converge, plus snapshots every 200 events and `rebuild`.
  `adapters/relational_store/control_store.py` + `control_models.py` hold the event log, snapshots, receipts, ledger (atomic consume) and API keys.
  The risk model uses tenant-keyed BLAKE2b feature hashing, and **its events store no plaintext**. Alembic env plus migration 0001.
- `71bdac7` CP2: multi-tenancy and auth.
  - `apps/api/auth.py`: API keys (peppered HMAC), 5 scopes, router-level `authorize` that **fails closed** on unmapped routes (a test
    enforces that every route is mapped).
  - `adapters/tenancy.py`: scoped memory and vector stores applied in DI. Methods are allow-listed, and cross-tenant access looks like a 404.
  - Admin key API plus `scripts/aegisctl.py`.
  - Boot guards: staging and production require auth, a real secret, a pepper and live stores.
  - **Fixed silent data loss in `PostgresStore`:** `memory_layer`, `contradicted_by` and the retrieval counters were never persisted, and
    `update_memory` dropped `parent_memory_ids`, `valid_to`, `confidence` and `tags`. Migration 0002 adds the columns and backfills the layer.
- `89bf5c9` CP3: `bench/` (aegis-bench).
  - Held-out dataset `bench/datasets/injection_v1.jsonl` (52 rows).
  - Suites: poisoning, learning (8-seed mean), revocation, erasure and latency, with gates in `bench/thresholds.json` and pytest gate tests.
  - Learning fixes the bench found: `SOURCE_SPILLOVER` 0.5→0.1, `INHERIT_FLOOR` 0.8, experience replay against seed anchors, and cost-asymmetric
    threshold tuning. Decision rationale: at production base rates FPR dominates reviewer cost, so the FPR-conservative config was chosen.
  - Heavy dependencies moved to extras.
- `6edf116` CP4: `sdk/python` (`aegismem-client`), whose retry policy never re-sends a state-creating write that may have reached the server.
  Prometheus `/metrics` (no ids in labels), `/ready` probe, and the ingest response now exposes quarantine status.

**Bench baseline (`python -m bench.run`):**
- poisoning: recall 0.58 (rules-only 0.125), FPR 0.107, user-message FP 0.
- learning: recall 0.57→0.78, FPR +0.018.
- revocation: 0 leaks across 7 scenarios.
- erasure: 0 residue, cascade recall 1.0.
- screening p95 0.05 ms, guard p95 0.04 ms.

**Tests:** 136 passing.

**Q1 progress tracker (engineering):**

| Epic | % | Remaining |
|---|---|---|
| Durable state | 90 | Postgres verification in CI; scheduled ledger pruning |
| Multi-tenancy & auth | 75 | Postgres RLS, per-tenant rate limits/quotas, graph tenant stamping, backfill script for pre-tenancy vector payloads |
| Single-store mode (pgvector, Helm) | 0 | all |
| Async pipeline / outbox | 0 | all (also server-side Idempotency-Key for ingest) |
| Observability | 60 | OpenTelemetry tracing, Grafana dashboards and alerts in Helm |
| Eval & benchmarks | 65 | public injection datasets, LongMemEval/LoCoMo recall-impact suite, multilingual |
| SDKs + MCP | 35 | TypeScript SDK, MCP server, LangGraph/OpenAI Agents SDK integrations |
| OSS Integrity Audit CLI | 0 | all |
| **Q1 engineering overall** | **≈41%** | |

**Next (recommended order):** push the branch and get CI green on Postgres → pgvector single-store mode → outbox + idempotent ingest →
OSS audit CLI (GTM wedge) → MCP server and TS SDK → RLS and rate limits → OTel.

### 2026-10-10 · Session 7: Q1 continued, CP5–CP12 (branch `q1/production-core`, not pushed)

**Interaction:** The user asked to continue the development completely. The push was not authorized, so all work is in local commits.

**Checkpoints:**
- `02bd8da` CP5, single-store mode:
  - `adapters/vector_store/pgvector_store.py` (HNSW cosine; SQLite fallback for dev), `NullGraphStore`.
  - Settings `vector_backend`/`graph_backend`, migration 0003.
  - Vector-store **conformance kit** (`tests/integration/test_vector_store_contract.py`).
  - CI image `pgvector/pgvector:pg16`.
- `ee5bba1` CP6, reliable writes:
  - `apps/api/idempotency.py` (Stripe semantics) on ingest, batch, corrections and forget.
  - `services/vector_sync.py`: `ResilientVectorStore` + `OutboxWorker`. Failed index ops are queued with ids only, retried with backoff and dead-lettered. Erasure cancels pending repairs.
  - The SDK sends a stable auto Idempotency-Key. Migration 0004.
  - **Security fix:** `/ingest/batch` ignored per-item `source_type`, which let tool output bypass screening.
- `2b7888b` CP7, `audit/` (`aegis-audit`):
  - Seven checks: REV-1, DEL-1..3, POI-1..2, ISO-1.
  - Targets: AegisMem, Mem0 REST (**unverified against a live Mem0**), and a naive reference.
  - The naive reference scores 1/7; AegisMem scores 7/7 through HTTP.
- `31fd03d` CP8, `integrations/mcp`: stdio JSON-RPC MCP server with remember/recall/handoff/correct/used/forget. Tested via a real subprocess.
- `697954c` CP9:
  - `sdk/typescript` (`@aegismem/client`), strict tsc.
  - `MEMORY_BACKEND=memory` Docker-free dev mode.
  - A pytest boots uvicorn and runs the TS e2e against it.
- `b40cc78` + `73b4431` CP10, platform hardening:
  - Per-tenant rate limits (`apps/api/ratelimit.py`; Redis Lua or in-process; off by default in tests via conftest).
  - **Postgres RLS:** migration 0005 plus `core/tenancy_context.py`. The tenant is bound per transaction through `set_config`; `system_context()` is used for cross-tenant jobs. An AST test guarantees every wrapper call is tenant-bound.
  - **Superusers bypass RLS**, so boot refuses a superuser or BYPASSRLS app role in prod (`REQUIRE_RLS`).
  - OpenTelemetry (`core/observability/tracing.py`; W3C propagation, no content in attributes).
- `65f4f1a` CP11, deployment:
  - Hardened multi-stage Dockerfile.
  - Single-store compose with owner/app roles and a migrate gate.
  - Kustomize base and production overlay (verified with `kubectl kustomize`). Helm is not used yet.
  - Deployment invariant tests and `docs/DEPLOYMENT.md`.
- `2262f25` CP12: hourly pruning of the ledger and idempotency records, `aegisctl prune`, and `aegisctl backfill-tenant` for Qdrant (**untested, no Qdrant server locally**).
- README rewritten for the integrity positioning.

**Verification status:**
- 168 tests passing, plus 3 skipped (Postgres RLS ×2 and the shared Redis limiter need CI services).
- Bench gates pass with unchanged numbers. TS typecheck passes. Compose config and Kustomize render validate.
- **Not verified:** Docker image build (daemon down), the Postgres/Redis paths (they run only in CI and CI has never run), the Mem0 adapter, and the Qdrant backfill.

**Q1 engineering tracker (updated):**

| Epic | % | Remaining |
|---|---|---|
| Durable state | 95 | first CI run on Postgres |
| Multi-tenancy & auth | 95 | graph-node tenant stamping; CI verification of RLS |
| Single-store mode & deploy | 85 | build and run the image; Helm chart (Kustomize ships today) |
| Async pipeline / outbox | 85 | `FOR UPDATE SKIP LOCKED` for multi-replica workers (currently duplicate-safe, not exclusive); retire the legacy Celery worker |
| Observability | 85 | Grafana dashboards JSON; alert rules as code |
| Eval & benchmarks | 65 | public injection datasets, LongMemEval/LoCoMo recall-impact suite with a real embedding model, multilingual |
| SDKs + MCP | 85 | LangGraph / OpenAI Agents SDK integrations; publish to PyPI/npm |
| OSS integrity audit | 85 | verify the Mem0 adapter live; publish results responsibly |
| **Q1 engineering overall** | **≈85%** | (design-partner recruiting is non-engineering and not counted) |

**Next:**
1. Push and get CI green (Postgres, pgvector, RLS and Redis paths).
2. Build and smoke-test the image with compose.
3. Public-benchmark suite with real embeddings.
4. Framework integrations.
5. Publish the SDKs and the audit.

### 2026-10-10 · Session 8: Q1 completed (CP13 onward), verified on real infrastructure

**Interaction:** The user asked to complete Q1 to 100%. Docker Desktop was started locally to verify against real services. Test
containers, a kind cluster, Homebrew tools (helm, kind, actionlint), and the Ollama model `nomic-embed-text` were added to the machine.
Still **not pushed**: pushing needs the user's approval, and publishing needs their registry credentials.

**Verification infrastructure used:** Postgres 16 + pgvector (Docker, :55432), Redis 7 (:56379), Qdrant 1.17 (:56333),
Ollama `nomic-embed-text` (768-d), a Docker Compose stack in staging config (:58000), and a kind cluster with Helm.

**Critical bugs found only by real infrastructure (all fixed):**
1. Qdrant `search()` was removed in the current qdrant-client, so **every Qdrant retrieval failed**. Moved to `query_points`.
2. The embedding factory never implemented `openai`/`voyage`, and **production silently used mock vectors** when no LLM key was set.
   There is now an OpenAI-compatible backend; mock is dev-only; a boot dimension probe was added.
3. **Ranking cost 28 points of recall** (LoCoMo recall@5 was 0.262 vs 0.540 for raw search). The cause was an access-count popularity feedback loop
   plus query-independent weights. Raw access was replaced with utility, and the defaults are now relevance-dominant. Result: **0.521 vs 0.514 raw**.
4. Migrations in the container crashed because newer SQLAlchemy defaults `postgresql://` to psycopg3. The driver is now pinned.
5. Helm: the pre-install hook referenced a not-yet-created ServiceAccount, and the install hung.
6. Kubernetes service links (`POSTGRES_PORT=tcp://…`) broke settings. Fixed with `enableServiceLinks: false`.
7. Model and migration drift on the HNSW index.
8. Risk-model selection bias (labels only for held items) produced 20% FPR after learning. Implicit benign signals from used memories fixed it (FPR 0.07).

**Built:**
- Exclusive outbox claims (`FOR UPDATE SKIP LOCKED` + lease). Graph nodes carry tenant_id.
- Alert rules (8, promtool-validated) and a Grafana dashboard (12 panels), provisioned in compose and verified live.
- Helm chart `infra/helm/aegismem`, installed and upgraded on kind.
- `bench/locomo.py` (recall impact with real embeddings) and the external deepset dataset suite (EN+DE, gated).
- The tool catalogue was moved into the SDK (`aegismem_client.tools`).
- `integrations/frameworks`: LangChain/LangGraph tools plus `handoff_node`, and OpenAI Agents SDK FunctionTools.
- aegis-audit `mem0-lib` target. Results: Mem0 OSS 2.2.1 scores 5/7 (infer) and 4/7 (no infer); AegisMem scores 7/7 under compose and Helm.
- Release automation (`release.yml`): PyPI OIDC, npm provenance, a multi-arch GHCR image with SBOM, and a Helm OCI chart. All packages pass `twine check --strict`.
- Image slimmed from 841 to 584 MB. The no-op Celery worker was retired.

**Final verification:**
- 205 tests passed with 0 skipped, on live Postgres, Redis and Qdrant.
- All bench gates pass.
- Migrations are clean on Postgres and SQLite.
- `helm lint --strict` and actionlint pass.
- The audit scores 7/7 on compose and on Helm.
- RLS was proven in the deployed database: app role with no or a foreign tenant sees 0 rows; it cannot run DDL.

**Q1 engineering tracker: 100%.** Every Q1 epic in `PRODUCT_PLAN_12M.md` is implemented and verified. What remains is not engineering:

| Item | Owner / blocker |
|---|---|
| Push branch, open PR, first GitHub CI run | needs the user's approval |
| First release (tag `v0.1.0`) | user: configure PyPI trusted publishers + `NPM_TOKEN` |
| Publish Mem0 audit results | responsible disclosure to Mem0 first |
| Design partners (3–5) | founder-led sales |
| Unexplained one-off: first live-PG run had 16 fixture errors that never recurred in 8+ runs | watch in CI |

**Local cleanup notes:**
- Test containers: `aegis-test-pg`, `aegis-test-redis`, `aegis-test-qdrant`.
- Compose project: `aegis-smoke`.
- kind cluster: `aegis`.
- Isolated Mem0 venv: in the session scratchpad.

### 2026-10-11 · Session 9: Merged `main` (v0.3.0 "stateful.ai" line) into `q1/production-core`

**Interaction:**
- PR #1 (`q1/production-core` → `main`) was opened by the user. GitHub reported it not mergeable: `main` had 7 newer commits (the user's own, made in parallel: rebrand to stateful.ai, v0.2–0.3), 343 files changed, 22 conflicts.
- The user decided the name is **AegisMem** and left the technical calls to me.

**Approach:**
- Merged `main` into the branch with no force-push and no history rewrite.
- Q1 is the backbone for conflicted files. `main`'s non-duplicative capabilities were ported, duplicates consolidated, and retired code stays in history at `e20ba0b`.
- Rationale is recorded in `docs/adr/0005-merge-integrity-architecture.md`; ADRs 0001–0004 are marked superseded.

**Ported from main:**
- BM25 + RRF hybrid retrieval as a candidate stage before the guard.
- Cross-encoder option.
- PII redaction at ingest, before screening and embedding.
- Security headers, a 413 body limit, the error envelope.
- `/stats`.
- Retrieval and feedback telemetry (renamed `aegis_*`).
- Zero-infra dev defaults with `relational_store`/`strict_stores` aliases.
- EWC policy, replay buffer and BWT/FWT modules kept as an evaluation harness.
- The CLI, rewired to the SDK.
- The Next.js landing site, rebranded.
- The audit trail, made **durable and tenant-scoped** (`audit_events`, migration 0006, `GET /api/v1/admin/audit`).

**Retired (superseded):**
- Flask demo stack: Flask app, JSON store, FAISS store (sync, pickle metadata), local graph, cache index, landing HTML.
- Single-key registry and in-process audit.
- `query_id` feedback.
- Stdlib SDK and main's MCP server.
- Root Dockerfile, `requirements*.txt`, `push.sh` (which auto-pushed to main), committed `build/`, `architecture.drawio`.

**Measured decisions:**
- LoCoMo, full dataset with real embeddings: hybrid blend 0.15 with pool 2,000 gives recall@5 **0.565 vs 0.514** raw (+5.1 pts).
- Main's defaults (pool 200) scored 0.418, because BM25 only saw the newest 200 memories. Defaults are now set accordingly.

**Bugs found and fixed during the merge:**
1. **The "unexplained one-off" from Session 8 is solved.** On a fresh Postgres, `create_all` ran before the vector extension existed. `ensure_pgvector()` now runs in every schema path.
2. **FastAPI 0.143** (what production installs) reports included-router routes with *relative* paths. That broke admin scopes, metrics labels and the audit trail. The route-scope coverage test had become **vacuous** (it walked `app.routes`, which no longer exposes routers).
   - Fix: `apps/api/routing.route_template()` reconstructs the full template from public data.
   - The coverage test now enumerates the OpenAPI schema and asserts at least 25 routes were checked.
   - The local venv was upgraded to match production.
3. The in-memory store counted deleted memories (Postgres doesn't). Fixed.
4. **Tests read the developer's `.env`.** The local `.env` set `sentence_transformers`/`bge-large`. Tests now set `AEGIS_ENV_FILE=""`, and the suite went from ~40 s to ~16 s.
5. Deployments relied on old defaults. Compose, Kustomize and Helm now declare `MEMORY_BACKEND` explicitly, with a test enforcing it.
6. `.env.example` documented settings that don't exist. It was rewritten, and a test now enforces that every key is a real setting.

**Verification:**
- 253 passed locally (+4 skipped live-service tests).
- **281 passed** with Postgres + pgvector, Redis and Qdrant on a **fresh database** (twice).
- All bench gates pass. Migrations 0001→0006 are clean on Postgres and SQLite.
- Compose stack on FastAPI 0.143: ready; aegis-audit **7/7**; durable audit trail and `/stats` verified.
- `helm lint --strict` passes. Version is **0.4.0**, and no "stateful.ai" references remain.

### 2026-10-12/13 · Session 10: Validation sprint on real data (branch `validation/benchmarks`)

**Interaction:**
- The user asked for validation on large, real (non-AI-generated) datasets with many more iterations before starting Q2.
- Decisions:
  - **Free/local embeddings only** (Ollama: all-minilm 384d, nomic-embed-text 768d, mxbai-embed-large 1024d).
  - **Non-commercial or unasserted-license datasets** are used for internal evaluation only (runtime download, never redistributed).
  - Headline claims rest on permissive datasets.

**Datasets (verified license, sha256 recorded per run, `bench/sources.py`):**

| Group | Datasets |
|---|---|
| Recall | LongMemEval-S (MIT, 500 q, 246,750 turns), LoCoMo (tuning set; internal), BEIR SciFact/NFCorpus/FiQA (CC BY-SA) |
| Attacks | InjecAgent (MIT), BIPIA (internal), Lakera Gandalf (MIT), deepset (Apache), SPML (MIT, caveat: different threat model) |
| Benign | OpenAssistant oasst1 (Apache, 88,838 multilingual messages), plus LongMemEval and LoCoMo turns |

- Rejected: HackAPrompt (gated), MSC (no license), WildChat (not needed).

**What the real data exposed (all fixed or reported):**
1. **The seed corpus was the "AI slop".** The 28 hand-written seed sentences made the risk model treat the word *"assistant"* and phrases like *"you should"* as attack signals, holding **13.2% of real assistant replies** (23.5% in a 5-question smoke run).
   - It was replaced by `domain/learning/seed_corpus.jsonl.gz`, built by `bench/build_seed_corpus.py`.
   - Sources (permissive training data only): Gandalf train, deepset train, the InjecAgent seed half, and oasst1 seed-split trees.
   - Result: **0.04% macro false alarms on 106K real harmless items.**
2. **Template leakage.**
   - InjecAgent split by attacker instruction only gave 98% detection, but held-out cases reused tool-response templates.
   - A strict split by instruction **and** tool gives the honest cold-start figure: **18.3%**.
3. **BIPIA task hijacks** ("Recommend a good book" inside an email) are 0% at cold start: undetectable from content alone. Context-aware detection is a Q2 item.
4. **Continual learning (3-run smoke):** never-seen attacks go **15% → 97%** (InjecAgent, deployment tools) and **0% → 72%** (BIPIA, fully disjoint), with false alarms of 0.1–0.4%. The full run is 50 runs × 3 report rates.
5. **Product bug:** embedding inputs longer than the model's context made long memories unindexable (the outbox would dead-letter them). The backend now truncates adaptively, learning the limit from the provider's rejection.
6. **Product bug:** retrieval kept the *first* rather than the *best* relevance per memory. Under a stale index, guard substitution served the successor only 67.5% of the time; it is now **100% over 400 real-text cases** (0 leaks).
7. **Harness bug, not product:** erasure used mock embeddings while ingest used real ones, so duplicates were missed. Fix: `use_embedding()` swaps the backend into every service.
8. **Environment:** iCloud created 183 byte-identical `* 2.py` sync-conflict copies in the repo, which doubled test collection. They are ignored in pytest and git and were *not deleted* (they are the user's files).
9. **Methodology note:** hybrid weights were tuned on LoCoMo, so LoCoMo is reported as the *tuning set*. LongMemEval and BEIR are held out.

**Built:**
- `bench/{sources,embedcache,stats,memory_recall,beir_eval,injection_eval,injection_learning,integrity_scale,validate,report}.py`.
- Bootstrap CIs everywhere.
- A resumable orchestrator: `python -m bench.validate`, then `python -m bench.report` produces `bench/VALIDATION.md`.
- The 52-example hand-written suite was demoted to smoke gates (`bench/thresholds.json`).
- Risk-model seeding is cached per key (1.1s once per tenant per process).

**Full runs launched in the background:**
- Job A: injection, learning (50 runs), integrity (4,000 revocation cases, 2,000 erasure subjects).
- Job B: LongMemEval, LoCoMo and BEIR × 3 models (~8–10 h; mxbai is the long pole).
- Results go to `bench-results/validation/*.json` (gitignored).

## Session 11 — 2026-10-13: Honest rework (outcome-level evaluation, root-cause fixes)

**User directive:** no manipulated data and no shortcuts. Measure whether answers are *correct* (not only whether retrieval hits), make LLM failures visible, handle facts that change without being declared, use open state-of-the-art methods and open models, and give honest benchmarks.

**Done:**
1. **No silent mock LLM.**
   - `UnavailableLLMClient` raises an error instead of returning fabricated output; the API returns 503 `llm_unavailable`.
   - Services re-raise `LLMError`.
   - Production refuses the mock LLM.
   - Commit `cea65b2`.
2. **Time correctness.**
   - `event_time` is accepted at ingest (API and both SDKs).
   - Recency is computed from event time.
   - Access no longer refreshes recency.
   - Commit `ffe4c69`.
3. **Answer-level evaluation** (`bench/answer_eval.py`):
   - LongMemEval's official reader and judge prompts, verbatim (MIT).
   - Reader qwen2.5:7b-instruct; judge gemma4, a different family.
   - EM and token F1 as well, and bootstrap CIs.
   - Pre-registered dev/test split (`sha256(qid)[0] % 2`). Tune on dev only; test is reported once.
4. **Harness bug caught before any numbers were reported.**
   - The oracle context was truncated at 28k chars in 43% of questions, dropping later sessions.
   - Now only the longest turns are shortened and sessions are never dropped (`num_ctx` 32k).
5. **Root cause of trailing BM25.**
   - Hybrid search fused rankings with RRF, then re-sorted by 0.85·cosine + 0.15·BM25, so ranking was effectively dense-only.
   - Added `hybrid_fusion` (blend / convex / rrf).
   - Dev-split recall@5 vs BM25 (238 q, all-minilm):

| Fusion | vs BM25 |
|---|---|
| blend | −3.7 pts [−8.2, +0.8] |
| rrf | −1.9 |
| convex 0.5 | +1.7 |
| **convex 0.7** | **+3.6 [+0.9, +6.4]** |
| convex 0.8 | +2.8 |
| convex 0.9 | +1.1 |

   - Knowledge-update gap: −24 → −4 pts.
   - The default is changed only after a cross-dataset regression check (LoCoMo, BEIR).
6. **Time-aware context** (`domain/memory/context.py`): memories are shown oldest first, with dates, and a note that later entries are current. Measured on its own by the `*_ctx` QA setups (same turns, same prompt).
7. **Answer accuracy, LongMemEval dev split** (256 q; reader qwen2.5-7B, judge gemma4, official prompts, 95% CIs).

   | Setup | Judged accuracy |
   |---|---|
   | no memory | 5.5% |
   | dense | 47.3% |
   | BM25 | 53.5% |
   | AegisMem | 53.9% [47.7, 59.8] |
   | AegisMem + time-aware context | 55.1% |
   | oracle | 59.4% |

   - AegisMem vs dense: **+6.6 [+0.8, +12.5]**, significant.
   - AegisMem vs BM25: +0.4 [−3.9, +5.1], a tie.
   - Time-aware context: +1.2 [−3.5, +5.1], not significant.
   - Knowledge update: 74% (aegis_ctx 86%, oracle 71%).
   - Weakest types: multi-session (33%) and temporal reasoning (38%).
   - **Judge bug caught:** gemma4 "thinking" consumed `num_predict=8` and returned empty text, which was scored as "no" (judged accuracy about 0%). Fixed with `think: false`; empty output now raises an error; verdicts must start with yes or no.

## Session 12 — 2026-10-21: Pivot to a free Chrome extension (v0.1 built)

**Decision (user):** make AegisMem a free Chrome extension, not a repository users clone. It should capture context from conversations, categorize it, learn about the user, and be encrypted so that even AegisMem cannot read it. A desktop app (Tauri + MCP) comes later as a companion. Deadlines should be tighter.

**Built** (`extension/`, branch `feature/chrome-extension`, commit `4f14934`):
- **Vault.** Zero-knowledge encryption: AES-256-GCM data key, wrapped by a PBKDF2-600k passphrase key and by a recovery key. Storage is IndexedDB, ciphertext only.
- **Capture.** First-person facts from the user's own messages on ChatGPT and Claude, opt-in per site. Includes on-device PII redaction and rule-based injection screening, so held items go to Review.
- **Updates.** Slot-based linking for single-valued facts (residence, employer, diet, relationship).
- **Recall.** BM25, plus a visible "＋ Memories" insertion into the draft.
- **Side panel.** View, edit, recategorize, delete with verified removal, export, wipe, lock.
- **Trust.** Only extension pages are trusted (by origin); web pages can only capture and request context.
- **Tests.** 10 unit tests, plus a real-Chromium end-to-end test (stand-in chatgpt.com page) that passed 3/3.

**Bugs found by the tests:**
- The trust check used `sender.tab`, which locked out the panel when opened in a tab. Fixed: check by origin.
- Health keywords had a trailing word boundary, so "allergic" never matched.
- Word-overlap update linking missed "live in Austin" → "live in Denver". Replaced by slots.

**Next:**
- On-device embeddings with hybrid fusion (port of the validated convex 0.7).
- On-device categorization model, evaluated on real data.
- Store listing and privacy policy.

## Session 13 — 2026-10-21: Extension v0.2, a finished, measured product

**User directive:** complete the extension end to end without stopping; log every change and decision.

**Built:**
- **On-device smart search.**
  - all-MiniLM-L6-v2 (int8 ONNX, 23 MB, sha256 `afdb6f1a…`) bundled with ONNX Runtime Web, running in an MV3 offscreen document.
  - Hybrid ranking: min-max BM25 and cosine, 0.7 lexical weight (the configuration validated in Session 11).
  - **Decision:** bundle the model and runtime instead of downloading at runtime. MV3 forbids remote code, and the product must work offline.
- **Keyword-only fallback is visible.** If the model fails, the panel shows "keyword search only". The model error is surfaced, never swallowed.
- **Capture rule rewritten after measurement.**
  - The v0.1 cue-word allow-list captured **0%** of the gold evidence on the first LongMemEval questions.
  - It is now a block-list: questions, requests to the AI, small talk, and reactions to the AI's reply.
  - Evidence capture went from 0% to 86–88%.
- **Noise filter for reactions** ("I like these ideas"). Measured trade-off on dev: memories per user 295 → 271, hit@5 81.5 → 80.7 (not significant). Kept.
- **Categories.**
  - Keyword rules, plus a meaning-based fallback (nearest category examples, threshold 0.25).
  - Author audit of 60 real memories: coverage 38% → 68%, precision about 63%.
  - Documented as a browsing convenience, not a quality claim.
- **Sites.** Gemini and Perplexity adapters added (beta, unverified against the live sites).
- **Capture at Enter.** A second, selector-independent capture path. Inserted memory blocks are never re-captured.
- **Settings and safety.** Auto-lock (alarms, default 30 min), passphrase change, recovery, a search box in the panel, a welcome tab on install.
- **Store readiness.** Icons, `store/PRIVACY.md` (no data collected), `store/LISTING.md`, `npm run package` producing a 23 MB zip (v0.2.0).
- **Security.** The trust rule was extracted to `src/trust.ts` and unit-tested. Content scripts may only use `status`, `capture` and `context`.

**Tests:**
- 12 unit tests.
- An end-to-end test in real Chromium. It covers: model loads; vault setup; capture on ChatGPT; injection held for Review; semantic recall among 13 memories; insertion; ciphertext only at rest; delete; Enter capture on Claude; no re-capture; lock/unlock persistence; passphrase change.
- Removed a trivial e2e step ("web page can't export") that passed for the wrong reason. Replaced by a unit test of the real rule.

**Measured** (extension pipeline, LongMemEval-S, tuned on dev, **test split run once**, 232 q):

| System | hit@5 |
|---|---|
| Hybrid | **78.4% [72.0, 83.6]** |
| Keyword only | 71.6% |
| Meaning only | 80.2% |
| Raw BM25 | 70.3% |

- Hybrid vs keyword-only: **+6.9 [+3.4, +9.9]**.
- Meaning-only scored above hybrid on test (not significant). Not re-tuned on test.
- Structural miss: evidence only in AI replies (3%), by design.

**Bugs found by tests and measurement:**
- The ORT runtime required the `asyncify` WASM variant; the model failed to load in the extension.
- Weak tests were fixed: the semantic test with only 3 memories, and the racy review-tab check.

**Remaining before public launch:**
- Verify the four site adapters against the live sites, logged in.
- Create the Chrome Web Store developer account and submit (user action).
- Optionally, an on-device LLM (Chrome built-in AI) for categorization and fact extraction, measured first.

## Session 14 — 2026-10-28: Pivot to "AegisMem Recall" (search and port your AI chats)

**Why:** an honest review rated the v0.2 "facts about me" extension 4/10. Built-in memory in ChatGPT, Claude and Gemini already covers that, for free.

**Research findings:**
- Demand for cross-AI chat search is visible, but there are competitors: LLMnesia, Echoes (about 10k users), ChatEngram, llm-history-search, AI Memory, ChatTrack.
- Export formats for ChatGPT (`mapping` tree + `current_node`, split files), Claude (`chat_messages` with human/assistant senders) and Gemini Takeout (`MyActivity.json`, `details` vs `userInteractions` variants) are undocumented.
- Store listings report malicious extensions stealing AI chats, so trust is a buying factor.

**Decision:** build Recall with five *verifiable* differentiators.
- **D1:** published search benchmark.
- **D2:** import of the full history.
- **D3:** continue in another AI.
- **D4:** CSP-enforced zero network access, with history never rendered into third-party pages.
- **D5:** speed.

The plan is in `docs/RECALL_ROADMAP.md`. The v0.2 memory feature is dropped; its code stays in git history. Branch: `feature/recall`.

### Session 14 — build log (Recall)

**Architecture decisions:**
- **Library host.** The library lives in the offscreen document; the service worker is only a router and gatekeeper.
  - *Why:* MV3 service workers die when idle, which would mean decrypting and re-indexing the whole history on every wake.
- **Search UI only on extension pages** (popup and full app), never as an overlay on AI sites.
  - *Why:* chatgpt.com scripts could read Claude history rendered into their page.
- **Content scripts** may only `captureConv` and `takeHandoff` (`src/trust.ts`, unit-tested).
- **Default encryption:** a device-bound, non-extractable AES-GCM key, so there's no passphrase friction. Passphrase mode is optional and switchable, with re-encryption on switch.
- **Strict CSP on extension pages** (`connect-src 'self'`): pages *cannot* reach the network. Verified in e2e.
- **Embedding.** The model runs in a dedicated worker with a priority queue: queries go ahead of bulk work, in 16-chunk slices. Cross-origin isolation enables multi-threaded WASM.
  - Measured in Chrome (CPU shared with another benchmark): 5 → 20 chunks/s.
  - Before this change, background indexing blocked saving: 150 conversations took 97–360 s to save.
- **Import UX.** Conversations are saved and keyword-searchable immediately; meaning vectors are added in the background, with a progress badge.

**Bugs caught by tests (all fixed):**
- Re-import marked unchanged conversations as updated when no model was present.
- Results showed "Matched the title" instead of the best message snippet.
- **Handoff race:** the tab loaded before the handoff was recorded.
- **Handoff lost on interstitial pages:** a login wall or 403 page consumed it. It is now claimed only once the editor exists.
- Inline `style` attributes were silently blocked by the strict CSP. Styles are now set via CSSOM.
- Meaning search returned every conversation. Added a cosine floor (0.25) and a relative cutoff (0.3 × top).

**Tests:**
- 21 unit tests: importers including branches, split files, zip and the 3 Gemini variants; both key modes; backup; handoff; trust.
- A 21-step real-Chromium e2e (stable 3/3).

### Session 14 — measurement and release candidate

**"Find that chat" benchmark.** LongMemEval-S, about 10k conversations per split, tuned on dev, test run once.

| Split | System | Ranked first | Top 5 |
|---|---|---|---|
| Dev | Keyword | 38.7% | 63.0% |
| Dev | MiniLM meaning | 23.5% | 45.0% |
| Dev | MiniLM hybrid | 37.8% | 62.6% |
| Dev | arctic-xs meaning | 26.5% | 50.4% |
| Dev | **arctic-xs hybrid 0.7** | **38.7%** | **64.7%** |
| **Test (232 q)** | **Hybrid** | **34.1% [28.0, 39.2]** | **56.0%** |
| Test | Keyword | 32.3% | 56.5% |
| Test | Meaning | 26.3% | 50.0% |

- **Honest result:** hybrid ≈ keyword on this benchmark (+1.7 ranked first, CI [−0.4, +3.9]).
- **Not claimed:** "smart search beats keyword". LongMemEval questions reuse the chat's own words.
- **Decision:** ship arctic-embed-xs (Apache-2.0, 22M params; better than MiniLM on dev meaning search).
- **Tuning experiments that did not beat the baseline on dev:** role weighting, top-3 aggregation, BM25 k1/b. Not adopted.
- **Performance:**
  - Contiguous int8 vectors plus heap top-K: latency p95 225 → **145 ms** at about 137k passages.
  - Embedding moved to a worker with a priority queue.
  - Cross-origin isolation enables multi-threaded WASM, measured at about 4× faster indexing in Chrome.

**Docs:**
- `extension/README.md`: measured results and limitations.
- `store/LISTING.md`, `store/PRIVACY.md`, 4 store screenshots.
- `store/landing/index.html`: a local landing page, **not published**.

## Session 15 — 2026-11-04: Restructure into the Aegis monorepo

**Decision:** One umbrella repo, "Aegis", holding AegisMem, AegisTrace and later shared code. Branch `restructure/aegis-monorepo`, not pushed.

- `AegisMem/server/`: the Python backend moved as one block (core, domain, adapters, services, apps, infra, tests, bench, sdk, integrations, audit, pyproject). Its imports and Docker paths are unchanged because they're relative to this folder.
- `mem/extension/`: the Chrome extension. `mem/site/`: the Next.js marketing site.
- `trace/`: empty, for AegisTrace. `shared/`: planned. Code moves there only once both products use it.
- CI and release workflows now point at `mem/server`.
- Verified after the move: backend 263 passed / 4 skipped (same as before), extension 22/22 unit tests, site `next build` OK.
- Not done: renaming the GitHub repo and the local folder (needs the owner's approval). The roughly 222 untracked "* 2.*" files are iCloud duplicates; left untouched, delete manually.
- Follow-up: top-level folders renamed to `AegisMem/` and `AegisTrace/` so the GitHub repo `Aegis` holds both by name.
