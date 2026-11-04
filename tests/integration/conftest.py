# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Integration tests need the compose stack: `docker compose up -d --wait`."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from aegisruntime.persistence.admin import create_agent, create_project, provision_tenant
from aegisruntime.persistence.db import make_engine, tenant_tx

OWNER_URL = os.environ.get(
    "AEGIS_OWNER_DATABASE_URL", "postgresql+psycopg://aegis_owner:dev-owner-password@127.0.0.1:55432/aegistrace_test"
)
APP_URL = os.environ.get(
    "AEGIS_DATABASE_URL", "postgresql+psycopg://aegis_app:dev-app-password@127.0.0.1:55432/aegistrace_test"
)
DISPATCHER_URL = os.environ.get(
    "AEGIS_DISPATCHER_DATABASE_URL",
    "postgresql+psycopg://aegis_dispatcher:dev-dispatcher-password@127.0.0.1:55432/aegistrace_test",
)


@pytest.fixture(scope="session")
def owner_engine() -> Engine:
    eng = make_engine(OWNER_URL)
    try:
        with eng.connect() as c:
            c.execute(text("SELECT 1 FROM runs LIMIT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"database unavailable or not migrated ({exc}); run docker compose up and alembic upgrade")
    return eng


@pytest.fixture(scope="session")
def app_engine(owner_engine) -> Engine:
    return make_engine(APP_URL)


@pytest.fixture(scope="session")
def dispatcher_engine(owner_engine) -> Engine:
    return make_engine(DISPATCHER_URL)


@dataclass
class TenantCtx:
    tenant_id: str
    project_id: str
    agent_id: str


def make_tenant(owner_engine: Engine, app_engine: Engine) -> TenantCtx:
    tid = "tnt_t" + secrets.token_hex(6)
    provision_tenant(owner_engine, tid, tid)
    with tenant_tx(app_engine, tid) as conn:
        pid = create_project(conn, tid, "default")
        aid = create_agent(conn, tid, pid, "research-agent")
    return TenantCtx(tid, pid, aid)


@pytest.fixture
def tenant(owner_engine, app_engine) -> TenantCtx:
    return make_tenant(owner_engine, app_engine)


@pytest.fixture
def other_tenant(owner_engine, app_engine) -> TenantCtx:
    return make_tenant(owner_engine, app_engine)
