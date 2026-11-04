# AegisOS

Trust infrastructure for AI agents: what they remember, what they are allowed to do, and proof of what they did.

| Component | What it does | Folder | Status |
|---|---|---|---|
| **AegisStudio** | Dashboard: activity, approvals, permissions, rules, insights | [`apps/studio`](apps/studio) | Working |
| **API** | HTTP API for runs, agents, approvals, rules, receipts | [`apps/api`](apps/api) | Working |
| **CLI** | `aegistrace` command | [`apps/cli`](apps/cli) | Working |
| **AegisTrace** | Tamper-evident records, signed receipts, offline verifier, metrics, insights | [`packages/aegistrace`](packages/aegistrace) | Working |
| **AegisGuard** | Permission checks (default deny), organization rules, identity, sandbox | [`packages/aegisguard`](packages/aegisguard) | Working |
| **AegisRuntime** | Durable agent runs, human approvals, tool gateway, replay | [`packages/aegisruntime`](packages/aegisruntime) | Working |
| **AegisMem** | Persistent memory engine for agents | [`packages/aegismem`](packages/aegismem) | Working |
| AegisMem Recall | Chrome extension that searches your AI chats | [`apps/memory-extension`](apps/memory-extension) | Working |
| Website | Marketing site | [`apps/site`](apps/site) | Working |
| SDKs | Python and TypeScript clients | [`packages/sdk-python`](packages/sdk-python), [`packages/sdk-typescript`](packages/sdk-typescript) | Working |
| Local runtime | Run small models on your own machine | [`apps/local-runtime`](apps/local-runtime) | Planned |
| AegisEval | Evaluation framework | [`packages/aegiseval`](packages/aegiseval) | Planned |
| AegisOptimize | Optimization engine | [`packages/aegisoptimize`](packages/aegisoptimize) | Planned |
| AegisModels | Local model management | [`packages/aegismodels`](packages/aegismodels) | Planned |
| Contracts | Shared API and event schemas | [`packages/contracts`](packages/contracts) | Planned |

Pre-release. No independent security review yet; see [SECURITY.md](SECURITY.md).

## Layout

```
apps/            studio, api, cli, local-runtime, memory-extension, site
packages/        aegistrace, aegisguard, aegisruntime, aegismem, aegiseval, aegisoptimize,
                 aegismodels, sdk-python, sdk-typescript, contracts, shared
infrastructure/  docker, kubernetes, terraform, monitoring
tests/           unit, property, fuzz, security, integration, e2e, contract, failure_injection, performance
docs/            architecture, adr, development, api, deployment, aegistrace
examples/        quickstart (working), local-slm-agent, memory-enabled-agent, multi-agent-workflow (planned)
```

## Quick start (AegisTrace)

```bash
uv sync
docker compose up -d --wait postgres redis opa
uv run python scripts/dev_bootstrap.py
docker compose up -d --build --wait
./examples/quickstart/run.sh
```

More: [docs/development](docs/development/README.md), [AegisTrace guide](docs/aegistrace/README.md),
[AegisMem guide](packages/aegismem/README.md).

## License

Apache-2.0 and FSL-1.1-ALv2 by component; see [LICENSE](LICENSE).
