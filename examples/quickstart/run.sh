#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
# End-to-end quickstart against the local compose stack.
# Prereqs: docker compose up -d --wait && uv run python scripts/dev_bootstrap.py
set -euo pipefail
cd "$(dirname "$0")/../.."
export AEGIS_API_URL=http://127.0.0.1:8000
AEGIS_TOKEN=$(python3 -c 'import json;print(json.load(open(".dev/tokens.json"))["user"])')
export AEGIS_TOKEN
A="uv run aegistrace"

$A doctor
PROJECT=$($A --json agents list >/dev/null; uv run python - <<'PY'
import os
from aegistrace_sdk import AegisClient
c = AegisClient(os.environ["AEGIS_API_URL"], os.environ["AEGIS_TOKEN"])
import secrets
print(c.create_project("quickstart-" + secrets.token_hex(3))["id"])
PY
)
AGENT=$($A agents register --project "$PROJECT" --name research-agent)
$A agents grant "$AGENT" calc.add --max-class 0
RUN=$($A --json runs submit --agent "$AGENT" --input examples/quickstart/research_task.json --wait \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')
$A runs get "$RUN"
$A runs events "$RUN"
$A receipt "$RUN" -o ".dev/$RUN.receipt.zip"
$A verify ".dev/$RUN.receipt.zip" --trust .dev/trust.json --tenant tnt_demo --run "$RUN"
$A runs replay "$RUN"
