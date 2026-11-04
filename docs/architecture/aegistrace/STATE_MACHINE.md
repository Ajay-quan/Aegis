# Execution state machine

Source of truth: `TRANSITIONS` in `packages/aegisruntime/src/aegisruntime/orchestration/states.py`.

```mermaid
stateDiagram-v2
  [*] --> CREATED
  CREATED --> VALIDATING
  CREATED --> CANCELLED
  VALIDATING --> QUEUED
  VALIDATING --> FAILED
  VALIDATING --> CANCELLED
  QUEUED --> RUNNING : worker claim (fencing token +1)
  QUEUED --> CANCELLED
  QUEUED --> TIMED_OUT
  RUNNING --> WAITING_FOR_APPROVAL
  RUNNING --> RETRY_SCHEDULED : retryable model error
  RUNNING --> RECOVERING : lease expired
  RUNNING --> SUCCEEDED
  RUNNING --> FAILED
  RUNNING --> CANCELLED
  RUNNING --> TIMED_OUT
  RUNNING --> NEEDS_RECONCILIATION
  WAITING_FOR_APPROVAL --> QUEUED : approved
  WAITING_FOR_APPROVAL --> FAILED : rejected
  WAITING_FOR_APPROVAL --> CANCELLED
  WAITING_FOR_APPROVAL --> TIMED_OUT
  RETRY_SCHEDULED --> QUEUED : backoff elapsed
  RETRY_SCHEDULED --> FAILED
  RETRY_SCHEDULED --> CANCELLED
  RECOVERING --> RETRY_SCHEDULED : no unresolved side effect, budget left
  RECOVERING --> QUEUED
  RECOVERING --> FAILED : retry budget exhausted
  RECOVERING --> NEEDS_RECONCILIATION : non-retry-safe tool outcome unknown
  RECOVERING --> CANCELLED
  NEEDS_RECONCILIATION --> SUCCEEDED : human operator only
  NEEDS_RECONCILIATION --> FAILED : human operator only
  NEEDS_RECONCILIATION --> QUEUED : human operator only
  NEEDS_RECONCILIATION --> CANCELLED : human operator only
  SUCCEEDED --> [*]
  FAILED --> [*]
  CANCELLED --> [*]
  TIMED_OUT --> [*]
```

## Rules enforced on every transition (`service.transition`)

1. Lock the run row (`SELECT … FOR UPDATE`).
2. If the caller supplied a fencing token, it must equal the current one. Otherwise the result is `StaleLease` and nothing is written.
3. The target state must be in `TRANSITIONS[current]`. Otherwise the result is `IllegalTransition`.
4. Leaving `NEEDS_RECONCILIATION` requires an actor of kind `user` (`OperatorRequired`).
5. Append a `run.state_changed` event with the next sequence number. `UNIQUE(run_id, sequence_number)` is the backstop.
6. Update the projection (`runs.state`, head hash, last sequence), and clear the lease when the run comes to rest.
7. Write an outbox message when the target is `QUEUED`.
8. All of this commits in the caller's single transaction.

## Uncertain external effects (INV-008)

The gateway writes `tool.execution_started` with `retry_safe` before execution, and an outcome event after it. During recovery, if any non-retry-safe execution has a start event but no outcome, the run goes to `NEEDS_RECONCILIATION` and is **never** retried automatically. Exactly-once execution is not claimed. Retry-safe tools receive a stable idempotency key, derived from the action digest and step number.

Tests: `tests/integration/test_kernel.py`, `tests/e2e/test_flagship.py::test_uc05_*`.
