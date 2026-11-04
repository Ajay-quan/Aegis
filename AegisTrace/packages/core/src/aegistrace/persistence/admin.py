# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Platform provisioning. Tenant creation runs as the owner role because the
app role is deliberately unable to create tenants."""

from __future__ import annotations

from sqlalchemy import Connection, Engine, text

from aegistrace.orchestration.service import new_id


def provision_tenant(owner_engine: Engine, tenant_id: str, name: str) -> None:
    with owner_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name) VALUES (:i, :n) ON CONFLICT (id) DO NOTHING"),
            {"i": tenant_id, "n": name},
        )


def create_project(conn: Connection, tenant_id: str, name: str) -> str:
    pid = new_id("prj")
    conn.execute(
        text("INSERT INTO projects (id, tenant_id, name) VALUES (:i, :t, :n)"), {"i": pid, "t": tenant_id, "n": name}
    )
    return pid


def create_agent(
    conn: Connection,
    tenant_id: str,
    project_id: str,
    name: str,
    model_provider: str = "mock",
    model_id: str = "mock-deterministic-1",
) -> str:
    aid = new_id("agt")
    conn.execute(
        text(
            "INSERT INTO agents (id, tenant_id, project_id, name, model_provider, model_id) "
            "VALUES (:i, :t, :p, :n, :mp, :mi)"
        ),
        {"i": aid, "t": tenant_id, "p": project_id, "n": name, "mp": model_provider, "mi": model_id},
    )
    return aid
