# AegisMem architecture

AegisMem is the trust layer for agent memory: one FastAPI service in front of durable stores.

```
client / SDK / MCP / framework tools
        │  API key (scoped, tenant-bound) · rate limits · size limits · audit trail
        ▼
FastAPI ── ingest ──► PII redaction ► provenance + learned trust ► rule + risk-model screening ► store | quarantine
        └─ retrieve ► dense + BM25 (RRF) ► integrity guard (current? expired? quarantined? erased? trusted?
                      right tenant?) ► learned ranking ► agent
        └─ outcomes (approve / reject / correct / confirm / used) ► event log ► trust · risk · ranking models
        └─ forget ► cascade (versions, derivatives, duplicates) across stores ► signed receipt
```

| Layer | Path | Responsibility |
|---|---|---|
| API | `apps/api` | routes, auth/scopes, idempotency, rate limits, hardening, audit |
| Services | `services/` | ingest, retrieve, guard, erasure, outcomes, handoff, feedback, learning runtime, vector sync |
| Domain | `domain/` | pure logic: provenance, receipts, scoring, lexical/RRF, redaction, learners, metrics |
| Adapters | `adapters/` | Postgres (+RLS), pgvector, Qdrant, Neo4j, in-memory dev stores, tenancy wrappers |

Storage: Postgres holds canonical memories, the control plane (event log, receipts, keys, audit, outbox) and,
in single-store mode, vectors (pgvector). Qdrant and Neo4j are optional. Development runs with zero
infrastructure. Deployment: `docs/DEPLOYMENT.md`. Decisions: `docs/adr/`.
