# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Agent Builder: an agent's configuration and its append-only version history.

Every saved change creates a new version (a full snapshot), recorded in the same
transaction as the change and in the audit log. The memory switch is not a second
permission system: turning it on grants the agent `memory.recall` (class 1) and
`memory.remember` (class 2) through the ordinary tool grants, so the gateway and
OPA enforce it like any other permission; turning it off removes those grants.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from aegistrace.persistence.audit import audit

FIELDS = ("name", "model_provider", "model_id", "instructions", "max_steps", "memory_enabled")
MEMORY_GRANTS = (("memory.recall", 1), ("memory.remember", 2))


def get(conn: Connection, agent_id: str) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text(
                "SELECT id, project_id, name, model_provider, model_id, instructions, max_steps, memory_enabled, "
                "version, created_at, updated_at FROM agents WHERE id = :a"
            ),
            {"a": agent_id},
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def snapshot(agent: dict[str, Any]) -> dict[str, Any]:
    return {k: agent[k] for k in FIELDS}


def record_version(conn: Connection, tenant_id: str, agent: dict[str, Any], by: str, note: str | None) -> None:
    conn.execute(
        text(
            "INSERT INTO agent_versions (tenant_id, agent_id, version, config, changed_by, note) "
            "VALUES (:t, :a, :v, CAST(:c AS jsonb), :b, :n)"
        ),
        {"t": tenant_id, "a": agent["id"], "v": agent["version"], "c": json.dumps(snapshot(agent)), "b": by, "n": note},
    )


def _set_memory_grants(conn: Connection, tenant_id: str, agent_id: str, on: bool, by: str) -> None:
    for tool, cls in MEMORY_GRANTS:
        conn.execute(text("DELETE FROM tool_grants WHERE agent_id = :a AND tool = :t"), {"a": agent_id, "t": tool})
        if on:
            conn.execute(
                text(
                    "INSERT INTO tool_grants (tenant_id, agent_id, tool, max_risk_class, allowed_hosts, granted_by) "
                    "VALUES (:tn, :a, :t, :m, '{}', :u)"
                ),
                {"tn": tenant_id, "a": agent_id, "t": tool, "m": cls, "u": by},
            )


def update(
    conn: Connection, tenant_id: str, agent_id: str, changes: dict[str, Any], by: str, note: str | None
) -> dict[str, Any]:
    current = get(conn, agent_id)
    if current is None:
        raise LookupError(agent_id)
    changed = {k: v for k, v in changes.items() if k in FIELDS and v is not None and v != current[k]}
    if not changed:
        return current
    if changed.get("model_provider", current["model_provider"]) == "registry":
        mid = changed.get("model_id", current["model_id"])
        if conn.execute(text("SELECT 1 FROM model_registrations WHERE id = :i"), {"i": mid}).first() is None:
            raise ValueError("unknown Model Hub registration")
    sets = ", ".join(f"{k} = :{k}" for k in changed)
    conn.execute(
        text(f"UPDATE agents SET {sets}, version = version + 1, updated_at = now() WHERE id = :a"),  # noqa: S608
        {**changed, "a": agent_id},
    )
    if "memory_enabled" in changed:
        _set_memory_grants(conn, tenant_id, agent_id, bool(changed["memory_enabled"]), by)
    updated = get(conn, agent_id)
    assert updated is not None
    record_version(conn, tenant_id, updated, by, note)
    audit(
        conn,
        tenant_id,
        by,
        "agent.updated",
        agent_id,
        {"version": updated["version"], "changed": sorted(changed), "note": note},
    )
    return updated


def versions(conn: Connection, agent_id: str) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            text(
                "SELECT version, config, changed_by, note, created_at FROM agent_versions WHERE agent_id = :a "
                "ORDER BY version DESC LIMIT 100"
            ),
            {"a": agent_id},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]
