# Operations runbook

## Local reference environment

```bash
docker compose up -d --wait postgres redis opa      # dependencies
uv sync                                             # Python 3.12 env (see note below)
uv run python scripts/dev_bootstrap.py              # dev keys, issuer, tenant tnt_demo, tokens in .dev/
docker compose up -d --build --wait                 # migrate, api, worker, dispatcher
./examples/quickstart/run.sh                        # end-to-end: register, grant, run, receipt, verify, replay
```

> **macOS with an iCloud-synced Desktop:** iCloud marks `.pth` files hidden and Python skips hidden `.pth` files. Keep the virtualenv out of sync: `rm -rf .venv && mkdir .venv.nosync && ln -s .venv.nosync .venv && uv sync`.

Dashboard: `cd apps/studio && npm ci && npm run build && AEGIS_API_URL=http://127.0.0.1:8000 npx next start -p 3100`, then sign in with the `user` token from `.dev/tokens.json`.

Tests: `./scripts/test_db.sh && uv run pytest`. These use the isolated `aegistrace_test` database and Redis DB 1.

## Configuration

| Variable | Used by | Notes |
|---|---|---|
| `AEGIS_DATABASE_URL` | api, worker | `aegis_app` role |
| `AEGIS_DISPATCHER_DATABASE_URL` | dispatcher | `aegis_dispatcher` role |
| `AEGIS_OWNER_DATABASE_URL` | migrations only | Never give this to services |
| `AEGIS_REDIS_URL`, `AEGIS_OPA_URL` | all | |
| `AEGIS_OIDC_ISSUER`, `AEGIS_OIDC_AUDIENCE`, `AEGIS_OIDC_JWKS` | api | JWKS URL or file |
| `AEGIS_SIGNING_KEY_FILE` | api, worker | Must be mode 0600 unless `AEGIS_DEV_ALLOW_SHARED_KEY_FILE=1` (local compose only) |
| `AEGIS_ANCHOR_FILE` | worker | Append-only checkpoint anchor (dev) |
| `AEGIS_RATE_LIMIT_PER_MINUTE` | api | Default 600 per principal |
| `AEGIS_OPENAI_BASE_URL`, `AEGIS_OPENAI_API_KEY` | worker | Only for agents with `model_provider=openai-compatible` |

## Degradation behavior (§42)

| Dependency down | Behavior | Verified by |
|---|---|---|
| PostgreSQL | API returns 503 with no detail; `/readyz` returns 503; workers cannot claim or record, so no protected action executes | `test_database_outage_returns_503_without_detail` |
| Redis | Outbox rows stay `pending` with backoff and are published on recovery. API reads continue; the rate limiter fails open (it is availability control, not authorization). | `test_redis_outage_keeps_outbox_pending_then_recovers`, `test_redis_outage_does_not_block_authenticated_reads` |
| OPA | Every tool call is denied (`policy_engine_unavailable`) | `test_policy_outage_fails_closed` |
| Signing key | Workers refuse to start; receipt export fails | startup check in `workers/main.py` |
| Anchor storage | The checkpoint is still stored in the DB; anchoring failure is logged | `Worker.seal` (logged, **not alerted yet**) |
| Model provider | `model.failed`; timeout and rate-limit errors go to `RETRY_SCHEDULED` within the attempt budget | runner code path (no dedicated test yet) |

## Backup and restore

```bash
./scripts/ops/backup_drill.sh
```

The drill runs `pg_dump -Fc`, restores into `aegistrace_restore`, then re-verifies **every** run from the restored copy against `.dev/trust.json` and the anchor.

Measured on 2026-10-31 (M1 Pro laptop, 1,182 runs after load testing):

| Dataset | Dump | Restore | Verify all | Result |
|---|---|---|---|---|
| 3 runs | 0.22 s | 0.43 s | 0.33 s | 3/3 VALID |

The 1,182-run figure is from `verify_restored.py` on the live DB: 1,182/1,182 VALID with the anchor.

**Provisional objectives (reference deployment, not yet validated at scale):** RPO ≤ 5 minutes using RDS PITR, and RTO ≤ 1 hour. These must be re-measured on production-sized data.

**After any restore:** run `verify_restored.py` with the **anchor**. Runs whose anchored checkpoint is newer than the restored data will fail with `MISSING_EVENT`. That is how data lost in the restore window is discovered; do not suppress it.

## Service-level indicators

Exported metrics:
- `aegis_tool_decisions_total{decision,reason}`
- `aegis_policy_eval_seconds`
- `aegis_gateway_overhead_seconds`
- `aegis_tool_executions_total`
- `aegis_outbox_lag_seconds`
- `aegis_outbox_publish_failures_total`
- `aegis_queue_pending_messages`
- `aegis_recoveries_total`
- `aegis_runs_finished_total`

Suggested alerts (not yet deployed as rules):
- outbox lag above 60 s for 5 minutes
- any `policy_engine_unavailable` decision
- queue pending above 1,000
- any run in `NEEDS_RECONCILIATION`
- anchoring failures
