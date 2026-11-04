# Progress

## Session 4 (2026-10-31)

- Per-organization rules:
  - presets, approval threshold, never-allowed and always-ask lists, approval window
  - enforced in Rego (`tools-v2`, 17 policy tests); versioned, append-only history
  - editable in the dashboard, the API (`/v1/rules`), or a YAML file (`aegistrace policy apply/export`, dry run)
- Insights report (`/v1/insights`, dashboard *Insights*, `aegistrace insights`): verdict, working / not working, agent scorecard with reasons, tool reliability, grouped recommendations, Markdown export. Rules-based, documented in RULES_AND_INSIGHTS.md.
- Dashboard redesign: activity chart (palette validated for the dark surface), KPI tiles with explanations, health banner, ⌘K palette, plain-language copy.
- Fixes found along the way:
  - YAML parse errors returned 500; now 422
  - OPA served a stale policy until restarted (dev compose now uses `--watch`)
  - iCloud duplicated files in `.next` (build dir is now `.next.nosync`)

## Session 3 (2026-10-31)

New work:
- Dark, live, interactive dashboard:
  - same-origin allowlisted API proxy; token never reaches browser JS
  - views: overview, runs (filters, search, new-run drawer with scenarios), run detail (timeline, evidence and hash-chain view, replay, cancel/reconcile/receipt), approvals, agents and policy (grants plus simulator), security, operations
- Grant list/revoke API; policy dry-run API (shared code path with the gateway)
- Token revocation via logout (fails closed)
- Anchor-failure and recovery metrics; 7 promtool-validated alert rules
- Demo data seeder: `scripts/seed_demo.py`

Python tests: 141 passed. Playwright: 2/2.

## Status as of 2026-10-31 (end of session 2)

**Pre-release (0.1.0.dev0). Not production-ready.**

- No independent security review (§48).
- The CI workflow has never run on GitHub.
- Nothing has been deployed.

### Verification evidence from this session (all run locally)

| Check | Result |
|---|---|
| Python tests (`uv run pytest`) | **139 passed**, 0 failed, 0 skipped. Suites: unit 19, property 6, fuzz 7, security 49, integration 19, end-to-end 16, contract 18, failure-injection 5. |
| Rego policy tests (`opa test`) | 10/10 |
| TypeScript SDK (`npm test`) | 6/6, including a live run against the compose stack |
| Dashboard | `tsc` clean, `next build` OK, Playwright 2/2 against the live stack |
| Lint and types | ruff clean, ruff format clean, mypy --strict clean (53 files) |
| Containerized quickstart (CLI → API → worker → OPA → receipt → offline verify → replay) | VALID / IDENTICAL |
| Backup drill (dump → restore → re-verify every run with the anchor) | Passed (see RUNBOOK) |
| Load test (k6, 1/10/50 VUs) | 0 HTTP errors; 1,182/1,182 runs succeeded and verified (see docs/benchmarks/REPORT.md) |
| Supply chain | pip-audit: no known vulnerabilities. npm audit: 0. gitleaks: no leaks (dev secrets and build output allowlisted, both git-ignored). Trivy image: 0 fixable HIGH/CRITICAL after remediation. SBOM: 3,502 components (CycloneDX). |
| Infrastructure as code | kubeconform 15/15 valid; `terraform validate` OK; **nothing provisioned** |

### Phase status

| Phase | Status | Notes |
|---|---|---|
| 0 Design | Done | Architecture, state machine, trust boundaries, threat model (24 threats mapped to tests), protocol |
| 1 Backend foundation | Done | FastAPI, PostgreSQL with forced RLS, Alembic (4 migrations, up/down tested), JWT/JWKS auth, JSON logs, compose, CI definition |
| 2 Workflow kernel | Done | State machine, chained event store, idempotent submission, transactional outbox, dispatcher |
| 3 Cryptographic evidence | Done | JCS, hash chain, Ed25519 checkpoints, trust store, bundles, offline verifier, external anchor |
| 4 Zero-trust authorization | Done | OPA/Rego default deny, grants, decision records, fail closed |
| 5 Fault tolerance | Done | Leases, fencing, recovery, backoff retries, timeouts, reconciliation, dead letters |
| 6 MCP and agents | Partial | Mock and OpenAI-compatible adapters (the latter tested only against a fake transport); MCP over stdio. **No remote MCP or OAuth.** No LangGraph adapter. |
| 7 Sandboxing | Done (container level) | microVM runtime not tested |
| 8 Approvals | Done | |
| 9 Replay and forensics | Done | Modes A–D |
| 10 Developer interfaces | Done | Python SDK (sync and async), TypeScript SDK, CLI, dashboard, OpenAPI |
| 11 Observability | Partial | Prometheus metrics and logs. **No OpenTelemetry tracing**, no Grafana dashboards or alert rules. |
| 12 Security hardening | Partial | Adversarial tests, fuzzing, scanners. **No independent review.** |
| 13 Performance | Partial | Measured to 50 VUs on one laptop. 100/500 not run. |
| 14 Deployment readiness | Partial | k8s and Terraform validated, not applied. Managed Ed25519 signing unverified. |
| 15 Release | Not started | No license chosen, no release signing or provenance, CI never run |
