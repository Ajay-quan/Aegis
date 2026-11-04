# Replay semantics

| Mode | What it does | Code | Side effects |
|---|---|---|---|
| A: Cryptographic verification | Verifies the chain, signatures and trust offline | `aegistrace.evidence.verifier`, `aegistrace-verify` | None (offline) |
| B: State reconstruction | Folds recorded events into a state view; the API compares it with the `runs` projection | `replay.engine.reconstruct`, `GET /v1/runs/{id}/replay` | None |
| C: Decision replay | Drives the agent decision loop with **recorded** model responses and tool outcomes, or with a candidate model (new agent version), and reports the first divergence | `replay.engine.replay_decisions` | None |
| D: Execution fork | Creates a **new run** seeded from a finished run's input. Requires scopes `replay:fork` and `runs:write`. | `POST /v1/runs/{id}/fork` | A real new execution, governed like any other |

**Guarantee for A–C:** the `aegistrace.replay` package cannot import persistence, tools, workers, the API, `sqlalchemy`, `httpx`, `redis`, `socket` or `urllib`. `test_replay_package_import_boundary` enforces this. The replay tests also run with sockets monkeypatched to raise.

## Result states (mode C)

| State | Meaning |
|---|---|
| `IDENTICAL` | Every recorded step reproduced |
| `DIVERGED` | The candidate's proposal differs; step, expected and actual are reported |
| `MISSING_DEPENDENCY` | A needed payload was withheld, or no outcome was recorded for a step |
| `INCOMPATIBLE_VERSION` | Unsupported event schema version |
| `INCOMPLETE_HISTORY` | The sequence has gaps |

## Runtime-level determinism

Workers resuming a run (after approval or recovery) reuse recorded model responses by step and recorded tool outcomes by call key. They do not re-query the model or repeat completed tool calls.
