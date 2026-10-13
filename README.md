# AegisMem

**The trust layer for AI agent memory.**

Agents are getting long-term memory faster than companies can trust it. AegisMem makes sure that what an
agent remembers is **true, current, safe and provably erasable**, and it gets better with every human decision.

| Problem in typical agent memory | AegisMem |
|---|---|
| A prompt injection in a web page or tool result becomes a "fact" | Provenance + trust on every write; low-trust instruction-like content is **quarantined** |
| Updated or revoked facts keep being served | A **read-time guard** re-checks every result against the canonical record and swaps in the current version |
| "Delete" leaves copies, summaries and vectors behind | **Cascading erasure** across versions, derivatives, duplicates and every store, with a **signed receipt** |
| Screening rules never improve | **Continual learning** from reviewer decisions and corrections: calibrated per-origin trust, a self-improving risk model, learned ranking |
| Context is lost between agents and sessions | **Handoff packets**: token-budgeted, cited briefings with open questions and recent changes |
| Vector search misses names, ids and rare terms | **Hybrid retrieval**: dense + BM25 fused with Reciprocal Rank Fusion, then the integrity guard |
| Agents persist whatever they see, including PII | **PII redaction at ingest** (emails, phones, cards, SSNs, IPs, secrets) before embedding or storage |

Run the free [integrity audit](audit/) against any memory system to see where it stands. A typical naive
vector memory scores 1/7; AegisMem scores 7/7.

## Quickstart (no Docker)

```bash
pip install -e ".[dev]"
uvicorn apps.api.main:app        # zero infrastructure: in-memory stores and mock embeddings by default
```

```python
from aegismem_client import AegisMem          # pip install ./sdk/python

async with AegisMem("http://localhost:8000") as mem:
    await mem.ingest("User prefers aisle seats", user_id="u1")
    w = await mem.ingest(page_text, user_id="u1", source_type="tool_output", origin="domain:example.com")
    if w.quarantined: ...                     # held for review, never served as trusted memory
    r = await mem.retrieve("seat preference", user_id="u1")
    await mem.feedback(r.retrieval_id, user_id="u1", used=[r.results[0].memory_id])
    brief = await mem.handoff(user_id="u1", task="book a flight", token_budget=800)
    receipt = await mem.forget("u1", memory_ids=[...], reason="GDPR Art. 17 request")
```

Also available: a [TypeScript SDK](sdk/typescript), an [MCP server](integrations/mcp) for any MCP client,
[LangChain/LangGraph and OpenAI Agents tools](integrations/frameworks), a CLI (`python -m apps.cli`),
and production deployment with [Docker Compose or Kubernetes](docs/DEPLOYMENT.md).

## How it works

```
write ──► provenance + learned trust ──► rule + risk-model screening ──► store │ quarantine
                                                                                   │
read  ──► hybrid retrieval ──► integrity guard (current version? expired? quarantined?
                               erased? trusted enough? right tenant?) ──► learned ranking ──► agent
                                                                                   │
human outcomes (approve / reject / correct / confirm / used) ──► event log ──► trust, risk & ranking models
```

- **Event-sourced learning.** Every learned update is an append-only event; models are deterministic replays,
  consistent across replicas and rebuildable for audit. Risk-model events store keyed feature hashes, never text.
- **Multi-tenant by construction.** Scoped stores in the app, Postgres row-level security in the database,
  scoped API keys, per-tenant rate limits.
- **Operable.** Idempotent writes, a durable index-repair outbox, `/ready` probes, Prometheus metrics,
  OpenTelemetry traces (no content in telemetry), Alembic migrations.

## Measured, not claimed

All figures come from public, human-made datasets, measured on data never used for seeding or tuning,
with 95% bootstrap confidence intervals. Full report: [bench/VALIDATION.md](bench/VALIDATION.md)
(`python -m bench.validate && python -m bench.report`).

| What | Result (local all-minilm embeddings) |
|---|---|
| Revocation, 4,000 cases built from real conversation turns | **0** revoked memories served |
| Erasure, 2,000 subjects / 8,000 linked items | **0** residue, 100% cascade recall, 0 collateral |
| Write screening, cold start, held-out attacks | 22.8% macro detection at 0.03% false alarms; most *novel* indirect injections are caught only after learning from reviewer feedback |
| Memory recall, LongMemEval-S | being re-measured after the fusion fix (dev split: +3.6 pts recall@5 over BM25, CI [+0.9, +6.4]); test-split figures will be published once |
| Answer accuracy (does the agent answer correctly?) | in progress: LongMemEval official judge protocol, open local reader and judge |

Known gaps are listed in the report rather than hidden. `python -m bench.run` runs a small hand-written
smoke suite in CI as a regression gate. Its numbers are not a performance claim.

## Repository map

| Path | What |
|---|---|
| `apps/api` | FastAPI app, auth, idempotency, rate limits |
| `services/` | ingest, retrieve, guard, erasure, outcomes, handoff, feedback, learning runtime, vector sync |
| `domain/` | pure logic: provenance, receipts, scoring, trust calibrator, risk model, weight learner |
| `adapters/` | Postgres, pgvector, Qdrant, Neo4j, in-memory stores, tenancy wrappers |
| `bench/`, `audit/` | benchmark suite with gates; open-source integrity audit |
| `sdk/`, `integrations/mcp` | Python and TypeScript clients; MCP server |
| `infra/` | migrations, Dockerfile, compose, Kubernetes manifests |
| `ROADMAP.md`, `PRODUCT_PLAN_12M.md`, `project_log.md` | strategy, plan, engineering log |

## License

Apache-2.0
