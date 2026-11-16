# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Distributed load and recovery tests against the running compose stack.

Phases (each under sustained k6 load, governed_runs.js):
  scale-N   N workers, no faults (throughput and latency vs. worker count)
  kill      a worker is SIGKILLed mid-load; its leases expire and others recover the runs
  redis     the queue (Redis) restarts mid-load; the outbox redelivers
  opa       the policy engine is down for 10 s; tool calls must fail closed
  postgres  the database restarts mid-load

After each phase, once in-flight runs settle, it checks every run the phase created:
states, outbox backlog, sequence gaps, duplicate tool executions, executions
without an allow decision, and offline verification of every receipt against
the trust store and the external anchor.

Usage (from AegisTrace/, stack up via ../aegis up):
  uv run python benchmarks/distributed.py --phases scale-1,scale-2,scale-4,kill,redis,opa,postgres
Writes benchmarks/results/distributed-<timestamp>.json.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aegistrace.evidence.anchor import load_anchor  # noqa: E402
from aegistrace.evidence.bundle import write_bundle_records  # noqa: E402
from aegistrace.evidence.trust import TrustStore  # noqa: E402
from aegistrace.evidence.verifier import Status, verify_bundle  # noqa: E402
from aegistrace.persistence import sealing  # noqa: E402
from scripts.ops.verify_restored import open_records  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OWNER = "postgresql+psycopg://aegis_owner:dev-owner-password@127.0.0.1:55432/aegistrace"
TERMINAL = ("SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT", "NEEDS_RECONCILIATION")
PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "aegis")


def sh(*cmd: str, check: bool = True) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT.parent)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {r.stderr[-500:]}")
    return r.stdout


def compose(*args: str, check: bool = True) -> str:
    return sh("docker", "compose", "-p", PROJECT, *args, check=check)


def scale(workers: int) -> None:
    compose("up", "-d", "--no-recreate", "--scale", f"worker={workers}", "--wait", "worker")


def workers() -> list[str]:
    return [n for n in compose("ps", "--format", "{{.Name}}", "worker").split() if n]


def k6(vus: int, duration: str, token: str, out: Path) -> dict[str, Any]:
    sh(
        "docker",
        "run",
        "--rm",
        "-v",
        f"{ROOT / 'benchmarks'}:/b",
        "-e",
        f"TOKEN={token}",
        "-e",
        f"VUS={vus}",
        "-e",
        f"DURATION={duration}",
        "grafana/k6:1.3.0",
        "run",
        "--quiet",
        "--summary-export",
        f"/b/results/{out.name}",
        "/b/k6/governed_runs.js",
        check=False,
    )
    data: dict[str, Any] = json.loads(out.read_text()) if out.exists() else {}
    return data


def settle(eng: Any, since: datetime, timeout: float = 180) -> dict[str, int]:
    """Wait until every run created since `since` is terminal (lease recovery can take a TTL)."""
    deadline = time.time() + timeout
    while True:
        with eng.connect() as c:
            states = dict(
                c.execute(
                    text("SELECT state, count(*) FROM runs WHERE created_at >= :s GROUP BY state"), {"s": since}
                ).all()
            )
        if all(s in TERMINAL for s in states) or time.time() > deadline:
            return {k: int(v) for k, v in states.items()}
        time.sleep(3)


def consistency(eng: Any, since: datetime, trust: TrustStore) -> dict[str, Any]:
    anchor_file = ROOT / ".dev/anchor/checkpoints.jsonl"
    anchor = load_anchor(anchor_file.read_bytes()) if anchor_file.exists() else None
    with eng.connect() as c:
        q = lambda sql: c.execute(text(sql), {"s": since}).scalar_one()  # noqa: E731
        out: dict[str, Any] = {
            "outbox_pending_or_dead": q(
                "SELECT count(*) FROM outbox WHERE created_at >= :s AND status IN ('pending','dead')"
            ),
            "sequence_gaps": q(
                "SELECT count(*) FROM (SELECT e.run_id FROM events e JOIN runs r ON r.id=e.run_id "
                "WHERE r.created_at >= :s GROUP BY e.run_id HAVING max(e.sequence_number) <> count(*)) g"
            ),
            "duplicate_executions": q(
                "SELECT count(*) FROM (SELECT e.run_id, e.record->'payload'->>'call_key' k FROM events e "
                "JOIN runs r ON r.id=e.run_id WHERE r.created_at >= :s AND e.event_type='tool.execution_succeeded' "
                "GROUP BY 1,2 HAVING count(*) > 1) d"
            ),
            "executions_without_allow": q(
                "SELECT count(*) FROM events s JOIN runs r ON r.id=s.run_id WHERE r.created_at >= :s "
                "AND s.event_type='tool.execution_started' AND NOT EXISTS (SELECT 1 FROM events a "
                "WHERE a.run_id=s.run_id AND a.event_type='tool.authorization' "
                "AND a.record->'payload'->>'call_key' = s.record->'payload'->>'call_key' "
                "AND a.record->'payload'->>'decision' = 'allow' AND a.sequence_number < s.sequence_number)"
            ),
            "denied_by_policy_outage": q(
                "SELECT count(*) FROM events e JOIN runs r ON r.id=e.run_id WHERE r.created_at >= :s "
                "AND e.event_type IN ('tool.denied','tool.authorization') "
                "AND e.record->'payload'->>'reason' = 'policy_engine_unavailable'"
            ),
        }
        verdicts: Counter[str] = Counter()
        runs = c.execute(text("SELECT tenant_id, id FROM runs WHERE created_at >= :s"), {"s": since}).all()
        for tenant_id, run_id in runs:
            recs = open_records(
                c,
                [
                    dict(r)
                    for (r,) in c.execute(
                        text("SELECT record FROM events WHERE run_id=:r ORDER BY sequence_number"), {"r": run_id}
                    )
                ],
            )
            cps = [
                dict(r)
                for (r,) in c.execute(
                    text("SELECT record FROM checkpoints WHERE run_id=:r ORDER BY last_sequence"), {"r": run_id}
                )
            ]
            rep = verify_bundle(
                write_bundle_records(tenant_id, run_id, recs, cps, {}),
                trust,
                tenant_id,
                run_id,
                anchored_checkpoints=anchor,
            )
            verdicts[rep.status.value] += 1
        out["receipts"] = dict(verdicts)
        out["receipts_valid"] = verdicts.get(Status.VALID.value, 0)
    return out


FAULTS = {
    "kill": lambda: sh("docker", "kill", "--signal", "KILL", workers()[0]),
    "redis": lambda: compose("restart", "redis"),
    "opa": lambda: (compose("stop", "opa"), time.sleep(10), compose("start", "opa")),
    "postgres": lambda: compose("restart", "postgres"),
}


def phase(name: str, eng: Any, trust: TrustStore, token: str, vus: int, duration: str, stamp: str) -> dict[str, Any]:
    n = int(name.split("-")[1]) if name.startswith("scale-") else 3
    scale(n)
    since = datetime.now(UTC)
    out = ROOT / f"benchmarks/results/k6-distributed-{name}-{stamp}.json"
    fault_at = None
    if name in FAULTS:

        def inject() -> None:
            nonlocal fault_at
            time.sleep(8)
            fault_at = round(time.time() - since.timestamp(), 1)
            FAULTS[name]()

        threading.Thread(target=inject, daemon=True).start()
    summary = k6(vus, duration, token, out)
    states = settle(eng, since)
    if name == "kill":
        scale(n)  # bring the killed replica back for later phases
    m = summary.get("metrics", {})
    res = {
        "phase": name,
        "workers": n,
        "vus": vus,
        "duration": duration,
        "fault_injected_at_s": fault_at,
        "runs_by_state": states,
        "runs_per_s": round(m.get("runs_completed", {}).get("rate", 0), 1),
        "e2e_p50_ms": round(m.get("run_end_to_end_ms", {}).get("med", 0)),
        "e2e_p95_ms": round(m.get("run_end_to_end_ms", {}).get("p(95)", 0)),
        "http_failed_rate": m.get("http_req_failed", {}).get("value"),
        **consistency(eng, since, trust),
    }
    print(json.dumps(res), flush=True)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phases", default="scale-1,scale-2,scale-4,kill,redis,opa,postgres")
    ap.add_argument("--vus", type=int, default=40)
    ap.add_argument("--duration", default="40s")
    a = ap.parse_args()
    sealing.configure(sealing.LocalKeyWrapper.from_file(str(ROOT / ".dev/secrets/payload-kek")))
    trust = TrustStore.from_json(json.loads((ROOT / ".dev/trust.json").read_text()))
    token = json.loads((ROOT / ".dev/tokens.json").read_text())["user"]
    eng = create_engine(OWNER, pool_pre_ping=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results = [phase(p, eng, trust, token, a.vus, a.duration, stamp) for p in a.phases.split(",")]
    scale(1)
    path = ROOT / f"benchmarks/results/distributed-{stamp}.json"
    path.write_text(json.dumps({"measured_at": stamp, "results": results}, indent=2))
    print("wrote", path)
    bad = [
        r["phase"]
        for r in results
        if r["sequence_gaps"]
        or r["duplicate_executions"]
        or r["executions_without_allow"]
        or r["outbox_pending_or_dead"]
    ]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
