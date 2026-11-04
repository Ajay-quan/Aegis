# AegisMem: 12-Month Product Plan (Nov 2026 – Oct 2027)

Owner: Product. Status: draft v1, 2026-10-10. Companion docs: `ROADMAP.md` (feature status), `project_log.md` (engineering history).

---

## 1. Thesis

**Agents are getting long-term memory faster than companies can trust it.** Every memory vendor optimises recall.
Nobody owns the question a security reviewer, DPO or CISO asks before approving memory in production:

> *What did the agent remember, where did it come from, can it be poisoned, will it act on revoked data, and can we prove we deleted it?*

**AegisMem is the trust layer for agent memory and context.** It sits between agents and whatever memory or context store they use,
and it gets smarter with every human decision.

**Scope expansion over the year** (each step reuses the same core):

```
Q1 Memory integrity (own store)  →  Q2 Integrity gateway for ANY memory store
→  Q3 Compliance-grade governance (audit, residency, crypto-erasure)  →  Q4 Context integrity platform
   (memory + RAG documents + tool outputs + agent-to-agent handoffs) with a cross-customer threat network
```

**Why now:**
- 2026 research documents >90% poisoning success.
- Revocation is not enforced by default in tested memory systems.
- Regulators (EDPB) prioritise erasure.
- MCP and A2A make agent-to-agent context sharing mainstream, which widens the attack surface.

## 2. Customer

**ICP (year 1):** companies with 200–5,000 employees shipping customer-facing or employee-facing agents in regulated or high-liability domains:
fintech and insurance support, health intake and care navigation, HR/benefits copilots, legal ops, B2B SaaS support with enterprise customers.

| Persona | Job to be done | What they buy |
|---|---|---|
| AI/platform engineer (user) | Ship memory without becoming the blocker in security review | SDK, gateway, adapters, 1-day integration |
| Security / AppSec (champion) | Prevent prompt-injection persistence and data leaks | Quarantine, risk model, threat intel, red-team |
| Privacy / DPO / Legal (economic veto) | Prove DSAR and erasure compliance | Receipts, crypto-erasure, audit exports, residency |
| Trust & Safety / Ops reviewer | Clear the review queue fast and accurately | Review console, explanations, learning that cuts the queue |

**Top pains, validated in design-partner interviews in Q1 (hypotheses until then):**
1. "Security won't sign off on long-term memory."
2. "We can't answer a DSAR for what the agent learned."
3. "Our agent repeated something a scraped page told it."
4. "Users corrected the bot and it went back to the old answer."
5. "Review queues are too noisy to staff."

## 3. Product principles (non-negotiable from Q1)

1. **No in-process state.** Every learned parameter, receipt, review and event is durable, versioned and tenant-scoped.
2. **Backend-agnostic.** Our value is integrity, not storage. We must work in front of Mem0, Zep, Letta, LangGraph, pgvector and Qdrant.
3. **Learning is gated.** Every learning loop ships in *shadow → canary → on*, with offline replay evals, per-tenant isolation, and one-click rollback to any prior model version.
4. **Explain everything.** Every hold, withhold, trust change and erasure has a machine-readable reason and an audit record.
5. **Fail closed on integrity, fail open on availability.** For example, if the guard cannot verify, it withholds; if the risk model is down, rules still apply.
6. **p95 overhead budget:** ≤ 25 ms added per retrieval and ≤ 40 ms per write (excluding embedding) at 1k RPS per tenant.

## 4. Quarter-by-quarter plan

### Q1 (Nov–Jan): Production core and first design partners
**Goal:** turn today's working prototype into a deployable, multi-tenant service that 3–5 design partners run on real traffic.

| Epic | Deliverables | Exit criteria |
|---|---|---|
| **Durable state** | Postgres schemas + Alembic migrations for: trust posteriors, risk-model versions (weights as versioned blobs), ranking weights, feedback events, retrieval ledger, quarantine reviews, erasure receipts, outcome events (append-only). Event-sourced learning: models are rebuildable from the outcome log. | Kill any pod → zero learning loss; rebuild any model from the event log deterministically |
| **Multi-tenancy & auth** | `tenant_id` on every row, index and vector payload; API keys with scopes (agent / reviewer / admin / auditor); row-level security in Postgres; per-tenant rate limits and quotas | Pen test: no cross-tenant read/write via any endpoint |
| **Single-store mode** | pgvector backend so one Postgres is enough; Qdrant and Neo4j optional | `docker compose up` with one DB; Helm chart |
| **Async pipeline** | Worker queue for embedding, contradiction scans, reflections and erasure cascades; idempotency keys on writes; outbox pattern for vector/graph sync | No dual-write drift under chaos test (kill between DB and vector write) |
| **Observability** | OpenTelemetry traces per memory op; Prometheus metrics (guard withhold rate, quarantine rate, review latency, erasure SLA); structured audit log | Dashboards + alerts shipped in the Helm chart |
| **Eval & benchmarks** | `aegis-bench`: injection set (public datasets + our red-team corpus, multilingual), revocation-leak suite, erasure-residue suite, retrieval quality (LongMemEval/LoCoMo) to show we don't hurt recall | Published numbers; CI fails on regression |
| **SDKs + MCP** | Python and TypeScript SDKs; MCP server exposing governed memory tools; LangGraph / LlamaIndex / OpenAI Agents SDK integrations | "Integrate in < 1 hour" measured with partners |
| **OSS Integrity Audit v1** | CLI that audits *any* memory API for revocation leaks, delete residue, poisoning acceptance and provenance laundering, with an HTML report | Run against 3 popular OSS memory systems; publish findings responsibly |

**Q1 metrics:** 3–5 design partners live; p95 overhead within budget; 0 cross-tenant incidents; audit tool 1k GitHub stars (vanity, but it is the top-of-funnel).

### Q2 (Feb–Apr): Integrity gateway, reviewer console, policy engine
**Goal:** be useful to teams that already chose a memory vendor, and make human review cheap.

| Epic | Deliverables |
|---|---|
| **Gateway + adapters** | Proxy / SDK-middleware mode in front of Mem0, Zep, Letta, LangGraph store, pgvector, Qdrant. We keep a provenance + status sidecar index; the guard and erasure work through adapter interfaces (`list_by_subject`, `delete`, `update_status`). Conformance test kit for new adapters. |
| **Reviewer console (web)** | Queue with explanations (trigger phrases, origin trust history), bulk actions, keyboard-first triage, SLAs, assignment, two-person rule for releases from low-trust origins, reviewer accuracy stats |
| **Policy engine** | Declarative per-tenant policies (YAML, versioned, dry-run): never-store classes (secrets, card numbers), retention per memory type, trust floors per source, residency tags, who can read what (agent-scoped ACLs) |
| **PII & secrets** | Detection at write time (pattern + NER + learned), redact / tokenize / block per policy; vault-style tokenization for reversible fields |
| **Risk model v2** | Embedding-based head on top of the n-gram model (paraphrase-robust); multilingual; per-tenant fine-tuning from reviews; shadow-mode comparison before promotion |
| **Reviewer-poisoning defence** | Per-reviewer weighting (agreement with consensus), audit trail of every label, quarantine of anomalous label bursts |
| **Receipts v2** | Ed25519-signed, publicly verifiable receipts; transparency log (Merkle tree) so customers can prove a receipt existed at time T |

**Q2 metrics:**
- 10 paying or LOI customers.
- Hosted beta launched.
- Review-queue size per 1k writes falls ≥ 40% from week 1 to week 8 per tenant (learning works).
- Reviewer false-positive rate below 20%.

### Q3 (May–Jul): Compliance-grade governance and agent-to-agent trust
**Goal:** pass enterprise procurement; own the "context handoff" moment between agents.

| Epic | Deliverables |
|---|---|
| **Crypto-erasure** | Per-subject data-encryption keys (envelope encryption, KMS/HSM). Forget = key destruction, which covers backups and replicas. Receipts state the key-destruction proof. |
| **DSAR toolkit** | Subject export (everything remembered about a person, with provenance), rectification and erasure workflows, deadline tracking |
| **Compliance packs** | GDPR, CCPA/CPRA and HIPAA mappings; data residency (EU/US regions); retention reports; SIEM export (Splunk, Datadog); SOC 2 Type I |
| **Enterprise identity** | SSO (SAML/OIDC), SCIM, fine-grained RBAC, customer-managed keys (BYOK) |
| **Signed handoff & memory contracts** | Handoff packets carry per-item provenance, trust and signature; receivers verify before use. A "memory contract" declares what one agent may read from or write to another's memory (A2A/MCP compatible). Multi-agent shared memory with scoped permissions. |
| **Continual learning v3** | Per-memory utility priors (Beta) used in ranking and in utility-driven forgetting; auto-expiry of time-bound facts from learned validity patterns; correction-driven "lessons" (procedural memories proposed from repeated corrections, human-approved) |

**Q3 metrics:**
- SOC 2 Type I complete.
- First enterprise contract (≥ $100k ARR).
- Erasure SLA p99 < 24h, with 100% of receipts verifiable.
- DSAR export in < 1 min per subject.

### Q4 (Aug–Oct): Context integrity platform and network effects
**Goal:** expand from "memory" to everything that enters an agent's context, and build a moat that compounds with customers.

| Epic | Deliverables |
|---|---|
| **Context firewall** | The same provenance, trust, risk and guard pipeline applied to RAG documents, tool outputs and web results *at prompt-assembly time* (not just at memory write). SDK hooks for major agent frameworks. |
| **Threat intelligence network** | Opt-in, privacy-preserving sharing of poisoning signals across tenants (origin reputation and attack-pattern fingerprints, never content). New tenants start protected by everyone's reviews. This is the moat. |
| **Continuous red-teaming** | Automated attack generation against each tenant's live policy and models (shadow traffic), with weekly risk reports and regression alerts |
| **Memory quality analytics** | Dashboards for staleness, contradiction rate, correction rate per source, recall impact of guard decisions, reviewer ROI |
| **Deployment options** | VPC / on-prem (Helm, Terraform, air-gapped models), SOC 2 Type II, ISO 27001 started |
| **Ecosystem** | Policy-pack and adapter marketplace; partner integrations with agent platforms and memory vendors (we make them enterprise-ready rather than competing) |

**Q4 metrics:**
- $1M+ ARR run-rate (target, not a forecast).
- 30+ production tenants.
- ≥ 50% of tenants opted into the threat network.
- Time-to-block for a new attack family across the network under 1 hour.

## 5. Continual learning across the year

| Loop | Signal | Learns | Status → plan |
|---|---|---|---|
| Source/origin trust | Releases, rejections, corrections, confirmations, usage | Whom to believe | Built (in-process) → Q1 durable + per-tenant → Q4 network-wide reputation |
| Write-risk model | Reviewer labels, missed-attack reports | What poisoning looks like | Built (n-gram) → Q2 embedding head and multilingual → Q4 shared fingerprints |
| Quarantine threshold | Reviewer precision | How strict to be | Built → Q2 per-source thresholds and cost-sensitive tuning (reviewer cost vs incident cost) |
| Ranking weights | Retrieval feedback | What helps this user | Built → Q1 offline replay gate → Q3 trust-weighted |
| Memory utility and forgetting | Used vs. ignored over time | What to keep | Q3 |
| Lessons / procedures | Repeated corrections | How to avoid repeat mistakes | Q3 (human-approved) |

**Safety gates for every loop:**
- Shadow mode and offline replay on the tenant's own event log.
- Canary rollout to 10% of traffic, with automatic rollback when guard-withhold or quarantine rates shift by more than 3σ.
- Versioned models with diff reports.
- Learning signals from quarantined or erased content are excluded or ring-fenced.
- Label provenance and reviewer weighting.

## 6. Metrics

**North star:** *Verified context operations per month.* These are memory and context reads and writes served with verified provenance and policy enforcement. The metric grows with usage and only counts what we uniquely do.

| Area | KPI | Target by Q4 |
|---|---|---|
| Safety | Missed attacks per 1k writes (red-team) | −80% vs. rules-only baseline |
| Cost | Review items per 1k writes | −60% from tenant week 1 to week 12 |
| Correctness | Revoked/superseded facts served | 0 in the revocation suite; < 0.01% in production audits |
| Compliance | Erasure SLA p99; receipts verifiable | < 24h; 100% |
| Performance | p95 added latency, read / write | ≤ 25 ms / ≤ 40 ms |
| Recall | LongMemEval delta with guard on | ≥ −1 pt (we must not hurt quality) |
| Business | Time to integrate; net revenue retention | < 1 day; > 120% |

## 7. Go-to-market and pricing (hypotheses to test)

- **Motion:** open-source audit tool and benchmark report → developer adoption of the OSS core → hosted gateway → enterprise compliance tier.
- **Packaging:**
  - **Open Core** (self-host, single tenant, rules plus local learning).
  - **Team** (hosted, usage-based on verified operations, review console, adapters).
  - **Enterprise** (crypto-erasure, residency, SSO, BYOK, SIEM, threat network, SLA, VPC deploy).
- **Design partners (Q1):** 5 companies across fintech support, health intake, HR copilot, legal ops and B2B SaaS. They get free usage for 6 months in exchange for weekly feedback and a case study.
- **Partnerships:** memory vendors (we are their enterprise-compliance answer), agent platforms, and GRC/privacy platforms (OneTrust-style DSAR integrations).
- **Content:** the quarterly "State of Agent Memory Integrity" report, built from audit-tool data. It positions us as the category definer.

## 8. Team plan

| Quarter | Hires (cumulative core team) |
|---|---|
| Q1 | Founding backend/infra engineer, ML engineer (risk models, evals), design-partner lead (founder-led sales) |
| Q2 | Frontend engineer (console), security engineer (pen testing, crypto), developer advocate |
| Q3 | Compliance/GRC lead (SOC 2, DPAs), second backend engineer, first AE |
| Q4 | SRE, solutions engineer, second ML engineer (threat network) |

## 9. Risks

| Risk | Mitigation |
|---|---|
| Memory vendors build integrity in-house | Be backend-agnostic and partner-first; the threat network and compliance artifacts are hard for a single vendor to match |
| Foundation-model providers ship native memory with governance | Extend to context integrity (Q4), which spans providers; enterprises want vendor-neutral controls |
| Learning loops get poisoned (reviewers, usage signals) | Reviewer weighting, label audit, shadow/canary gates, caps on low-cost positive signals |
| Latency overhead kills adoption | Hard p95 budget in CI; cached trust lookups; async heavy paths |
| False positives frustrate users | Trust-scaled thresholds, per-tenant learning, fast review UX, measured FP KPI |
| Compliance claims overreach | Precise receipt semantics (`not_covered` field), external legal review, SOC 2 auditors |

## 10. Next 30 days

1. **Week 1–2:**
   - Durable state migration (trust, risk-model versions, receipts, reviews, outcome event log), with an event-sourced rebuild test.
   - `tenant_id` threading plus API-key auth.
2. **Week 2–3:**
   - pgvector single-store mode.
   - Outbox-based vector sync.
   - Remove the four remaining in-process singletons.
3. **Week 3–4:**
   - `aegis-bench` v0 (injection, revocation, erasure suites) in CI.
   - OSS audit CLI skeleton.
   - Recruit 5 design partners. The interview script focuses on the five pains in §2.

Decision needed from founders: hosted-first or self-host-first for design partners. The recommendation is **hosted for speed with a VPC option**,
because regulated partners will ask for VPC by Q2 anyway.
