# Existing system: verified inventory (2026-11-16)

Everything here was checked in the repository on this date. "Verified" means exercised by a test or run in
this session; see `project_log.md` for evidence.

## Repository
```
Aegis/
  AegisMem/
    server/      Python 3.11+, FastAPI. Memory service, benchmarks, Python/TS SDKs, MCP + LangChain integrations
    extension/   Chrome MV3 extension "Recall" (TypeScript): local encrypted chat search
    site/        Next.js marketing site (older copy; superseded by the Studio welcome page)
  AegisTrace/
    packages/core       Python 3.12 platform: API, workers, dispatcher, signer, dev identity provider, CLI
    packages/sdk-python, packages/sdk-typescript
    apps/dashboard      Next.js 16 (App Router), Tailwind 4: today's Studio UI + public welcome page
    migrations/         Alembic 0001–0006 (Postgres, row-level security)
    policies/           OPA/Rego (tools-v2)
  compose.yaml, aegis   one-command local stack (./aegis up | demo | test | rotate-keys | down)
  .github/workflows     aegismem-server, aegismem-extension, aegistrace, integration, release
```

## AegisMem server (`/api/v1`)
| Area | Endpoints |
|---|---|
| Memory | `POST /ingest`, `/ingest/batch`, `/retrieve`, `/memories/list`, `/update`; `GET/DELETE /memories/{id}` |
| Reasoning | `POST /reflect`, `/contradictions/scan`; `GET /contradictions`; `POST /handoff` |
| Learning | `POST /feedback`, `/corrections`, `/memories/{id}/confirm`; `GET/DELETE /learning/{user}`; `GET /trust/sources`, `/risk-model` |
| Integrity | `POST /forget` (signed erasure receipt), `GET /receipts/{id}`, `POST /receipts/verify`; quarantine list/release/reject |
| Admin | `POST/GET /admin/keys`, `DELETE /admin/keys/{id}`, `GET /admin/audit` |
| Evaluation | `POST /eval/run`, `/eval/retrieval`, `/eval/contradiction` |
| Ops | `GET /stats`, `/health`, `/metrics` |

- Auth: API keys `aem_<id>_<secret>`, peppered HMAC-SHA256 stored, plaintext shown once; scopes `memory:read|write`, `review`, `privacy`, `admin`; unmapped routes fail closed. **In the local compose stack auth is off** (internal network only).
- Storage: in-memory (dev) or Postgres + pgvector; optional Qdrant and Neo4j adapters; Redis; control DB for keys, receipts and audit.
- LLM adapters: Ollama (default local), OpenAI, Anthropic, mock. Embeddings: mock, OpenAI-compatible, sentence-transformers.

## AegisTrace (`/v1`)
| Area | Endpoints |
|---|---|
| Projects and agents | `POST /projects`; `POST/GET /agents`; `GET/PUT /agents/{id}/grants`, `DELETE …/grants/{tool}`; `GET /tools` |
| Policy | `POST /policy/simulate`; `GET/PUT /rules`, `/rules/history`, `GET/POST /rules/file`; `GET /policy-decisions` |
| Runs | `POST/GET /runs`; `GET /runs/{id}`, `/events`, `/replay`, `/verification`, `/receipt`, `/data-status`; `POST /runs/{id}/cancel`, `/reconcile`, `/checkpoints`, `/fork` |
| Approvals | `GET /approvals`; `POST /approvals/{id}/decision` |
| Privacy | `POST /runs/{id}/erase`, `/data/erase`; `PUT /runs/{id}/legal-hold`; `GET /erasures` |
| Memory (via AegisMem) | `GET /memory/{subject}` |
| Insight | `GET /stats`, `/stats/timeseries`, `/insights`, `/signing-keys` |
| Auth | `POST /auth/logout` (JWT revocation) |

- Auth: OIDC JWTs only (any provider; a dev provider ships for local use). Scopes per action. Tenant = organization, enforced by Postgres RLS. **No API keys.**
- Services: API, worker(s), dispatcher, signer (keys; no network), OPA, Postgres, Redis; optional Prometheus/Tempo/Grafana.
- Tables: tenants, projects, agents, runs, events, checkpoints, outbox, idempotency_keys, tool_grants, policy_decisions, approvals, tenant_rules(+history), payload_keys, erasures.

## Studio UI today (`AegisTrace/apps/dashboard`)
`/welcome` (public), `/login`, `/` overview, `/insights`, `/runs`, `/runs/[id]`, `/approvals`, `/agents`, `/rules`, `/memory`, `/security`, `/operations`. A same-origin, allowlisted proxy (`/api/aegis/*`) keeps tokens server-side.

## Verified quality gates
- CI on GitHub is green: AegisMem server, AegisTrace Python and TypeScript, supply chain (gitleaks, Trivy, SBOM), and AegisMem↔AegisTrace integration.
- Local: AegisTrace pytest 218 pass, 1 skipped (live-AegisMem contract, which runs in CI); Playwright 10/10; extension 22/22; AegisMem server 263 pass.
- Distributed recovery: 7,334/7,334 runs verified (`AegisTrace/docs/benchmarks/DISTRIBUTED.md`).
