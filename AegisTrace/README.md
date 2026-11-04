# AegisTrace

Secure execution and verification infrastructure for AI agents. Every consequential agent action is:

- **governed** before it executes (default-deny policy enforced outside the model),
- **recorded** durably (an append-only, hash-chained event log in PostgreSQL), and
- **independently verifiable** (Ed25519-signed checkpoints, portable receipts, an offline verifier, and an external anchor).

> **Status: pre-release, 0.1.0.dev0.** All verification so far is local. There has been no independent security review and CI has not run on GitHub. See [docs/product/PROGRESS.md](docs/product/PROGRESS.md) and [docs/product/OPEN_ISSUES.md](docs/product/OPEN_ISSUES.md).

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
| API | FastAPI, versioned `/v1`; OpenAPI in [docs/api/openapi.json](docs/api/openapi.json) |
| Isolation | PostgreSQL forced row-level security; tenant taken only from the signed token |
| Orchestration | Explicit state machine, transactional outbox → Redis Streams, leases with fencing tokens, recovery, reconciliation |
| Authorization | OPA/Rego default deny; grants; human approvals bound to exact action digests |
| Evidence | RFC 8785 canonical JSON, domain-separated SHA-256 chain, Ed25519 checkpoints, receipt bundles, offline `aegistrace-verify` |
| Agents and tools | Mock and OpenAI-compatible models; MCP (stdio) bridge; egress-controlled HTTP; Docker sandbox for untrusted code |
| Replay | State reconstruction and decision replay with no I/O (enforced); authorized forks |
| Interfaces | Python SDK (sync/async), TypeScript SDK, `aegistrace` CLI, Next.js dashboard |
| Ops | Prometheus metrics, redacting JSON logs, k8s manifests, Terraform (AWS reference, not applied) |

## Tests

```bash
./scripts/test_db.sh && uv run pytest     # 139 tests: unit, property, fuzz, security, integration, e2e, contract, failure injection
uv run aegistrace policy test             # Rego tests
(cd packages/sdk-typescript && npm ci && npm test)
(cd apps/dashboard && npm ci && npx next build && npx playwright test)   # needs AEGIS_TOKEN
```

## Documentation

- Architecture: [docs/architecture/](docs/architecture/)
- Security: [threat model](docs/security/THREAT_MODEL.md), [trust boundaries](docs/security/TRUST_BOUNDARIES.md), [sandbox](docs/security/SANDBOX.md), [MCP](docs/security/MCP_SECURITY.md)
- Cryptography: [protocol](docs/cryptography/PROTOCOL.md), [trust model](docs/cryptography/TRUST_MODEL.md)
- [Replay](docs/replay/REPLAY.md)
- Operations: [runbook](docs/operations/RUNBOOK.md), [incident response](docs/operations/INCIDENT_RESPONSE.md)
- [Benchmarks](docs/benchmarks/REPORT.md) (measured on a laptop; read the limitations)

## License

Dual-licensed: the offline verifier, CLI, SDKs, policies and examples are **Apache-2.0**; the server and dashboard are **FSL-1.1-ALv2** (Functional Source License; each version becomes Apache-2.0 two years after release). See [LICENSE](LICENSE).
