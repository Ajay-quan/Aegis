# Changelog

## Unreleased

- Restructured the repository into the AegisOS layout (`apps/`, `packages/`, `infrastructure/`, `tests/`, `docs/`, `examples/`).
- Split AegisTrace into three engines: `aegistrace` (evidence, metrics, insights), `aegisguard` (policy, rules, identity, sandbox) and `aegisruntime` (runs, approvals, gateway, agents, replay, workers), plus `apps/api` and `apps/cli`.
- AegisTrace JavaScript projects moved to a pnpm workspace; AegisMem keeps its npm lockfiles.
- Added placeholders for local-runtime, aegiseval, aegisoptimize, aegismodels and contracts.

Component history: [packages/aegismem/CHANGELOG.md](packages/aegismem/CHANGELOG.md), [docs/aegistrace/product/PROGRESS.md](docs/aegistrace/product/PROGRESS.md).
