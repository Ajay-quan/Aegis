# Open issues (prioritized)

## Blocking any production or public deployment
1. **Independent security review** of the sandbox, authentication/authorization, cryptographic protocol, tenant isolation and network controls (§48).
2. **Managed signing backend.** Only the file-based dev signer exists. Verify Ed25519 support in the chosen KMS/HSM before choosing it, otherwise run a dedicated signing service. Implement `Signer` for it.
3. ~~License~~ Done: split Apache-2.0 / FSL-1.1-ALv2 (ADR-021). If outside contributions are accepted, decide on a DCO or CLA first, so contributed code can be offered under both licenses.
4. **CI never executed on GitHub.** Also pin third-party actions to reviewed commit SHAs.
5. **Release signing and provenance** (Sigstore/cosign, SLSA) are not implemented.

## Functional gaps
6. Remote MCP servers (Streamable HTTP) with OAuth 2.1 and audience-bound tokens; MCP conformance testing.
7. Data retention, privacy deletion (crypto-shredding of payload encryption keys), legal hold, envelope encryption of payloads (§32–33). Payloads are currently plaintext JSONB, protected by RLS and managed encryption at rest only.
8. OpenTelemetry tracing and Grafana dashboards. (Prometheus alert rules: done, `infra/observability/alerts.yml`, promtool-validated.)
9. Custom Rego logic per organization still requires a code change. Per-org rule settings, presets, file-based rules and history are done. Production OPA should load signed policy bundles rather than `--watch`.
10. Artifact storage service (S3 upload/download API). Bundles support artifacts, but runs do not yet produce stored artifacts.
11. ~~Token revocation~~ Done: `POST /v1/auth/logout`; jti denylist in Redis; fails closed if Redis is unreachable.
12. The OpenAI-compatible adapter is tested only against fake transports, never against a live provider.
13. LangGraph integration adapter (optional in the directive).
14. Interactive OIDC login for the dashboard (it currently accepts a pasted token).

## Hardening
15. DNS-rebinding TOCTOU in `egress.py`. Production needs an egress proxy that pins resolved IPs.
16. Anchoring failures are counted and alerted (`aegis_anchor_failures_total`), but do not block new work.
17. The rate limiter fails open when Redis is down (documented choice; revisit).
18. ~~Reconciliation UI~~ Done (run page actions).
19. Load tests above 50 VUs and with multiple workers; Postgres tuning.
