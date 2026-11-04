# Contributing

1. Read `docs/product/PROGRESS.md`, `OPEN_ISSUES.md` and the threat model first.
2. Every security or reliability claim needs a test (INV-013). Never fabricate results (INV-014).
3. Before opening a PR:
   - `uv run ruff check . && uv run ruff format --check . && uv run mypy`
   - `./scripts/test_db.sh && uv run pytest`
   - `uv run aegistrace policy test`
4. Schema changes need a new Alembic migration with a working `downgrade()`.
5. Changes to the evidence protocol require a new protocol version and new test vectors. Never change v1 semantics.
6. Keep `aegistrace.replay` and `aegistrace.evidence` free of I/O and server imports.
