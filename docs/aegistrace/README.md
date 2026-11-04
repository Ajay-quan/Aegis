# AegisTrace

Secure execution and verification infrastructure for AI agents. Every consequential agent action is:

- **governed** before it executes (default-deny policy enforced outside the model),
- **recorded** durably (an append-only, hash-chained event log in PostgreSQL), and
- **independently verifiable** (Ed25519-signed checkpoints, portable receipts, an offline verifier, and an external anchor).

All commands run from the repository root.

> **Status: pre-release, 0.1.0.dev0.** All verification so far is local. There has been no independent security review and CI has not run on GitHub. See [docs/product/PROGRESS.md](product/PROGRESS.md) and [docs/product/OPEN_ISSUES.md](product/OPEN_ISSUES.md).

## Quick start

Requires Docker, [uv](https://docs.astral.sh/uv/), and Node 22 (for the dashboard and TypeScript SDK).

```bash
docker compose up -d --wait postgres redis opa
uv sync
uv run python scripts/dev_bootstrap.py      # dev-only keys, token issuer, tenant, tokens in .dev/
docker compose up -d --build --wait         # migrations, api, worker, dispatcher
./examples/quickstart/run.sh                # register agent, grant tool, run, export receipt, verify offline, replay
```

No paid LLM access is needed; the deterministic mock model drives the demos.

## What is in the box

| | |
|---|---|
| API | FastAPI, versioned `/v1`; OpenAPI in [docs/api/aegistrace-openapi.json](../api/aegistrace-openapi.json) |
| Isolation | PostgreSQL forced row-level security; tenant taken only from the signed token |
| Orchestration | Explicit state machine, transactional outbox → Redis Streams, leases with fencing tokens, recovery, reconciliation |
| Authorization | OPA/Rego default deny; grants; human approvals bound to exact action digests |
| Evidence | RFC 8785 canonical JSON, domain-separated SHA-256 chain, Ed25519 checkpoints, receipt bundles, offline `aegistrace-verify` |
| Agents and tools | Mock and OpenAI-compatible models; MCP (stdio) bridge; egress-controlled HTTP; Docker sandbox for untrusted code |
| Replay | State reconstruction and decision replay with no I/O (enforced); authorized forks |
| Interfaces | Python SDK (sync/async), TypeScript SDK, `aegistrace` CLI (`apps/cli`), Next.js dashboard (`apps/studio`) |
| Code | `packages/aegistrace` (evidence, metrics, insights), `packages/aegisguard` (policy, rules, identity, sandbox), `packages/aegisruntime` (runs, approvals, gateway, agents, replay, workers), `apps/api` |
| Ops | Prometheus metrics, redacting JSON logs, k8s manifests, Terraform (AWS reference, not applied) |

## Tests

```bash
./scripts/test_db.sh && uv run pytest     # 155 tests: unit, property, fuzz, security, integration, e2e, contract, failure injection
uv run aegistrace policy test             # Rego tests
pnpm install && pnpm --filter @aegistrace/sdk test
(cd apps/studio && npx next build && npx playwright test)   # needs AEGIS_TOKEN
```

## Documentation

- Architecture: [docs/architecture/](../architecture/aegistrace/)
- Security: [threat model](security/THREAT_MODEL.md), [trust boundaries](security/TRUST_BOUNDARIES.md), [sandbox](security/SANDBOX.md), [MCP](security/MCP_SECURITY.md)
- Cryptography: [protocol](cryptography/PROTOCOL.md), [trust model](cryptography/TRUST_MODEL.md)
- [Replay](replay/REPLAY.md)
- Operations: [runbook](../deployment/aegistrace/RUNBOOK.md), [incident response](../deployment/aegistrace/INCIDENT_RESPONSE.md)
- [Benchmarks](tests/performance/REPORT.md) (measured on a laptop; read the limitations)

## License

Dual-licensed: the offline verifier, CLI, SDKs, policies and examples are **Apache-2.0**; the server and dashboard are **FSL-1.1-ALv2** (Functional Source License; each version becomes Apache-2.0 two years after release). See [LICENSE](../../LICENSE).
