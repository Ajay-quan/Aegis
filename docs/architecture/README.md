# Architecture

| Component | Folder | Role |
|---|---|---|
| AegisStudio | `apps/studio` | Dashboard |
| API | `apps/api` | HTTP API (FastAPI) |
| CLI | `apps/cli` | `aegistrace` command |
| AegisTrace | `packages/aegistrace` | Tamper-evident evidence, receipts, offline verifier, metrics, insights |
| AegisGuard | `packages/aegisguard` | Policy decisions (OPA), organization rules, identity, sandbox |
| AegisRuntime | `packages/aegisruntime` | Durable runs, approvals, tool gateway, agents, replay, workers |
| AegisMem | `packages/aegismem` | Persistent memory engine |

Details: [AegisTrace](aegistrace/ARCHITECTURE.md), [state machine](aegistrace/STATE_MACHINE.md), [AegisMem](aegismem.md).
