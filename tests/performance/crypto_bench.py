# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Evidence-path microbenchmarks. Writes raw JSON to tests/performance/results/.
Usage: uv run python tests/performance/crypto_bench.py"""

from __future__ import annotations

import json
import platform
import statistics
import subprocess
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

from aegisruntime.replay.engine import reconstruct
from aegistrace.evidence.bundle import write_bundle
from aegistrace.evidence.checkpoint import CheckpointBody, sign_checkpoint
from aegistrace.evidence.events import ChainBuilder
from aegistrace.evidence.signing import LocalEd25519Signer, b64
from aegistrace.evidence.trust import TrustStore
from aegistrace.evidence.verifier import Status, verify_bundle

PAYLOAD = {"tool": "docs.read", "arguments": {"doc_id": "q3-report", "page": 7}, "classification": "INTERNAL"}


def timeit(fn, n):
    samples = []
    for _ in range(n):
        t = time.perf_counter_ns()
        fn()
        samples.append((time.perf_counter_ns() - t) / 1e3)
    samples.sort()
    return {
        "n": n,
        "p50_us": samples[n // 2],
        "p95_us": samples[int(n * 0.95)],
        "p99_us": samples[int(n * 0.99)],
        "mean_us": statistics.fmean(samples),
    }


def build(n):
    c = ChainBuilder("tnt_bench", "prj", "run_bench")
    for i in range(n):
        c.append(
            event_id=f"e{i}",
            event_type="tool.execution_succeeded",
            actor_id="wrk",
            correlation_id="run_bench",
            timestamp="2026-10-31T00:00:00Z",
            payload={**PAYLOAD, "i": i},
        )
    return c


def env():
    def sh(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout.strip()
        except OSError:
            return ""

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu": sh(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor(),
        "cpu_count": sh(["sysctl", "-n", "hw.ncpu"]),
        "memory_bytes": sh(["sysctl", "-n", "hw.memsize"]),
    }


def main():
    signer = LocalEd25519Signer()
    trust = TrustStore.from_json(
        {
            "version": 1,
            "keys": [
                {
                    "key_id": signer.key_id,
                    "public_key": b64(signer.public_key_raw()),
                    "not_before": "2026-01-01T00:00:00Z",
                }
            ],
        }
    )
    out = {"started_at": datetime.now(UTC).isoformat(), "environment": env(), "results": {}}
    R = out["results"]

    c = build(1)
    R["event_append_hash"] = timeit(
        lambda: c.append(
            event_id="x",
            event_type="t",
            actor_id="a",
            correlation_id="r",
            timestamp="2026-10-31T00:00:00Z",
            payload=PAYLOAD,
        ),
        5000,
    )
    body = CheckpointBody("tnt_bench", "run_bench", 1, 1, c.head, signer.key_id, "2026-10-31T00:00:00Z")
    R["checkpoint_sign"] = timeit(lambda: sign_checkpoint(body, signer), 2000)

    for n in (100, 1000, 10_000):
        chain = build(n)
        cp = sign_checkpoint(
            CheckpointBody("tnt_bench", "run_bench", 1, n, chain.head, signer.key_id, "2026-10-31T00:00:00Z"), signer
        )
        bundle = write_bundle("tnt_bench", "run_bench", chain.events, [cp])
        assert verify_bundle(bundle, trust, "tnt_bench", "run_bench").status is Status.VALID
        reps = 20 if n <= 1000 else 5
        stats = timeit(lambda b=bundle: verify_bundle(b, trust, "tnt_bench", "run_bench"), reps)
        tracemalloc.start()
        verify_bundle(bundle, trust, "tnt_bench", "run_bench")
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        records = [e.to_record() for e in chain.events]
        recon = timeit(lambda r=records: reconstruct(r), reps)
        R[f"verify_{n}_events"] = {
            **stats,
            "events_per_second": n / (stats["p50_us"] / 1e6),
            "bundle_bytes": len(bundle),
            "peak_python_heap_bytes": peak,
        }
        R[f"reconstruct_{n}_events"] = {**recon, "events_per_second": n / (recon["p50_us"] / 1e6)}

    path = Path(__file__).parent / "results" / f"crypto-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(out, indent=2))
    for k, v in R.items():
        extra = f"  {v['events_per_second']:,.0f} ev/s" if "events_per_second" in v else ""
        print(f"{k:<26} p50 {v['p50_us']:>10.1f} us  p95 {v['p95_us']:>10.1f} us{extra}")
    print(f"raw: {path}")


if __name__ == "__main__":
    main()
