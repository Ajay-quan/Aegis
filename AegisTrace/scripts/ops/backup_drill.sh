#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
# Backup/restore drill: dump the live database, restore it into a scratch
# database, then verify every run's evidence from the RESTORED copy against
# the trust store and the external anchor. Prints measured timings.
set -euo pipefail
cd "$(dirname "$0")/../.."
OUT=.dev/backups; mkdir -p "$OUT"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DUMP="$OUT/aegistrace-$STAMP.dump"

t0=$(python3 -c 'import time;print(time.time())')
docker compose exec -T postgres pg_dump -U aegis_owner -d aegistrace -Fc > "$DUMP"
t1=$(python3 -c 'import time;print(time.time())')
docker compose exec -T postgres psql -q -U aegis_owner -d postgres -c "DROP DATABASE IF EXISTS aegistrace_restore" \
  -c "CREATE DATABASE aegistrace_restore" -c "GRANT CONNECT ON DATABASE aegistrace_restore TO aegis_app, aegis_dispatcher"
docker compose exec -T postgres pg_restore -U aegis_owner -d aegistrace_restore --exit-on-error < "$DUMP"
t2=$(python3 -c 'import time;print(time.time())')

uv run python scripts/ops/verify_restored.py \
  --db postgresql+psycopg://aegis_owner:dev-owner-password@127.0.0.1:55432/aegistrace_restore \
  --trust .dev/trust.json --anchor .dev/anchor/checkpoints.jsonl
t3=$(python3 -c 'import time;print(time.time())')
python3 - "$t0" "$t1" "$t2" "$t3" "$DUMP" <<'PY'
import os, sys
t0, t1, t2, t3 = map(float, sys.argv[1:5])
print(f"dump {t1-t0:.2f}s  restore {t2-t1:.2f}s  verify {t3-t2:.2f}s  size {os.path.getsize(sys.argv[5])} bytes")
PY
