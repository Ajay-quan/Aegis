# Notes for AI coding agents

- Read [README.md](README.md), then the guide for the component you are changing:
  AegisTrace: `docs/aegistrace/product/PROGRESS.md` and `OPEN_ISSUES.md`. AegisMem: `project_log.md`.
- Python engines are one uv workspace at the root. Run `uv run ruff check . && uv run mypy && uv run pytest` before finishing.
- Dependency direction is `aegistrace` ← `aegisguard` ← `aegisruntime` ← `apps/api`. Never import upward.
- The Rego package `aegistrace.tools` is the OPA query path the gateway calls; it is not a Python module. Do not rename it.
- Never fabricate test results. Every security or reliability claim needs a test.
- Do not deploy, publish packages, or push to `main` without the owner's approval.
