# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Organization roles. Effective permissions = token scopes ∩ role scopes.

Owner      everything, including managing owners and admins
Admin      rules, grants, approvals, erasure, API keys, members (not owners)
Developer  build and run agents, read run content and memories
Viewer     read runs, agents, approvals and the audit log; no run content

API keys and service tokens are not members: their scopes are fixed when they
are issued (an API key never exceeds its creator's scopes).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from aegistrace.persistence.audit import audit

from .jwt import Principal

MEMBERS_SCOPE = "members:manage"
ROLES = ("owner", "admin", "developer", "viewer")
# Viewers can export receipts: without payloads:read they are redacted (digests only), still verifiable.
_VIEWER = {"runs:read", "agents:read", "approvals:read", "replay:read", "audit:read", "receipts:export"}
_DEVELOPER = _VIEWER | {"runs:write", "agents:write", "payloads:read", "replay:fork"}
_ADMIN = _DEVELOPER | {
    "policies:write",
    "approvals:decide",
    "runs:reconcile",
    "data:erase",
    "keys:manage",
    MEMBERS_SCOPE,
}
ROLE_SCOPES: dict[str, frozenset[str]] = {
    "viewer": frozenset(_VIEWER),
    "developer": frozenset(_DEVELOPER),
    "admin": frozenset(_ADMIN),
    "owner": frozenset(_ADMIN),
}


class NotAMember(Exception):
    pass


def resolve(conn: Connection, p: Principal) -> tuple[Principal, str]:
    """Apply the member's role to a signed-in user's token. Bootstraps the first owner."""
    row = conn.execute(text("SELECT role FROM members WHERE subject = :s"), {"s": p.subject}).one_or_none()
    if row is None:
        anyone = conn.execute(text("SELECT 1 FROM members LIMIT 1")).first()
        if anyone is not None:
            raise NotAMember(p.subject)
        conn.execute(
            text(
                "INSERT INTO members (tenant_id, subject, role, added_by) VALUES (:t, :s, 'owner', 'bootstrap') "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": p.tenant_id, "s": p.subject},
        )
        audit(conn, p.tenant_id, p.subject, "member.bootstrapped_owner", p.subject, {})
        role = conn.execute(text("SELECT role FROM members WHERE subject = :s"), {"s": p.subject}).scalar_one()
    else:
        role = row[0]
    return replace(p, scopes=p.scopes & ROLE_SCOPES[role]), role


def list_members(conn: Connection) -> list[dict[str, Any]]:
    rows = (
        conn.execute(text("SELECT subject, role, added_by, created_at, updated_at FROM members ORDER BY created_at"))
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def _role_of(conn: Connection, subject: str) -> str | None:
    row = conn.execute(text("SELECT role FROM members WHERE subject = :s"), {"s": subject}).one_or_none()
    return row[0] if row else None


def _check(actor_role: str, current: str | None, wanted: str | None) -> None:
    if actor_role != "owner" and ("owner" in (current, wanted)):
        raise PermissionError("only an owner can add, change or remove owners")


def set_role(conn: Connection, actor: Principal, actor_role: str, subject: str, role: str) -> dict[str, Any]:
    if role not in ROLES:
        raise ValueError("unknown role")
    current = _role_of(conn, subject)
    _check(actor_role, current, role)
    if current == role:
        return {"subject": subject, "role": role}
    conn.execute(
        text(
            "INSERT INTO members (tenant_id, subject, role, added_by) VALUES (:t, :s, :r, :a) "
            "ON CONFLICT (tenant_id, subject) DO UPDATE SET role = EXCLUDED.role, updated_at = now()"
        ),
        {"t": actor.tenant_id, "s": subject, "r": role, "a": actor.subject},
    )
    audit(
        conn,
        actor.tenant_id,
        actor.subject,
        "member.added" if current is None else "member.role_changed",
        subject,
        {"from": current, "to": role},
    )
    return {"subject": subject, "role": role}


def remove(conn: Connection, actor: Principal, actor_role: str, subject: str) -> None:
    current = _role_of(conn, subject)
    if current is None:
        raise LookupError(subject)
    _check(actor_role, current, None)
    conn.execute(text("DELETE FROM members WHERE subject = :s"), {"s": subject})
    audit(conn, actor.tenant_id, actor.subject, "member.removed", subject, {"role": current})
