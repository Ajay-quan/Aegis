# Gap analysis: target Studio vs. today

| Studio area (target) | Today | Status | Main gap |
|---|---|---|---|
| Overview | `/` KPIs, activity chart, health, approvals | available | tokens and cost not tracked |
| Agent Builder | agents and grants via API; read-only list in UI | planned | create/edit/version UI, model + memory binding |
| Memory (AegisMem) | `/memory`: activity + per-subject browse | preview | search, edit, versions, contradictions, graph |
| Traces | `/runs/[id]`: timeline, evidence, replay; OTel spans to Tempo | available | span tree in Studio, token/cost per span |
| Runtime | worker leases, recovery, cancel/reconcile | available (in AegisTrace) | runtime config UI, worker health page |
| Security (Guard) | rules, grants, approvals, security log, erasures | available | role model (Owner/Admin/Developer/Viewer), audit viewer |
| Evaluations | AegisMem `/eval/*` (retrieval, contradiction) | preview (API only) | datasets, runs, comparisons UI |
| Optimization | none | planned | token/cost capture first |
| Models | mock + OpenAI-compatible adapter | preview | registry, connectivity tests, providers |
| Integrations | MCP servers file, AegisMem link, OIDC | preview | UI, verification state |
| Deployments | `/operations` service health | preview | environments, history |
| Settings: API keys | `/settings/api-keys`; `POST/GET /v1/api-keys`, `DELETE /v1/api-keys/{id}` | available (2026-11-16) | rotation helper; per-key rate limits |
| Settings: audit | `/settings/audit`; `GET /v1/audit-events` (key actions so far) | preview | log more admin actions (rules, grants, erasures) |
| Settings: members, usage | none | planned | membership table and roles; usage needs token capture |
| Public site pages | `/welcome` only | preview | /platform, /products/*, /docs, … |

Risks: AegisMem runs with auth off in local compose; token/cost data does not exist yet (Overview and Optimize
depend on it); the Studio UI lives inside the AegisTrace folder (fine for now; a move needs care with CI paths).
