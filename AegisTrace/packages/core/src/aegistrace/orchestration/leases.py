# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Worker leases with fencing tokens, and recovery of abandoned runs.

A worker owns a run only while it holds the current fencing token. Every
write a worker makes passes that token; once recovery or another claim
advances it, the old worker's writes are rejected (StaleLease).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Connection, Engine, text

from aegistrace.observability import RECOVERIES
from aegistrace.persistence.db import tenant_tx

from .service import Actor, StaleLease, _lock_run, transition
from .states import RunState

SYSTEM = Actor("system:recovery", "system")


@dataclass(frozen=True)
class Lease:
    run_id: str
    fencing_token: int
    attempt: int


def claim(conn: Connection, run_id: str, worker_id: str, ttl: timedelta) -> Lease | None:
    run = _lock_run(conn, run_id)
    if run.state is not RunState.QUEUED:
        return None  # duplicate delivery or already handled: no-op
    token = run.fencing_token + 1
    conn.execute(
        text(
            "UPDATE runs SET lease_owner = :w, lease_expires_at = now() + :ttl, "
            "fencing_token = :tok, attempt = attempt + 1 WHERE id = :id"
        ),
        {"w": worker_id, "ttl": ttl, "tok": token, "id": run_id},
    )
    transition(
        conn,
        run_id,
        RunState.RUNNING,
        Actor(worker_id, "worker"),
        {"worker_id": worker_id, "fencing_token": token, "attempt": run.attempt + 1},
        fencing_token=token,
    )
    return Lease(run_id, token, run.attempt + 1)


def heartbeat(conn: Connection, lease: Lease, ttl: timedelta) -> None:
    row = conn.execute(
        text(
            "UPDATE runs SET lease_expires_at = now() + :ttl WHERE id = :id AND fencing_token = :tok "
            "AND state = 'RUNNING' AND lease_expires_at > now() RETURNING id"
        ),
        {"ttl": ttl, "id": lease.run_id, "tok": lease.fencing_token},
    ).one_or_none()
    if row is None:
        raise StaleLease(lease.run_id)


def backoff(attempt: int, base: float = 1.0, cap: float = 300.0) -> timedelta:
    """Exponential backoff with full jitter."""
    return timedelta(seconds=random.uniform(0, min(cap, base * 2**attempt)))  # noqa: S311


def _has_unresolved_side_effect(conn: Connection, run_id: str) -> bool:
    """True if a non-idempotent tool call started but its outcome was never recorded."""
    row = conn.execute(
        text(
            """
            SELECT 1 FROM events s
            WHERE s.run_id = :r AND s.event_type = 'tool.execution_started'
              AND (s.record->'payload'->>'retry_safe')::boolean IS NOT TRUE
              AND NOT EXISTS (
                SELECT 1 FROM events f WHERE f.run_id = s.run_id
                  AND f.event_type IN ('tool.execution_succeeded', 'tool.execution_failed')
                  AND f.record->'payload'->>'execution_id' = s.record->'payload'->>'execution_id')
            LIMIT 1
            """
        ),
        {"r": run_id},
    ).one_or_none()
    return row is not None


def recover_run(conn: Connection, run_id: str) -> RunState:
    run = _lock_run(conn, run_id)
    expired = conn.execute(
        text("SELECT lease_expires_at < now() FROM runs WHERE id = :id"), {"id": run_id}
    ).scalar_one()
    if run.state is not RunState.RUNNING or not expired:
        return run.state
    # Advance the fencing token first so the old worker is fenced out.
    conn.execute(text("UPDATE runs SET fencing_token = fencing_token + 1 WHERE id = :id"), {"id": run_id})
    transition(
        conn, run_id, RunState.RECOVERING, SYSTEM, {"reason": "lease_expired", "previous_owner": run.lease_owner}
    )
    if _has_unresolved_side_effect(conn, run_id):
        transition(
            conn,
            run_id,
            RunState.NEEDS_RECONCILIATION,
            SYSTEM,
            {"reason": "tool outcome unknown after worker loss; automatic retry unsafe"},
        )
        return RunState.NEEDS_RECONCILIATION
    if run.attempt >= run.max_attempts:
        transition(conn, run_id, RunState.FAILED, SYSTEM, {"reason": "retry_budget_exhausted"})
        return RunState.FAILED
    delay = backoff(run.attempt)
    conn.execute(
        text("UPDATE runs SET next_attempt_at = :t WHERE id = :id"), {"t": datetime.now(UTC) + delay, "id": run_id}
    )
    transition(
        conn,
        run_id,
        RunState.RETRY_SCHEDULED,
        SYSTEM,
        {"reason": "recovered", "retry_in_ms": int(delay.total_seconds() * 1000)},
    )
    return RunState.RETRY_SCHEDULED


def _scan(engine: Engine, fn: str, limit: int) -> list[tuple[str, str]]:
    with engine.begin() as conn:
        return [(t, r) for t, r in conn.execute(text(f"SELECT * FROM {fn}(:l)"), {"l": limit})]  # noqa: S608


def recover_expired(engine: Engine, limit: int = 100) -> dict[str, RunState]:
    results = {}
    for tenant_id, run_id in _scan(engine, "scheduler_expired_leases", limit):
        with tenant_tx(engine, tenant_id) as conn:
            results[run_id] = recover_run(conn, run_id)
        RECOVERIES.labels(results[run_id].value).inc()
    return results


def requeue_due_retries(engine: Engine, limit: int = 100) -> list[str]:
    done = []
    for tenant_id, run_id in _scan(engine, "scheduler_due_retries", limit):
        with tenant_tx(engine, tenant_id) as conn:
            if _lock_run(conn, run_id).state is RunState.RETRY_SCHEDULED:
                transition(conn, run_id, RunState.QUEUED, SYSTEM, {"reason": "retry_due"})
                done.append(run_id)
    return done


def expire_overdue(engine: Engine, limit: int = 100) -> list[str]:
    done = []
    for tenant_id, run_id in _scan(engine, "scheduler_overdue_runs", limit):
        with tenant_tx(engine, tenant_id) as conn:
            run = _lock_run(conn, run_id)
            if run.state in (RunState.QUEUED, RunState.RUNNING, RunState.WAITING_FOR_APPROVAL):
                conn.execute(text("UPDATE runs SET fencing_token = fencing_token + 1 WHERE id = :id"), {"id": run_id})
                transition(conn, run_id, RunState.TIMED_OUT, SYSTEM, {"reason": "deadline_exceeded"})
                done.append(run_id)
    return done
