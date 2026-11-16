#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
# Governed memory demo: an agent remembers and recalls through AegisMem, every
# access is policy-checked and signed, and erasing memory needs human approval.
# Prereqs: an AegisMem server, and the compose stack started with AEGIS_MEMORY_URL
# pointing at it (see README.md in this folder).
set -euo pipefail
cd "$(dirname "$0")/../.."
export AEGIS_API_URL=http://127.0.0.1:8000
AEGIS_TOKEN=$(python3 -c 'import json;print(json.load(open(".dev/tokens.json"))["user"])')
export AEGIS_TOKEN
A="uv run aegistrace"
D=examples/governed_memory
id() { python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])'; }

PROJECT=$(uv run python - <<'PY'
import os, secrets
from aegistrace_sdk import AegisClient
print(AegisClient(os.environ["AEGIS_API_URL"], os.environ["AEGIS_TOKEN"]).create_project("memory-" + secrets.token_hex(3))["id"])
PY
)
AGENT=$($A agents register --project "$PROJECT" --name billing-agent)
$A agents grant "$AGENT" memory.remember --max-class 2
$A agents grant "$AGENT" memory.recall --max-class 1
$A agents grant "$AGENT" memory.forget --max-class 4   # allowed, but only with human approval

echo "== 1. The agent learns two facts"
RUN1=$($A --json runs submit --agent "$AGENT" --input $D/learn.json --wait | id)
$A runs events "$RUN1"

echo "== 2. A later run recalls them (and a recall about another customer finds nothing)"
RUN2=$($A --json runs submit --agent "$AGENT" --input $D/recall.json --wait | id)
$A runs events "$RUN2"

echo "== 3. Erasing memory pauses for approval: open the dashboard, Approvals"
MID=$(curl -s -X POST http://127.0.0.1:${AEGIS_MEMORY_PORT:-8100}/api/v1/retrieve -H 'content-type: application/json' \
      -d '{"query":"Acme invoices","user_id":"tnt_demo/acme","top_k":1}' \
      | python3 -c 'import json,sys;print(json.load(sys.stdin)["results"][0]["memory_id"])')
sed "s/MEMORY_ID/$MID/" $D/forget.json > ".dev/forget-$MID.json"
RUN3=$($A --json runs submit --agent "$AGENT" --input ".dev/forget-$MID.json" | id)
echo "run $RUN3 is waiting for approval"

echo "== 4. Signed receipt for run 2, verified offline"
$A receipt "$RUN2" -o ".dev/$RUN2.receipt.zip"
$A verify ".dev/$RUN2.receipt.zip" --trust .dev/trust.json --tenant tnt_demo --run "$RUN2"
