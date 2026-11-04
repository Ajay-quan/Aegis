# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Demonstration 3: export a signed receipt, tamper with it, verify offline.

Writes sample bundles and a trust store to examples/receipts/. Every key here
is a throwaway development key generated on each run.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # the demo reuses the test fixtures' run builder

from tests.conftest import RUN, TENANT, build_run, edit_events, repack, trust_doc, unpack  # noqa: E402

OUT = ROOT / "examples" / "receipts"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fx = build_run()
    (OUT / "trust.json").write_text(json.dumps(trust_doc(fx.signer), indent=2))

    def mutate(evs):
        evs[1]["payload"]["doc"] = "secret-plans"
        return evs

    def flip_sig(b: bytes) -> bytes:
        files = unpack(b)
        cps = json.loads(files["checkpoints.json"])
        sig = bytearray(base64.b64decode(cps[0]["signature"]))
        sig[0] ^= 1
        cps[0]["signature"] = base64.b64encode(bytes(sig)).decode()
        files["checkpoints.json"] = json.dumps(cps).encode()
        return repack(files)

    def corrupt_artifact(b: bytes) -> bytes:
        files = unpack(b)
        files[next(n for n in files if n.startswith("artifacts/"))] = b"forged"
        return repack(files)

    def swap(evs):
        evs[1], evs[2] = evs[2], evs[1]
        return evs

    samples = {
        "valid": fx.bundle,
        "tampered-event": edit_events(fx.bundle, mutate),
        "deleted-event": edit_events(fx.bundle, lambda e: e[:2] + e[3:]),
        "reordered-events": edit_events(fx.bundle, swap),
        "modified-artifact": corrupt_artifact(fx.bundle),
        "invalid-signature": flip_sig(fx.bundle),
    }
    for name, data in samples.items():
        path = OUT / f"{name}.zip"
        path.write_bytes(data)
        print(f"\n$ aegistrace-verify {path.name}", flush=True)
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                sys.executable,
                "-m",
                "aegistrace.evidence.cli",
                str(path),
                "--trust",
                str(OUT / "trust.json"),
                "--tenant",
                TENANT,
                "--run",
                RUN,
            ],
            check=False,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
