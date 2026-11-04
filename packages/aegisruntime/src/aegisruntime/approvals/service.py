# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, text

from aegisruntime.orchestration.service import Actor, Conflict, NotFound, _lock_run, new_id, record_event, transition
from aegisruntime.orchestration.states import RunState

DEFAULT_TTL = timedelta(hours=1)


@dataclass(frozen=True)
class ApprovalRequest:
    run_id: str
    agent_id: str
    tool: str
    action_digest: str
    arguments_digest: str
    resource: str | None
    risk_class: int
    policy_revision: str
    summary: dict[str, Any]


class ApprovalDenied(PermissionError):
    pass


def expire_stale(conn: Connection, run_id: str) -> None:
    conn.execute(
        text(
            "UPDATE approvals SET status = 'expired' WHERE run_id = :r AND status IN ('pending', 'approved') "
            "AND expires_at <= now()"
        ),
        {"r": run_id},
    )


def find_live(conn: Connection, run_id: str, action_digest: str) -> tuple[str, str, str] | None:
    """(id, status, policy_revision) of the live approval for this exact action."""
    expire_stale(conn, run_id)
    row = conn.execute(
        text(
            "SELECT id, status, policy_revision FROM approvals WHERE run_id = :r AND action_digest = :d "
            "AND status IN ('pending', 'approved')"
        ),
        {"r": run_id, "d": action_digest},
    ).one_or_none()
    return (row[0], row[1], row[2]) if row else None


def was_rejected(conn: Connection, run_id: str, action_digest: str) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM approvals WHERE run_id = :r AND action_digest = :d AND status = 'rejected' LIMIT 1"),
            {"r": run_id, "d": action_digest},
        ).first()
        is not None
    )


def request(conn: Connection, tenant_id: str, req: ApprovalRequest, ttl: timedelta = DEFAULT_TTL) -> str:
    live = find_live(conn, req.run_id, req.action_digest)
    if live:
        return live[0]
    approval_id = new_id("apr")
    conn.execute(
        text(
            "INSERT INTO approvals (id, tenant_id, run_id, agent_id, tool, action_digest, arguments_digest, resource, "
            "risk_class, policy_revision, summary, expires_at) VALUES (:id, :t, :r, :a, :tool, :d, :ad, :res, :rc, "
            ":pr, CAST(:s AS jsonb), now() + :ttl)"
        ),
        {
            "id": approval_id,
            "t": tenant_id,
            "r": req.run_id,
            "a": req.agent_id,
            "tool": req.tool,
            "d": req.action_digest,
            "ad": req.arguments_digest,
            "res": req.resource,
            "rc": req.risk_class,
            "pr": req.policy_revision,
            "s": json.dumps(req.summary),
            "ttl": ttl,
        },
    )
    return approval_id


def decide(conn: Connection, approval_id: str, approver: Actor, approve: bool) -> str:
    """Race-safe: only one decision can move an approval out of 'pending'."""
    if approver.kind != "user":
        raise ApprovalDenied("only human users may decide approvals")
    row = conn.execute(text("SELECT run_id, agent_id FROM approvals WHERE id = :i"), {"i": approval_id}).one_or_none()
    if row is None:
        raise NotFound(approval_id)
    run_id, agent_id = row
    if approver.id == agent_id:
        raise ApprovalDenied("requesting principal cannot approve its own request")
    run = _lock_run(conn, run_id)
    status = "approved" if approve else "rejected"
    updated = conn.execute(
        text(
            "UPDATE approvals SET status = :s, decided_by = :u, decided_at = now() "
            "WHERE id = :i AND status = 'pending' AND expires_at > now() RETURNING action_digest"
        ),
        {"s": status, "u": approver.id, "i": approval_id},
    ).one_or_none()
    if updated is None:
        raise Conflict("approval is not pending or has expired")
    record_event(
        conn,
        run_id,
        "approval.decided",
        approver,
        {"approval_id": approval_id, "decision": status, "action_digest": updated[0]},
    )
    if run.state is RunState.WAITING_FOR_APPROVAL:
        if approve:
            transition(conn, run_id, RunState.QUEUED, approver, {"reason": "approval_granted"})
        else:
            transition(
                conn,
                run_id,
                RunState.FAILED,
                approver,
                {"reason": "approval_rejected", "result": {"error": "approval_rejected"}},
            )
    return status


def consume(conn: Connection, run_id: str, action_digest: str, policy_revision: str) -> str | None:
    """Atomically consume the approval for this exact action. Returns its id,
    or None if there is no valid, unexpired approval for this exact digest
    under the current policy revision."""
    row = conn.execute(
        text(
            "UPDATE approvals SET status = 'consumed', consumed_at = now() WHERE run_id = :r "
            "AND action_digest = :d AND status = 'approved' AND expires_at > now() AND policy_revision = :pr "
            "RETURNING id"
        ),
        {"r": run_id, "d": action_digest, "pr": policy_revision},
    ).one_or_none()
    return row[0] if row else None
