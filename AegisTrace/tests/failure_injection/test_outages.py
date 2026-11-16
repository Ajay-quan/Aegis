# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Failure injection: dependency outages must not lose work, duplicate
logical transitions, or silently bypass controls."""

from __future__ import annotations

import redis
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from aegistrace.api.app import Deps, create_app
from aegistrace.identity.devissuer import AUDIENCE, ISSUER
from aegistrace.identity.jwt import JwksCache, TokenValidator
from aegistrace.persistence.db import tenant_tx
from aegistrace.workers.dispatcher import dispatch_once
from tests.contract.conftest import auth, issuer, signer  # noqa: F401
from tests.end_to_end.conftest import harness  # noqa: F401
from tests.integration.conftest import OWNER_URL, app_engine, dispatcher_engine, other_tenant, owner_engine, tenant  # noqa: F401

SCRIPT = [{"tool": "calc.add", "args": {"a": 1, "b": 2}}, {"final": "3"}]


def _outbox(h, t, run_id):
    with tenant_tx(h.app_engine, t.tenant_id) as c:
        return c.execute(text("SELECT status, attempts, last_error FROM outbox WHERE run_id=:r"), {"r": run_id}).one()


def test_redis_outage_keeps_outbox_pending_then_recovers(harness, tenant):
    h, t = harness, tenant
    h.grant(t, "calc.add", 0)
    run_id = h.submit(t, SCRIPT)
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)
    assert dispatch_once(h.dispatcher_engine, dead) == 0
    status, attempts, err = _outbox(h, t, run_id)
    assert (status, attempts) == ("pending", 1) and err == "ConnectionError"
    assert h.state(t, run_id) == "QUEUED"  # nothing fabricated
    with create_engine(OWNER_URL).begin() as c:  # fast-forward the publish backoff
        c.execute(text("UPDATE outbox SET available_at = now() WHERE run_id=:r"), {"r": run_id})
    h.pump()
    assert h.state(t, run_id) == "SUCCEEDED"


def test_crash_after_publish_before_commit_is_harmless(harness, tenant):
    """Simulate the dispatcher dying after XADD but before marking the row:
    the message is published twice. The run must transition exactly once."""
    h, t = harness, tenant
    h.grant(t, "calc.add", 0)
    run_id = h.submit(t, SCRIPT)
    h.redis.xadd(
        "aegis:runs",
        {"outbox_id": "0", "tenant_id": t.tenant_id, "run_id": run_id, "topic": "run.execute", "payload": "{}"},
    )
    h.pump()
    with tenant_tx(h.app_engine, t.tenant_id) as c:
        to_running = c.execute(
            text(
                "SELECT count(*) FROM events WHERE run_id=:r AND event_type='run.state_changed' "
                "AND record->'payload'->>'to' = 'RUNNING'"
            ),
            {"r": run_id},
        ).scalar_one()
        execs = c.execute(
            text("SELECT count(*) FROM events WHERE run_id=:r AND event_type='tool.execution_started'"), {"r": run_id}
        ).scalar_one()
    assert h.state(t, run_id) == "SUCCEEDED" and to_running == 1 and execs == 1


def test_malformed_message_goes_to_dead_letter(harness):
    h = harness
    h.redis.xadd("aegis:runs", {"topic": "run.execute", "tenant_id": "'; DROP TABLE runs; --", "run_id": "x"})
    h.pump(rounds=1)
    dead = h.redis.xrange("aegis:runs:dead")
    assert len(dead) == 1 and dead[0][1]["error"] == "malformed"


def test_database_outage_returns_503_without_detail(harness, issuer, signer, tenant):  # noqa: F811
    broken = create_engine("postgresql+psycopg://aegis_app:x@127.0.0.1:1/none", pool_pre_ping=False)
    app = create_app(Deps(broken, TokenValidator(ISSUER, AUDIENCE, JwksCache(issuer.jwks)), signer, harness.redis))
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/v1/runs", headers=auth(issuer, tenant.tenant_id))
    assert r.status_code == 503 and "127.0.0.1" not in r.text and "psycopg" not in r.text
    assert c.get("/readyz").status_code == 503


def test_redis_outage_fails_closed_for_authentication(issuer, signer, app_engine, tenant):  # noqa: F811
    """Revocation status lives in Redis; if it cannot be checked, requests are refused."""
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)
    app = create_app(Deps(app_engine, TokenValidator(ISSUER, AUDIENCE, JwksCache(issuer.jwks)), signer, dead))
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/v1/runs", headers=auth(issuer, tenant.tenant_id))
    assert r.status_code == 503 and "127.0.0.1" not in r.text
    assert c.get("/v1/runs").status_code == 401
