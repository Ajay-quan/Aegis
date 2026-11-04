# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Workflow kernel against real PostgreSQL: atomic transitions, chained
events, idempotency, RLS isolation, leases, fencing, recovery."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from aegisruntime.orchestration import leases
from aegisruntime.orchestration.service import (
    Actor,
    Conflict,
    OperatorRequired,
    StaleLease,
    checkpoint,
    create_run,
    load_events,
    record_event,
    transition,
)
from aegisruntime.orchestration.states import IllegalTransition, RunState
from aegisruntime.persistence.db import tenant_tx
from aegistrace.evidence.bundle import write_bundle_records
from aegistrace.evidence.signing import LocalEd25519Signer
from aegistrace.evidence.trust import TrustStore
from aegistrace.evidence.verifier import Status, verify_bundle
from tests.conftest import trust_doc

USER = Actor("usr_alice", "user")
TTL = timedelta(seconds=30)


def _run(app_engine, t, key="k1", inp=None):
    with tenant_tx(app_engine, t.tenant_id) as c:
        return create_run(c, t.tenant_id, t.agent_id, inp or {"task": "summarize"}, USER, key)


def _state(app_engine, t, run_id):
    with tenant_tx(app_engine, t.tenant_id) as c:
        return c.execute(text("SELECT state FROM runs WHERE id=:r"), {"r": run_id}).scalar_one()


def test_create_run_appends_chain_and_outbox(app_engine, tenant):
    run_id, created = _run(app_engine, tenant)
    assert created
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        evs = load_events(c, run_id)
        outbox = c.execute(text("SELECT topic FROM outbox WHERE run_id=:r"), {"r": run_id}).scalars().all()
    assert [e["event_type"] for e in evs] == ["run.created", "run.state_changed", "run.state_changed"]
    assert [e["sequence_number"] for e in evs] == [1, 2, 3]
    assert outbox == ["run.execute"]
    assert _state(app_engine, tenant, run_id) == "QUEUED"


def test_idempotent_create(app_engine, tenant):
    a, _ = _run(app_engine, tenant, "same")
    b, created = _run(app_engine, tenant, "same")
    assert a == b and not created
    with pytest.raises(Conflict):
        _run(app_engine, tenant, "same", {"task": "different"})


def test_concurrent_identical_creates_yield_one_run(app_engine, tenant):
    results, errors = [], []

    def go():
        try:
            results.append(_run(app_engine, tenant, "race")[0])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors and len(set(results)) == 1
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        assert c.execute(text("SELECT count(*) FROM runs")).scalar_one() == 1


def test_illegal_transition_rejected_and_nothing_written(app_engine, tenant):
    run_id, _ = _run(app_engine, tenant)
    with pytest.raises(IllegalTransition), tenant_tx(app_engine, tenant.tenant_id) as c:
        transition(c, run_id, RunState.SUCCEEDED, USER)
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        assert len(load_events(c, run_id)) == 3


def test_events_are_append_only_even_for_owner(owner_engine, app_engine, tenant):
    run_id, _ = _run(app_engine, tenant)
    with pytest.raises(DBAPIError, match="append-only"), owner_engine.begin() as c:
        c.execute(text("UPDATE events SET event_type='forged' WHERE run_id=:r"), {"r": run_id})
    with pytest.raises(DBAPIError), tenant_tx(app_engine, tenant.tenant_id) as c:
        c.execute(text("DELETE FROM events WHERE run_id=:r"), {"r": run_id})


def test_duplicate_sequence_rejected(owner_engine, app_engine, tenant):
    run_id, _ = _run(app_engine, tenant)
    with pytest.raises(IntegrityError), owner_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO events (event_id, tenant_id, run_id, sequence_number, event_type, current_event_hash, record) "
                "VALUES ('evt_dup', :t, :r, 1, 'x', 'h', '{}')"
            ),
            {"t": tenant.tenant_id, "r": run_id},
        )


# -- tenant isolation (INV-003) ----------------------------------------------


def test_rls_hides_other_tenant(app_engine, tenant, other_tenant):
    run_id, _ = _run(app_engine, tenant)
    with tenant_tx(app_engine, other_tenant.tenant_id) as c:
        for table in ("runs", "events", "outbox", "agents", "projects", "idempotency_keys"):
            n = c.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id=:t"),  # noqa: S608
                {"t": tenant.tenant_id},
            ).scalar_one()
            assert n == 0, table
        assert c.execute(text("SELECT count(*) FROM tenants")).scalar_one() == 1


def test_rls_blocks_cross_tenant_writes(app_engine, tenant, other_tenant):
    with pytest.raises(DBAPIError, match="row-level security"), tenant_tx(app_engine, other_tenant.tenant_id) as c:
        c.execute(
            text("INSERT INTO projects (id, tenant_id, name) VALUES ('prj_x', :t, 'evil')"), {"t": tenant.tenant_id}
        )


def test_cannot_run_other_tenants_agent(app_engine, tenant, other_tenant):
    from aegisruntime.orchestration.service import NotFound

    with pytest.raises(NotFound), tenant_tx(app_engine, other_tenant.tenant_id) as c:
        create_run(c, other_tenant.tenant_id, tenant.agent_id, {}, USER, "x")


def test_unbound_connection_sees_nothing(app_engine, tenant):
    _run(app_engine, tenant)
    with app_engine.begin() as c:
        assert c.execute(text("SELECT count(*) FROM runs")).scalar_one() == 0


def test_app_role_cannot_bypass_rls(app_engine):
    with app_engine.begin() as c:
        bypass = c.execute(text("SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user"))
        assert bypass.scalar_one() is False


# -- leases, fencing, recovery (UC-05) ----------------------------------------


def test_claim_is_exclusive_and_duplicate_delivery_is_noop(app_engine, tenant):
    run_id, _ = _run(app_engine, tenant)
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        lease = leases.claim(c, run_id, "wrk_a", TTL)
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        assert leases.claim(c, run_id, "wrk_b", TTL) is None
    assert lease and lease.fencing_token == 1


def _expire(owner_engine, run_id):
    with owner_engine.begin() as c:
        c.execute(text("UPDATE runs SET lease_expires_at = now() - interval '1 second' WHERE id=:r"), {"r": run_id})


def test_stale_worker_cannot_finalize(owner_engine, app_engine, tenant):
    run_id, _ = _run(app_engine, tenant)
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        old = leases.claim(c, run_id, "wrk_a", TTL)
    _expire(owner_engine, run_id)
    assert leases.recover_expired(app_engine)[run_id] is RunState.RETRY_SCHEDULED
    with pytest.raises(StaleLease), tenant_tx(app_engine, tenant.tenant_id) as c:
        transition(c, run_id, RunState.SUCCEEDED, Actor("wrk_a", "worker"), fencing_token=old.fencing_token)
    with pytest.raises(StaleLease), tenant_tx(app_engine, tenant.tenant_id) as c:
        leases.heartbeat(c, old, TTL)
    with pytest.raises(StaleLease), tenant_tx(app_engine, tenant.tenant_id) as c:
        record_event(
            c, run_id, "tool.execution_succeeded", Actor("wrk_a", "worker"), {}, fencing_token=old.fencing_token
        )
    assert _state(app_engine, tenant, run_id) == "RETRY_SCHEDULED"


def test_retry_then_new_worker_succeeds(owner_engine, app_engine, tenant):
    run_id, _ = _run(app_engine, tenant)
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        leases.claim(c, run_id, "wrk_a", TTL)
    _expire(owner_engine, run_id)
    leases.recover_expired(app_engine)
    with owner_engine.begin() as c:
        c.execute(text("UPDATE runs SET next_attempt_at = now() WHERE id=:r"), {"r": run_id})
    assert run_id in leases.requeue_due_retries(app_engine)
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        new = leases.claim(c, run_id, "wrk_b", TTL)
        assert new.fencing_token == 3 and new.attempt == 2
        transition(
            c,
            run_id,
            RunState.SUCCEEDED,
            Actor("wrk_b", "worker"),
            {"result": {"ok": True}},
            fencing_token=new.fencing_token,
        )
    assert _state(app_engine, tenant, run_id) == "SUCCEEDED"


def test_unknown_side_effect_goes_to_reconciliation_not_retry(owner_engine, app_engine, tenant):
    run_id, _ = _run(app_engine, tenant)
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        lease = leases.claim(c, run_id, "wrk_a", TTL)
        record_event(
            c,
            run_id,
            "tool.execution_started",
            Actor("wrk_a", "worker"),
            {"execution_id": "exe_1", "tool": "payments.send", "retry_safe": False},
            fencing_token=lease.fencing_token,
        )
    _expire(owner_engine, run_id)
    assert leases.recover_expired(app_engine)[run_id] is RunState.NEEDS_RECONCILIATION
    with pytest.raises(OperatorRequired), tenant_tx(app_engine, tenant.tenant_id) as c:
        transition(c, run_id, RunState.SUCCEEDED, Actor("system", "system"))
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        transition(c, run_id, RunState.FAILED, USER, {"reconciliation": "provider confirms no payment"})
    assert _state(app_engine, tenant, run_id) == "FAILED"


def test_retry_budget_exhausted_fails(owner_engine, app_engine, tenant):
    run_id, _ = _run(app_engine, tenant)
    with owner_engine.begin() as c:
        c.execute(text("UPDATE runs SET max_attempts = 1 WHERE id=:r"), {"r": run_id})
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        leases.claim(c, run_id, "wrk_a", TTL)
    _expire(owner_engine, run_id)
    assert leases.recover_expired(app_engine)[run_id] is RunState.FAILED


def test_timeout(owner_engine, app_engine, tenant):
    run_id, _ = _run(app_engine, tenant)
    with owner_engine.begin() as c:
        c.execute(text("UPDATE runs SET deadline_at = now() - interval '1 second' WHERE id=:r"), {"r": run_id})
    assert run_id in leases.expire_overdue(app_engine)
    assert _state(app_engine, tenant, run_id) == "TIMED_OUT"


# -- receipts from real runs ------------------------------------------------------


def test_exported_receipt_verifies_offline(app_engine, tenant):
    signer = LocalEd25519Signer()
    run_id, _ = _run(app_engine, tenant)
    with tenant_tx(app_engine, tenant.tenant_id) as c:
        lease = leases.claim(c, run_id, "wrk_a", TTL)
        transition(
            c,
            run_id,
            RunState.SUCCEEDED,
            Actor("wrk_a", "worker"),
            {"result": {"ok": 1}},
            fencing_token=lease.fencing_token,
        )
        cp = checkpoint(c, run_id, signer)
        assert checkpoint(c, run_id, signer) == cp  # idempotent
        bundle = write_bundle_records(tenant.tenant_id, run_id, load_events(c, run_id), [cp], {})
    report = verify_bundle(bundle, TrustStore.from_json(trust_doc(signer)), tenant.tenant_id, run_id)
    assert report.status is Status.VALID, report.as_dict()
    assert report.event_count == 5


def test_tenant_concurrency_quota(owner_engine, app_engine, tenant, other_tenant):
    from aegisruntime.orchestration.service import QuotaExceeded

    with owner_engine.begin() as c:
        c.execute(text("UPDATE tenants SET max_active_runs = 2 WHERE id = :t"), {"t": tenant.tenant_id})
    _run(app_engine, tenant, "q1")
    _run(app_engine, tenant, "q2")
    with pytest.raises(QuotaExceeded):
        _run(app_engine, tenant, "q3")
    _run(app_engine, other_tenant, "q1")  # quotas are per tenant
