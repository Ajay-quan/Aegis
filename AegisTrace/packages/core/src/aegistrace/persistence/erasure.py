# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Privacy erasure by crypto-shredding, and legal hold.

Erasing destroys the runs' data keys. Their content (inputs, model responses,
tool outputs, approval arguments, results) becomes permanently unreadable;
events, digests, hashes, checkpoints and signatures are untouched, so every
receipt still verifies with payloads reported as withheld. Each erasure is
recorded (who, when, why, which runs) without any content.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from aegistrace.orchestration.service import Actor, new_id

FINISHED = ("SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT")


class ErasureRefused(Exception):
    def __init__(self, reason: str, run_ids: list[str]) -> None:
        super().__init__(f"{reason}: {', '.join(run_ids)}")
        self.reason, self.run_ids = reason, run_ids


def _record(
    conn: Connection, tenant_id: str, scope: str, run_ids: list[str], actor: Actor, reason: str
) -> dict[str, Any]:
    eid = new_id("era")
    row = conn.execute(
        text(
            "INSERT INTO erasures (id, tenant_id, scope, run_ids, actor_id, reason) "
            "VALUES (:i, :t, :s, :r, :a, :why) RETURNING created_at"
        ),
        {"i": eid, "t": tenant_id, "s": scope, "r": run_ids, "a": actor.id, "why": reason},
    ).scalar_one()
    return {"erasure_id": eid, "scope": scope, "run_ids": run_ids, "erased_at": row.isoformat(), "reason": reason}


def erase_run(conn: Connection, tenant_id: str, run_id: str, actor: Actor, reason: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            "SELECT r.state, k.wrapped IS NOT NULL, k.shredded_at IS NOT NULL, k.legal_hold FROM runs r "
            "LEFT JOIN payload_keys k ON k.run_id = r.id WHERE r.id = :r FOR UPDATE OF r"
        ),
        {"r": run_id},
    ).one_or_none()
    if row is None:
        raise LookupError(run_id)
    state, has_key, shredded, hold = row
    if state not in FINISHED:
        raise ErasureRefused("run_not_finished", [run_id])
    if shredded:
        raise ErasureRefused("already_erased", [run_id])
    if not has_key:
        raise ErasureRefused("stored_without_encryption", [run_id])
    if hold:
        raise ErasureRefused("legal_hold", [run_id])
    conn.execute(text("UPDATE payload_keys SET wrapped = NULL, shredded_at = now() WHERE run_id = :r"), {"r": run_id})
    return _record(conn, tenant_id, "run", [run_id], actor, reason)


def erase_tenant(
    conn: Connection, tenant_id: str, actor: Actor, reason: str, before: datetime | None = None
) -> dict[str, Any]:
    """Erase every finished run of this tenant (optionally only those finished before `before`), except held ones."""
    ids = list(
        conn.execute(
            text(
                "UPDATE payload_keys k SET wrapped = NULL, shredded_at = now() FROM runs r "
                "WHERE k.run_id = r.id AND k.wrapped IS NOT NULL AND NOT k.legal_hold AND r.state = ANY(:fin) "
                "AND (CAST(:b AS timestamptz) IS NULL OR r.updated_at < CAST(:b AS timestamptz)) RETURNING k.run_id"
            ),
            {"fin": list(FINISHED), "b": before},
        ).scalars()
    )
    held = list(
        conn.execute(text("SELECT run_id FROM payload_keys WHERE legal_hold AND wrapped IS NOT NULL")).scalars()
    )
    out = _record(conn, tenant_id, "tenant", sorted(ids), actor, reason) if ids else {"erasure_id": None, "run_ids": []}
    return {**out, "kept_under_legal_hold": sorted(held)}


def set_legal_hold(conn: Connection, run_id: str, hold: bool) -> None:
    row = conn.execute(
        text("UPDATE payload_keys SET legal_hold = :h WHERE run_id = :r AND wrapped IS NOT NULL RETURNING run_id"),
        {"h": hold, "r": run_id},
    ).one_or_none()
    if row is None:
        exists = conn.execute(text("SELECT 1 FROM runs WHERE id = :r"), {"r": run_id}).one_or_none()
        if exists is None:
            raise LookupError(run_id)
        raise ErasureRefused("no_encrypted_content", [run_id])


def apply_retention(conn: Connection) -> int:
    """Shred runs past each tenant's `payload_retention_days` (cross-tenant; see migration 0006)."""
    return int(conn.execute(text("SELECT apply_payload_retention()")).scalar_one())
