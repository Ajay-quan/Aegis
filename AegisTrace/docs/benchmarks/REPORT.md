# Benchmark report — 2026-10-31

All numbers below were measured on this date. Raw data is in `benchmarks/results/`.

**These are single-laptop results.** They are not capacity claims for any production deployment.

## Environment

| | |
|---|---|
| Hardware | Apple M1 Pro, 8 cores, 16 GiB RAM (macOS 27.0) |
| Containers | Docker Desktop 29.2.1 Linux VM: 8 vCPU, 7.65 GiB |
| Software | AegisTrace 0.1.0.dev0, Python 3.12.13, PostgreSQL 17.6 (default config), Redis 7.4, OPA 1.4.2 |
| Topology | 1 API (uvicorn, 1 process), **1 worker**, 1 dispatcher, all in compose on the same VM. k6 1.3.0 runs in a container on the same machine. |

## Evidence path (in-process, `benchmarks/crypto_bench.py`)

| Operation | p50 | p95 | Throughput |
|---|---|---|---|
| Append and hash one event | 41 µs | 46 µs | — |
| Sign checkpoint (Ed25519) | 52 µs | 133 µs | — |
| Verify bundle, 100 events | 6.2 ms | 8.4 ms | ~16k events/s |
| Verify bundle, 1,000 events | 55 ms | 64 ms | ~18k events/s |
| Verify bundle, 10,000 events (3.9 MB zip) | 575 ms | 664 ms | ~17k events/s |
| Reconstruct state, 10,000 events | 2.2 ms | 2.8 ms | ~4.6M events/s |

## End-to-end governed runs (`benchmarks/k6/governed_runs.js`)

Each iteration:
1. Submits a run (one allowed `calc.add` call and one **denied** `email.send` call).
2. Polls every 50 ms until the run reaches a terminal state.

A run counts as completed only if it ends `SUCCEEDED`. Each profile ran for 20 seconds.

| Concurrent VUs | Completed runs | Not succeeded | Runs/s | End-to-end p50 | End-to-end p95 | HTTP p95 | HTTP errors |
|---|---|---|---|---|---|---|---|
| 1 | 96 | 0 | 4.8 | 192 ms | 247 ms | 11 ms | 0 / 525 |
| 10 | 568 | 0 | 27.7 | 353 ms | 443 ms | 23 ms | 0 / 4,316 |
| 50 | 515 | 0 | 23.8 | 2.04 s | 2.44 s | 210 ms | 0 / 6,122 |

**Post-run consistency check:**
- 1,182 of 1,182 runs `SUCCEEDED`.
- 0 outbox rows pending or dead.
- 0 sequence gaps.
- 1,182 of 1,182 receipts verified `VALID` against the trust store and the external anchor.

**Interpretation:** one worker saturates at about 24–28 governed runs/s on this machine. At 50 VUs the extra latency is queueing. The 100 and 500 VU profiles were **not run**; they need more workers and dedicated hardware.

## Policy and gateway latency (worker histograms during the k6 runs)

| Metric | Samples | p95 bound |
|---|---|---|
| OPA evaluation (`aegis_policy_eval_seconds`) | 2,358 | ≤ 2.5 ms (96.7% of samples ≤ 2.5 ms) |
| Gateway overhead before execution (`aegis_gateway_overhead_seconds`, allowed calls) | 1,179 | ≤ 10 ms (95.1% of samples ≤ 10 ms) |

These are histogram bucket bounds, not exact percentiles. The SLO target of p95 below 20 ms for policy evaluation was met on this workload.

## Limitations

- Everything ran on one machine, so load generator and system shared CPU.
- Default Postgres configuration.
- Mock model, so there is no LLM latency.
- No network latency between components.
- Short durations (20 s per profile).
