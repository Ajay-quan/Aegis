# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""API keys for the AegisTrace API (SDKs, CLI, CI jobs, agents).

Same design as AegisMem's keys: `aet_<id8>_<secret>`, only a peppered
HMAC-SHA256 of the full key is stored, the plaintext is returned once at
creation, keys are scoped, expiring and revocable, and every create and revoke
is written to the audit log.

Rules:
- A key's scopes must be a subset of its creator's scopes (no escalation).
- A key can never manage keys (`keys:manage`): key administration stays with
  signed-in people.
- A revoked or expired key is refused on the next request (no cache).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from aegistrace.persistence.audit import audit

from .jwt import Principal

PREFIX = "aet_"
MANAGE_SCOPE = "keys:manage"
NOT_GRANTABLE = frozenset({MANAGE_SCOPE})


class KeyRejected(Exception):
    pass


def pepper_from_env(env: dict[str, str] | None = None) -> bytes | None:
    """AEGIS_API_KEY_PEPPER_FILE (preferred) or AEGIS_API_KEY_PEPPER. None disables API keys."""
    e = os.environ if env is None else env
    if e.get("AEGIS_API_KEY_PEPPER_FILE"):
        return Path(e["AEGIS_API_KEY_PEPPER_FILE"]).read_bytes().strip()
    raw = e.get("AEGIS_API_KEY_PEPPER")
    return raw.encode() if raw else None


def hash_key(pepper: bytes, raw: str) -> str:
    return hmac.new(pepper, raw.encode(), hashlib.sha256).hexdigest()


def looks_like_key(token: str) -> bool:
    return token.startswith(PREFIX)


def authenticate(engine: Engine, pepper: bytes, raw: str) -> Principal:
    if not looks_like_key(raw) or len(raw) > 200:
        raise KeyRejected("malformed key")
    with engine.begin() as c:
        row = c.execute(
            text("SELECT id, tenant_id, scopes, usable FROM api_key_lookup(:h)"), {"h": hash_key(pepper, raw)}
        ).one_or_none()
    if row is None or not row[3]:
        raise KeyRejected("unknown, revoked or expired key")
    return Principal(subject=f"key:{row[0]}", tenant_id=row[1], scopes=frozenset(row[2]), kind="service", token_id=None)


def create(
    conn: Connection, pepper: bytes, creator: Principal, name: str, scopes: list[str], expires_in_days: int | None
) -> dict[str, Any]:
    wanted = frozenset(scopes)
    if not wanted:
        raise ValueError("choose at least one scope")
    if wanted & NOT_GRANTABLE:
        raise ValueError("keys cannot be given keys:manage")
    if not wanted <= creator.scopes:
        raise PermissionError("a key cannot have scopes you do not have: " + ", ".join(sorted(wanted - creator.scopes)))
    key_id = "key_" + secrets.token_hex(12)
    raw = f"{PREFIX}{key_id[4:12]}_{secrets.token_urlsafe(32)}"
    expires = datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None
    created_at = conn.execute(
        text(
            "INSERT INTO api_keys (id, tenant_id, name, prefix, key_hash, scopes, created_by, expires_at) "
            "VALUES (:i, :t, :n, :p, :h, :s, :c, :e) RETURNING created_at"
        ),
        {
            "i": key_id,
            "t": creator.tenant_id,
            "n": name,
            "p": raw[:12],
            "h": hash_key(pepper, raw),
            "s": sorted(wanted),
            "c": creator.subject,
            "e": expires,
        },
    ).scalar_one()
    audit(
        conn,
        creator.tenant_id,
        creator.subject,
        "api_key.created",
        key_id,
        {"name": name, "scopes": sorted(wanted), "expires_at": expires.isoformat() if expires else None},
    )
    return {
        "id": key_id,
        "key": raw,
        "name": name,
        "prefix": raw[:12],
        "scopes": sorted(wanted),
        "created_at": created_at.isoformat(),
        "expires_at": expires.isoformat() if expires else None,
    }


def list_keys(conn: Connection) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            text(
                "SELECT id, name, prefix, scopes, created_by, created_at, expires_at, last_used_at, revoked_at "
                "FROM api_keys ORDER BY created_at DESC LIMIT 500"
            )
        )
        .mappings()
        .all()
    )
    return [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()} for r in rows]


def revoke(conn: Connection, actor: Principal, key_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            "UPDATE api_keys SET revoked_at = now(), revoked_by = :a WHERE id = :i AND revoked_at IS NULL "
            "RETURNING revoked_at"
        ),
        {"a": actor.subject, "i": key_id},
    ).one_or_none()
    if row is None:
        exists = conn.execute(text("SELECT revoked_at FROM api_keys WHERE id = :i"), {"i": key_id}).one_or_none()
        if exists is None:
            raise LookupError(key_id)
        return {"id": key_id, "revoked_at": exists[0].isoformat()}  # already revoked: idempotent
    audit(conn, actor.tenant_id, actor.subject, "api_key.revoked", key_id, {})
    return {"id": key_id, "revoked_at": row[0].isoformat()}
