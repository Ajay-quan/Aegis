# Open issues (prioritized)

## Blocking any production or public deployment
1. **Independent security review** of the sandbox, authentication/authorization, cryptographic protocol, tenant isolation and network controls (§48).
2. **Managed signing backend.** Only the file-based dev signer exists. Verify Ed25519 support in the chosen KMS/HSM before choosing it, otherwise run a dedicated signing service. Implement `Signer` for it.
3. ~~License~~ Done: split Apache-2.0 / FSL-1.1-ALv2 (ADR-021). If outside contributions are accepted, decide on a DCO or CLA first, so contributed code can be offered under both licenses.
4. ~~CI never executed on GitHub~~ Done: CI runs on GitHub and is green (Python, TypeScript, supply chain with secret scan, Trivy and SBOM, AegisMem integration). Actions pinned to commit SHAs.
5. **Release signing and provenance** (Sigstore/cosign, SLSA) are not implemented.

## Functional gaps
- ~~Memory~~ Done: governed memory via AegisMem (`memory.recall/remember/forget`), see `tools/memory.py` and `examples/governed_memory`.
6. ~~Remote MCP servers with OAuth 2.1 and audience-bound tokens~~ Done (docs/security/MCP_SECURITY.md). Remaining: official MCP conformance-suite run; on-behalf-of-user grants.
7. ~~Data retention, privacy deletion, legal hold, envelope encryption~~ Done (docs/operations/PRIVACY.md). Remaining: a KMS-backed `KeyWrapper` for production (the dev wrapper uses a key file).
8. ~~OpenTelemetry tracing and Grafana dashboards~~ Done (docs/operations/OBSERVABILITY.md): one trace per run across API, queue and worker; Grafana + Tempo + Prometheus via `./aegis up --observability`.
9. Custom Rego logic per organization still requires a code change. Per-org rule settings, presets, file-based rules and history are done. Production OPA should load signed policy bundles rather than `--watch`.
10. Artifact storage service (S3 upload/download API). Bundles support artifacts, but runs do not yet produce stored artifacts.
11. ~~Token revocation~~ Done: `POST /v1/auth/logout`; jti denylist in Redis; fails closed if Redis is unreachable.
12. The OpenAI-compatible adapter is tested only against fake transports, never against a live provider.
13. LangGraph integration adapter (optional in the directive).
14. ~~Interactive OIDC login~~ Done: authorization code + PKCE against any OIDC provider (docs/operations/SSO.md); dev provider for local use; token paste can be disabled.

## Hardening
15. DNS-rebinding TOCTOU in `egress.py`. Production needs an egress proxy that pins resolved IPs.
16. Anchoring failures are counted and alerted (`aegis_anchor_failures_total`), but do not block new work.
17. The rate limiter fails open when Redis is down (documented choice; revisit).
18. ~~Reconciliation UI~~ Done (run page actions).
19. ~~Multiple workers and recovery under load~~ Done on one machine (docs/benchmarks/DISTRIBUTED.md): 1–4 workers; worker kill, Redis, OPA and Postgres faults; 7,334/7,334 receipts VALID. Remaining: multi-host runs, Postgres failover, longer soak tests.
