# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Run lifecycle operations. Each public function runs inside a caller-supplied
tenant-bound transaction, so state change + event + outbox commit atomically."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, text

from aegistrace.evidence.canonical import canonicalize
from aegistrace.evidence.checkpoint import CheckpointBody, sign_checkpoint
from aegistrace.evidence.events import Event, SealedEvent, genesis_hash, payload_digest
from aegistrace.evidence.signing import Signer

from .states import OPERATOR_ONLY, TERMINAL, RunState, check_transition


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def now_rfc3339() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class NotFound(LookupError):
    pass


class Conflict(Exception):
    pass


class QuotaExceeded(Exception):
    """Tenant has reached its concurrent-run limit (resource governance, §43)."""


class StaleLease(Exception):
    """The caller no longer owns the run (lease expired or fencing token advanced)."""


class OperatorRequired(PermissionError):
    pass


@dataclass(frozen=True)
class Actor:
    id: str
    kind: str  # "user" | "service" | "worker" | "system"


@dataclass
class RunRow:
    id: str
    tenant_id: str
    project_id: str
    agent_id: str
    state: RunState
    head_hash: str
    last_sequence: int
    attempt: int
    max_attempts: int
    fencing_token: int
    lease_owner: str | None


def _lock_run(conn: Connection, run_id: str) -> RunRow:
    row = conn.execute(
        text(
            "SELECT id, tenant_id, project_id, agent_id, state, head_hash, last_sequence, attempt, "
            "max_attempts, fencing_token, lease_owner FROM runs WHERE id = :id FOR UPDATE"
        ),
        {"id": run_id},
    ).one_or_none()
    if row is None:
        raise NotFound(run_id)
    return RunRow(
        id=row[0],
        tenant_id=row[1],
        project_id=row[2],
        agent_id=row[3],
        state=RunState(row[4]),
        head_hash=row[5],
        last_sequence=row[6],
        attempt=row[7],
        max_attempts=row[8],
        fencing_token=row[9],
        lease_owner=row[10],
    )


def _append_event(
    conn: Connection,
    run: RunRow,
    event_type: str,
    actor: Actor,
    payload: Any,
    causation_id: str | None = None,
) -> SealedEvent:
    ev = Event(
        event_id=new_id("evt"),
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        run_id=run.id,
        sequence_number=run.last_sequence + 1,
        event_type=event_type,
        schema_version=1,
        actor_id=actor.id,
        causation_id=causation_id,
        correlation_id=run.id,
        timestamp=now_rfc3339(),
        payload_digest=payload_digest(payload),
        previous_event_hash=run.head_hash,
    )
    sealed = SealedEvent(ev, ev.compute_hash(), payload)
    # UNIQUE (run_id, sequence_number) is the backstop against concurrent appends.
    conn.execute(
        text(
            "INSERT INTO events (event_id, tenant_id, run_id, sequence_number, event_type, "
            "current_event_hash, record) VALUES (:id, :t, :r, :s, :ty, :h, CAST(:rec AS jsonb))"
        ),
        {
            "id": ev.event_id,
            "t": run.tenant_id,
            "r": run.id,
            "s": ev.sequence_number,
            "ty": event_type,
            "h": sealed.current_event_hash,
            "rec": canonicalize(sealed.to_record()).decode(),
        },
    )
    run.last_sequence = ev.sequence_number
    run.head_hash = sealed.current_event_hash
    conn.execute(
        text("UPDATE runs SET head_hash = :h, last_sequence = :s, updated_at = now() WHERE id = :id"),
        {"h": run.head_hash, "s": run.last_sequence, "id": run.id},
    )
    return sealed


def enqueue(
    conn: Connection,
    tenant_id: str,
    run_id: str | None,
    topic: str,
    payload: dict[str, Any],
    available_at: datetime | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO outbox (tenant_id, run_id, topic, payload, available_at) "
            "VALUES (:t, :r, :topic, CAST(:p AS jsonb), COALESCE(:at, now()))"
        ),
        {"t": tenant_id, "r": run_id, "topic": topic, "p": json.dumps(payload), "at": available_at},
    )


def transition(
    conn: Connection,
    run_id: str,
    target: RunState,
    actor: Actor,
    payload: dict[str, Any] | None = None,
    *,
    fencing_token: int | None = None,
) -> RunRow:
    """Validate and apply a state transition with its audit event.

    If fencing_token is given, the caller must still hold that exact lease
    generation; a stale worker gets StaleLease and changes nothing.
    """
    run = _lock_run(conn, run_id)
    if fencing_token is not None and fencing_token != run.fencing_token:
        raise StaleLease(run_id)
    check_transition(run.state, target)
    if (run.state, target) in OPERATOR_ONLY and actor.kind != "user":
        raise OperatorRequired("reconciliation requires a human operator")
    prev = run.state
    run.state = target
    params: dict[str, Any] = {"st": target.value, "id": run.id}
    sql = "UPDATE runs SET state = :st, updated_at = now()"
    if target in TERMINAL or target in (
        RunState.QUEUED,
        RunState.WAITING_FOR_APPROVAL,
        RunState.RETRY_SCHEDULED,
        RunState.NEEDS_RECONCILIATION,
    ):
        sql += ", lease_owner = NULL, lease_expires_at = NULL"
        run.lease_owner = None
    if target in TERMINAL and payload is not None and "result" in payload:
        sql += ", result = CAST(:res AS jsonb)"
        params["res"] = json.dumps(payload["result"])
    conn.execute(text(sql + " WHERE id = :id"), params)
    _append_event(conn, run, "run.state_changed", actor, {"from": prev.value, "to": target.value, **(payload or {})})
    if target is RunState.QUEUED:
        enqueue(conn, run.tenant_id, run.id, "run.execute", {"run_id": run.id})
    return run


def record_event(
    conn: Connection, run_id: str, event_type: str, actor: Actor, payload: Any, *, fencing_token: int | None = None
) -> SealedEvent:
    run = _lock_run(conn, run_id)
    if fencing_token is not None and fencing_token != run.fencing_token:
        raise StaleLease(run_id)
    if run.state in TERMINAL:
        raise Conflict("run is terminal")
    return _append_event(conn, run, event_type, actor, payload)


def create_run(
    conn: Connection,
    tenant_id: str,
    agent_id: str,
    run_input: dict[str, Any],
    actor: Actor,
    idempotency_key: str,
) -> tuple[str, bool]:
    """Returns (run_id, created). Same key + same request => same run.
    Same key + different request => Conflict."""
    digest = payload_digest({"agent_id": agent_id, "input": run_input})
    existing = conn.execute(
        text("SELECT request_digest, resource_id FROM idempotency_keys WHERE key = :k"),
        {"k": idempotency_key},
    ).one_or_none()
    if existing:
        if existing[0] != digest:
            raise Conflict("idempotency key reused with a different request")
        return existing[1], False

    agent = conn.execute(text("SELECT project_id FROM agents WHERE id = :a"), {"a": agent_id}).one_or_none()
    if agent is None:
        raise NotFound(agent_id)
    # Per-tenant advisory lock serializes quota checks so concurrent submissions cannot overshoot.
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:t))"), {"t": tenant_id})
    limit = conn.execute(text("SELECT max_active_runs FROM tenants WHERE id = :t"), {"t": tenant_id}).scalar_one()
    active = conn.execute(
        text("SELECT count(*) FROM runs WHERE state NOT IN ('SUCCEEDED', 'FAILED', 'CANCELLED', 'TIMED_OUT')")
    ).scalar_one()
    if active >= limit:
        raise QuotaExceeded(f"tenant has {active} active runs (limit {limit})")
    run_id = new_id("run")
    inserted = conn.execute(
        text(
            "INSERT INTO idempotency_keys (tenant_id, key, request_digest, resource_id) "
            "VALUES (:t, :k, :d, :r) ON CONFLICT DO NOTHING RETURNING resource_id"
        ),
        {"t": tenant_id, "k": idempotency_key, "d": digest, "r": run_id},
    ).one_or_none()
    if inserted is None:
        # Lost a race: the concurrent winner has committed by now (READ COMMITTED).
        winner = conn.execute(
            text("SELECT request_digest, resource_id FROM idempotency_keys WHERE key = :k"),
            {"k": idempotency_key},
        ).one()
        if winner[0] != digest:
            raise Conflict("idempotency key reused with a different request")
        return winner[1], False
    conn.execute(
        text(
            "INSERT INTO runs (id, tenant_id, project_id, agent_id, state, input, head_hash, last_sequence) "
            "VALUES (:id, :t, :p, :a, 'CREATED', CAST(:in AS jsonb), :g, 0)"
        ),
        {
            "id": run_id,
            "t": tenant_id,
            "p": agent[0],
            "a": agent_id,
            "in": json.dumps(run_input),
            "g": genesis_hash(tenant_id, run_id),
        },
    )
    run = _lock_run(conn, run_id)
    _append_event(conn, run, "run.created", actor, {"agent_id": agent_id, "input": run_input})
    transition(conn, run_id, RunState.VALIDATING, Actor("system", "system"))
    transition(conn, run_id, RunState.QUEUED, Actor("system", "system"))
    return run_id, True


def checkpoint(conn: Connection, run_id: str, signer: Signer) -> dict[str, Any]:
    """Sign the current head. Idempotent per (run, last_sequence)."""
    run = _lock_run(conn, run_id)
    existing = conn.execute(
        text("SELECT record FROM checkpoints WHERE run_id = :r AND last_sequence = :s"),
        {"r": run_id, "s": run.last_sequence},
    ).one_or_none()
    if existing:
        return dict(existing[0])
    body = CheckpointBody(run.tenant_id, run.id, 1, run.last_sequence, run.head_hash, signer.key_id, now_rfc3339())
    cp = sign_checkpoint(body, signer)
    conn.execute(
        text(
            "INSERT INTO checkpoints (tenant_id, run_id, last_sequence, key_id, record) "
            "VALUES (:t, :r, :s, :k, CAST(:rec AS jsonb))"
        ),
        {"t": run.tenant_id, "r": run_id, "s": run.last_sequence, "k": signer.key_id, "rec": json.dumps(cp)},
    )
    return cp


def load_events(conn: Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        text("SELECT record FROM events WHERE run_id = :r ORDER BY sequence_number"), {"r": run_id}
    ).all()
    return [dict(r[0]) for r in rows]
