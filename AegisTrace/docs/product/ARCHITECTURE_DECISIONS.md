# Architecture decisions

| ADR | Decision | Status | Rationale |
|---|---|---|---|
| 001 | Build the evidence core first, infrastructure-free | Accepted | The wire format is the longest-lived contract |
| 002 | No floats in the canonical model | Accepted | JCS number serialization is a cross-implementation risk |
| 003 | Payloads bound by digest | Accepted | Enables redaction and deletion without breaking verification |
| 004 | Genesis hash bound to (tenant, run) | Accepted | Prevents chain transplantation |
| 005 | Compromised keys reject all checkpoints | Accepted | Signer-asserted time is not trustworthy; anchors are the escape hatch |
| 006 | Single Python distribution plus a separate SDK distribution | Accepted | Modular monolith (§8). The verifier stays importable without server dependencies (enforced by imports), but is not yet a separate package. |
| 007 | PostgreSQL forced RLS with separate app, dispatcher and owner roles | Accepted | Tenant isolation enforced below application code |
| 008 | `SECURITY DEFINER` scheduler scans return IDs only | Accepted | Cross-tenant maintenance without granting cross-tenant reads |
| 009 | Fencing token on every worker write | Accepted | Stale-worker safety without distributed locks |
| 010 | `retry_safe` flag plus started/outcome events drive reconciliation | Accepted | No exactly-once claim; uncertain irreversible effects are never auto-retried |
| 011 | Decision persisted before execution, in its own commit | Accepted | INV-004: no evidence means no execution |
| 012 | Replay package forbidden from importing I/O modules | Accepted | INV-006 by construction, enforced by a test |
| 013 | MCP tools require admin mapping and schema pinning; strict arguments | Accepted | Server metadata is never authority |
| 014 | Sandbox on dedicated hosts; workers never get the Docker socket | Accepted | INV-007 |
| 015 | External anchor (FileAnchor in dev, S3 Object Lock in a separate account in reference AWS) | Accepted | Closes tail truncation |
| 016 | Container image uses pure `psycopg` with Debian `libpq5` | Accepted | The `psycopg[binary]` wheel vendors an EL8 `libpcre2` with CRITICAL CVEs (Trivy) |
| 017 | Dashboard keeps the token server-side (httpOnly, SameSite=Strict cookie) | Accepted | No bearer token in browser JavaScript |
| 018 | TypeScript 5.9.3 rather than 7.0 | Accepted | Next.js toolchain compatibility with the 7.x native compiler is unverified |
| 019 | `/metrics` disabled on the API by default | Accepted | Platform-wide counters must not be reachable via the public ingress |
| 020 | Tests use an isolated `aegistrace_test` database and Redis DB 1 | Accepted | Discovered when the compose worker consumed test runs |
| 021 | Split licensing: Apache-2.0 for the verifier, CLI, SDKs, policies and examples; FSL-1.1-ALv2 for the server and dashboard. Copyright: AegisTrace contributors. | Accepted (owner decision, 2026-10-31) | Anyone can verify receipts and integrate freely; competing hosted offerings of the server are restricted, and each version becomes Apache-2.0 two years after release |
