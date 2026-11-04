# AegisMem Product Roadmap

## Positioning (revised 2026-10-10)

**AegisMem is the integrity layer for agent memory.** It doesn't compete on recall; Mem0, Zep, Letta,
Cognee and Supermemory have that covered. It answers the questions those systems leave open once memory
holds real customer data:

- *Can a poisoned web page or tool output become a "fact" my agent trusts?* (poisoning, provenance laundering)
- *Will my agent act on information that was revoked or replaced?* ("revoked but still authoritative")
- *When a user says "forget me", can I prove it, including summaries and copies?* (GDPR Art. 17, CCPA)
- *When context moves between agents, what can the receiver trust?* (handoff)

**Why this niche:** 2026 research shows the problems are real and unsolved in shipping products:
- Memory poisoning attacks succeed above 90% in controlled settings.
- An empirical study found that none of five soft-revocation memory systems enforced revocation by default.
- Surveys note that no evaluated store satisfies both forensic retention and verified deletion.

Existing offerings are fragments:
- SurrealDB sells provenance and a forget verb in its Enterprise tier.
- Attestari is a small open-source package.
- SuperLocalMemory is a research prototype.

Nobody owns the "trust and compliance layer" as a product.

**Buyer:** teams shipping agents in regulated or high-stakes settings (fintech and insurance support, health
intake, HR, legal, enterprise copilots), where a security or privacy review currently blocks long-term memory.

**Wedge, then platform:**
1. Open-source **integrity audit** that runs against *any* memory backend and reports revocation leaks,
   residual data after delete, and poisoning acceptance. It's free, it's shareable, and it creates the problem awareness.
2. **AegisMem gateway** sits between agents and their memory store (its own store today; Mem0, Zep and pgvector
   adapters next) and enforces provenance, quarantine, read-time guarding and verifiable erasure.
3. Paid: hosted gateway, audit exports, a DPA-ready erasure-receipt ledger, policy packs per regulation, SSO.

## What is built (P1)

| Capability | Where | Status |
|---|---|---|
| Provenance + trust on every write, non-amplification for derived memories | `domain/integrity/provenance.py`, `services/ingest_service.py` | done |
| Quarantine of low-trust, instruction-like content plus review/release API | same; `GET /quarantine/{user}`, `POST /quarantine/{id}/release` | done |
| Read-time guard: canonical re-check, successor substitution, expiry, owner check, trust floor, `guard_report` | `services/guard_service.py`, wired into `RetrievalService` | done |
| Cascading verifiable erasure: versions, derivatives, duplicates, all stores, signed receipts | `services/erasure_service.py`; `POST /forget`, `/receipts/*` | done |
| Handoff packet (budgeted, cited, includes open questions and changes) | `services/handoff_service.py`; `POST /handoff` | done |
| Retrieval feedback and per-user learned ranking weights | `domain/learning/`, `services/feedback_service.py` | done |
| **Outcome-calibrated trust** (continual learning from reviews, corrections, confirmations and usage; retroactive distrust) | `domain/learning/trust_calibrator.py`, `services/outcome_service.py`; `/corrections`, `/memories/{id}/confirm`, `/quarantine/{id}/reject`, `/trust/sources` | done |

## Q1 production core status
**Q1 engineering complete (100%)**, verified on real infrastructure. See `project_log.md` Session 8. Shipped on branch `q1/production-core`: durable event-sourced learning state,
multi-tenancy with API-key auth and Postgres RLS, rate limits, aegis-bench with CI gates, Python + TypeScript SDKs,
MCP server, aegis-audit, pgvector single-store mode, idempotent writes + index-repair outbox, metrics/tracing/readiness,
Docker/Compose/Kubernetes deployment.

## Next (P1 completion, original list)
- [ ] Persist receipts, quarantine decisions, learner state and the feedback ledger in Postgres (Alembic migration).
- [ ] `scripts/integrity_audit.py`: backend-agnostic audit suite (revocation leak, delete residue, poisoning acceptance,
      laundering through reflection). Run it against AegisMem and publish the numbers.
- [ ] Signed handoff packets: provenance + trust per item, with an HMAC so the receiving agent can verify origin.
- [ ] Ed25519 receipts so third parties (auditors, users) can verify without the server key.
- [ ] Single-Postgres (pgvector) deployment mode; four stores is too much for first users.

## P2: Gateway and adapters
- Adapters that put the guard and erasure in front of Mem0, Zep and raw pgvector or Qdrant.
- Policy engine: per-tenant trust floors, retention windows, PII classes, and "never store" rules.
- Memory utility priors and utility-driven forgetting (continual-learning layer 2).
- Python and TypeScript SDKs, plus an MCP server so any agent can mount governed memory.

## P3: Enterprise
- Multi-tenant auth and quotas, audit-log export (SIEM), erasure SLA dashboards, SOC 2 readiness.
- Procedural learning from successful patterns (continual-learning layer 3), with human review.

## Continual learning (model weights stay frozen)
1. **Outcome-calibrated trust (built, flagship).** Reviewer approvals and rejections, user corrections (`wrong` vs `outdated`),
   confirmations and usage update a Beta posterior per source and origin (tool, domain, connector). Learned trust is shared
   across users, so one rejection protects everyone. It is applied at write time and **retroactively at read time**, so
   past memories from a newly distrusted origin stop being served immediately. Corrections flag derived memories.
   Expected effect: fewer items need review over time, and poisoned origins are shut out quickly.
2. **Self-improving write-risk model (built).** Reviewer releases, rejections and `malicious` reports train a per-deployment
   online classifier (hashed n-grams, AdaGrad logistic regression, seeded for day one). The quarantine threshold scales with
   source trust and tunes itself from reviewer precision, and every hold names its trigger phrases. KPIs: reviewer false-positive rate ↓,
   missed attacks per 1k writes ↓, time-to-block for a new attack family. `GET /risk-model`.
3. **Ranking-weight learning (built).** Per-user online weights from retrieval feedback.
4. **Next:** trust-weighted ranking updates; per-memory utility priors and forgetting; an auto-tuned quarantine threshold from
   reviewer precision; procedural memories from repeated successful patterns (with review).

Quarantined or erased memories are never served, so they never produce training signal.

## Non-goals
- Being the best general-purpose recall engine. Integrate with those instead.
- Fine-tuning on user data.
