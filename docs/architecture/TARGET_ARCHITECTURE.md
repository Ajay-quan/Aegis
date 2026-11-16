# Target architecture for Aegis Studio

```
Public site (/welcome, later /platform, /products/*, /docs …)
        │
Aegis Studio UI  (Next.js, AegisTrace/apps/dashboard; becomes apps/studio when it outgrows the folder)
        │  server-side session (OIDC) · same-origin BFF routes (/api/aegis/*, later /api/studio/*)
Studio API  = AegisTrace API (control plane: orgs, workspaces, keys, agents, policy, runs, audit)
        │  typed adapters
 ┌──────┴────────┬──────────────┬─────────────┐
AegisMem      AegisTrace      Runtime*      Guard*      (*today inside AegisTrace)
(memory API)  (runs, evidence) (workers)     (OPA, approvals)
        │
Postgres · Redis · OPA · signer · Qdrant/Neo4j (optional) · model providers · MCP servers
```

Principles:
1. **No new service until one is needed.** Runtime and Guard already exist as AegisTrace modules; Eval,
   Optimize and Models start as modules too.
2. **One control plane.** Organization = AegisTrace tenant; workspace = AegisTrace project. Studio-owned
   records (API keys, audit events, integrations, saved views) live in the AegisTrace database under the
   same RLS. AegisMem keeps owning memory; AegisTrace keeps owning runs and evidence (ADR-001).
3. **Every privileged call goes through the server.** The browser never holds API keys, provider secrets
   or database credentials.
4. **Capability discovery.** Studio asks each service what it supports and shows `unavailable`/`degraded`
   honestly instead of mocking.
