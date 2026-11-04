# Contributing to AegisOS

This repository holds several products. Follow the section for the code you are changing.

## AegisMem (packages/aegismem, apps/memory-extension, apps/site)

Thanks for your interest in contributing. This guide gets you productive fast.

## Development setup

Requires Python 3.11+ (the package targets 3.11) and Node 18+ for the frontend.

```bash
git clone https://github.com/Ajay-quan/AegisMem.git
cd AegisMem
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-asyncio httpx        # test deps
```

The service runs with **zero infrastructure** by default (in-memory stores +
deterministic mock embeddings):

```bash
uvicorn apps.api.main:app --reload     # http://127.0.0.1:8000/docs
```

## Running tests

```bash
# Full Python suite (no external infra needed):
pytest -q

# A focused area:
pytest tests/unit/test_online_scorer.py -q

# Frontend type-check:
npx tsc --noEmit
```

All PRs must keep the suite green. Add tests for new behavior — unit tests for
domain logic, API tests (httpx + ASGITransport) for endpoints.

## Project layout

```
core/        config, schemas, logging, observability, security, version
domain/      pure logic: memory scoring, lexical/BM25, reranker, learning, privacy, evaluations
services/    orchestration: ingest, retrieve, update, contradiction, reflect, feedback
adapters/    swappable backends: relational, vector, graph, embeddings, llm
apps/        FastAPI app (api/) + CLI
integrations/ MCP server
sdk/         zero-dependency Python client
src/         Next.js frontend (AegisMem marketing site)
```

Architecture: `API → services → domain → adapters`, every external backend
behind an adapter, defaults in-memory. See `docs/architecture.md`,
`docs/continual_learning_design.md`, and `docs/ELITE_UPGRADE.md`.

## Conventions

- Keep the **zero-infra default** working: new external backends must be opt-in
  via settings and degrade gracefully (dev/staging) or fail loudly only in
  production (`APP_ENV=production`).
- Prefer narrow exceptions; log on graceful-degradation paths.
- No secrets in commits (`.env` is gitignored; use `.env.example`).
- Update `CHANGELOG.md` and relevant docs with user-facing changes.

## Pull requests

1. Branch from `main`.
2. Keep changes focused; one concern per PR.
3. `pytest -q` and `npx tsc --noEmit` must pass.
4. Fill in the PR template.

## Reporting bugs / requesting features

Use the issue templates under `.github/ISSUE_TEMPLATE`.

## AegisTrace engines (aegistrace, aegisguard, aegisruntime, apps/api, apps/cli, apps/studio)

Run from the repository root.

1. Read `docs/aegistrace/product/PROGRESS.md`, `OPEN_ISSUES.md` and the threat model first.
2. Every security or reliability claim needs a test (INV-013). Never fabricate results (INV-014).
3. Before opening a PR:
   - `uv run ruff check . && uv run ruff format --check . && uv run mypy`
   - `./scripts/test_db.sh && uv run pytest`
   - `uv run aegistrace policy test`
4. Schema changes need a new Alembic migration with a working `downgrade()`.
5. Changes to the evidence protocol require a new protocol version and new test vectors. Never change v1 semantics.
6. Keep `aegisruntime.replay` and `aegistrace.evidence` free of I/O and server imports.
