# Development

Requires Docker, [uv](https://docs.astral.sh/uv/), Node 22 and pnpm 10 (`corepack enable`).

## AegisTrace engines (Python workspace at the repository root)

```bash
uv sync                                     # installs aegistrace, aegisguard, aegisruntime, apps/api, apps/cli, SDK
docker compose up -d --wait postgres redis opa
uv run python scripts/dev_bootstrap.py
docker compose up -d --build --wait
./scripts/test_db.sh && uv run pytest
uv run ruff check . && uv run mypy
```

Dependency direction (enforced by imports, never reversed): `aegistrace` ← `aegisguard` ← `aegisruntime` ← `apps/api`.

## JavaScript workspace (pnpm)

```bash
pnpm install
pnpm --filter @aegistrace/sdk test
pnpm --filter @aegistrace/dashboard exec next build
```

## AegisMem

AegisMem keeps its own tooling: see [packages/aegismem/README.md](../../packages/aegismem/README.md),
`apps/memory-extension` and `apps/site` (npm, each with its own lockfile).
