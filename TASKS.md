# Tasks

| ID | Task | Status | Depends on | Acceptance criteria |
|---|---|---|---|---|
| S-01 | Phase 0 audit docs (EXISTING_SYSTEM, TARGET_ARCHITECTURE, GAP_ANALYSIS, INTEGRATION_PLAN) | done | — | docs/architecture/* match the code |
| S-02 | API keys: create/list/revoke, shown once, hashed, scoped, audited, tenant-isolated | done | S-01 | tests/contract/test_api_keys.py (8), Playwright key flow, CLI works with a key |
| S-03 | Audit log page | done (preview) | S-02 | /settings/audit lists key events |
| S-04 | Write audit events for rules, grants, erasures, legal holds | planned | S-03 | each admin change appears in /settings/audit; test per action |
| S-05 | AegisMem service credential (Studio → AegisMem with an aem_ key; auth on in compose) | planned | — | compose runs AegisMem with AUTH_ENABLED=true; contract + e2e pass |
| S-06 | Members and roles (Owner/Admin/Developer/Viewer → scopes), enforced server-side | planned | S-04 | role escalation and cross-tenant tests |
| S-07 | Memory Explorer: search, versions, contradictions, quarantine review | planned | S-05 | real AegisMem calls; permission tests |
| S-08 | Agent Builder (form): create/edit agents, model, grants | planned | S-06 | persisted, validated, survives reload; e2e |
| S-09 | Token and cost capture in model adapters | planned | — | per-run tokens recorded; Overview shows real numbers |
| S-10 | Public pages: /platform, /products/*, /docs, /architecture | planned | — | content matches code; working/planned labelled |
