# Security risks (current)

The full analysis is in `docs/security/THREAT_MODEL.md`. These are the risks that remain open today.

| Risk | Severity (for an intended multi-tenant SaaS deployment) | Status |
|---|---|---|
| No independent security review | High | Open; blocks release |
| Dev signing key is a file; no managed KMS/HSM backend | High | Open |
| Container-only sandbox for hostile code | High for hostile multi-tenant code | Mitigated by the dedicated-host design; microVM runtime untested |
| DNS-rebinding TOCTOU in the egress check | Medium | Needs a network-level egress proxy |
| Payloads stored unencrypted at the application layer; no deletion or retention | Medium | Open |
| Superuser can disable append-only triggers | Medium | Detected (anchor and verifier), not prevented |
| Rate limiter fails open on Redis outage | Low | Documented choice |
| Third-party GitHub Actions pinned by tag, not SHA | Medium | Open |
| `psycopg[binary]` in the dev environment vendors vulnerable libraries | Low (dev only) | The image uses system libpq |
