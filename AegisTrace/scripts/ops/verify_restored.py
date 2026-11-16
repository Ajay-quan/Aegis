# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Verify every run in a (restored) database: export each run's events and
stored checkpoints as a bundle and verify offline against the trust store and
the external anchor. Exits non-zero if any run fails.

Payload content is encrypted at rest. With --kek (the key-encryption key
file) payloads are decrypted and verified against their digests; without it,
or for erased runs, they are verified digest-only ("withheld"), which still
proves the chain, hashes and signatures intact."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, text

from aegistrace.evidence.anchor import load_anchor
from aegistrace.evidence.bundle import write_bundle_records
from aegistrace.evidence.trust import TrustStore
from aegistrace.evidence.verifier import Status, verify_bundle
from aegistrace.persistence import sealing


def open_records(conn, records: list[dict]) -> list[dict]:
    """Decrypt where possible; otherwise withhold sealed payloads (their digests still bind them)."""
    out = []
    for r in records:
        sealed = isinstance(r.get("payload"), dict) and any(sealing.is_sealed(v) for v in r["payload"].values())
        if not sealed:
            out.append(r)
        elif sealing.enabled():
            out.append(sealing.open_event_record(conn, r))
        else:
            out.append({k: v for k, v in r.items() if k != "payload"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="owner-role URL of the restored database")
    ap.add_argument("--trust", required=True)
    ap.add_argument("--anchor")
    ap.add_argument("--kek", help="payload key-encryption key file (decrypt and check payloads too)")
    ap.add_argument("--since", help="only runs created at or after this ISO timestamp")
    a = ap.parse_args()
    if a.kek:
        sealing.configure(sealing.LocalKeyWrapper.from_file(a.kek))
    trust = TrustStore.from_json(json.loads(Path(a.trust).read_text()))
    anchor = load_anchor(Path(a.anchor).read_bytes()) if a.anchor and Path(a.anchor).exists() else None
    eng = create_engine(a.db)
    results: Counter[str] = Counter()
    failures = []
    with eng.connect() as c:
        runs = c.execute(
            text(
                "SELECT tenant_id, id FROM runs WHERE (CAST(:s AS timestamptz) IS NULL OR created_at >= "
                "CAST(:s AS timestamptz)) ORDER BY created_at"
            ),
            {"s": a.since},
        ).all()
        for tenant_id, run_id in runs:
            records = open_records(
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
                write_bundle_records(tenant_id, run_id, records, cps, {}),
                trust,
                tenant_id,
                run_id,
                anchored_checkpoints=anchor,
            )
            results[rep.status.value] += 1
            # Runs never checkpointed (e.g. still queued) are INCOMPLETE, not corrupt.
            if rep.status not in (Status.VALID, Status.INCOMPLETE_HISTORY):
                failures.append((run_id, rep.status.value, rep.findings[0].detail if rep.findings else ""))
    print(f"runs checked: {len(runs)}  results: {dict(results)}")
    for f in failures:
        print("FAIL", *f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
