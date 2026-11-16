# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""aegistrace-verify: offline receipt verification.

Exit codes: 0 VALID, 1 verification failed, 2 usage or input error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .anchor import load_anchor
from .trust import TrustStore
from .verifier import Status, verify_bundle


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aegistrace-verify", description=__doc__)
    p.add_argument("bundle", type=Path)
    p.add_argument("--trust", type=Path, required=True, help="trust store JSON you control")
    p.add_argument("--tenant", required=True, help="expected tenant id")
    p.add_argument("--run", required=True, help="expected run id")
    p.add_argument("--anchor", type=Path, help="externally anchored checkpoints (JSON lines)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    try:
        data = args.bundle.read_bytes()
        trust = TrustStore.from_json(json.loads(args.trust.read_text()))
        anchored = load_anchor(args.anchor.read_bytes()) if args.anchor else None
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = verify_bundle(data, trust, args.tenant, args.run, anchored_checkpoints=anchored)
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(
            f"{report.status.value}  ({report.event_count} events, trusted through #{report.trusted_through_sequence})"
        )
        for f in report.findings:
            where = f" [seq {f.sequence}]" if f.sequence is not None else ""
            print(f"  {f.code.value}{where}: {f.detail}")
        for w in report.warnings:
            print(f"  note: {w}")
    return 0 if report.status is Status.VALID else 1


if __name__ == "__main__":
    sys.exit(main())
