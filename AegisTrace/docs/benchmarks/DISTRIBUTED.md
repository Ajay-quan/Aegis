# Distributed load and recovery — 2026-11-16

Measured with `benchmarks/distributed.py` against the full compose stack (`./aegis up`): API, dispatcher,
1–4 workers, Postgres, Redis, OPA, AegisMem. Load: k6 `governed_runs.js`, **40 concurrent users for 40 s
per phase**. Each run makes one allowed tool call and one denied call, and polls until it finishes. Raw data:
`benchmarks/results/distributed-20261116T160847Z.json`.

**Same single laptop as REPORT.md** (M1 Pro, 8 vCPU Docker VM; load generator on the same machine), with
payload encryption on. The API rate limit was raised for the load test; at the default 600 requests per
minute per token, the 50 ms polling is throttled with 429s. These are not production capacity claims.

## Scaling workers (no faults)

| Workers | Runs completed | Runs/s | End-to-end p50 | p95 | HTTP errors |
|---|---|---|---|---|---|
| 1 | 665 | 15.8 | 2.13 s | 4.20 s | 0% |
| 2 | 852 | 20.5 | 1.63 s | 3.77 s | 0% |
| 4 | 1,345 | 32.7 | 1.14 s | 1.69 s | 0% |

4 workers give about 2× the throughput of 1 and cut p95 latency by 60%. Scaling is sub-linear here because
everything shares one machine's CPU.

## Faults under load (3 workers, fault 8 s into the phase)

| Fault | Runs | Outcome | HTTP errors | What happened |
|---|---|---|---|---|
| Worker SIGKILLed | 894 | all SUCCEEDED | 0% | The killed worker held 3 runs mid-flight; their leases expired and other workers recovered and retried them (`lease_expired` → `recovered` → `retry_due`). |
| Redis restarted | 1,201 | all SUCCEEDED | 1.7% | API requests failed briefly while Redis was down (token-revocation checks fail closed); the outbox redelivered everything. |
| Policy engine (OPA) down 10 s | 1,346 | all SUCCEEDED | 0% | **620 tool calls denied with `policy_engine_unavailable`** (fail closed); none executed without an allow decision. |
| Postgres restarted | 1,031 | all SUCCEEDED | 3.4% | Requests failed during the restart; every run completed afterwards. |

## Consistency after every phase (7,334 runs in total)

| Check | Result |
|---|---|
| Runs left unfinished | 0 |
| Outbox messages pending or dead | 0 |
| Event sequence gaps | 0 |
| Tool executed twice for the same call | 0 |
| Tool executed without a prior allow decision | 0 |
| Receipts verified offline (trust store + external anchor) | **7,334 / 7,334 VALID** |

## Not covered
Multiple machines, network partitions between hosts, Postgres failover to a replica, sustained load beyond
40 s per phase, and real LLM latency (a mock model was used).
