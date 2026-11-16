# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Payload encryption at rest, crypto-shredding erasure, legal hold and retention.

The suite runs with encryption on (tests/conftest.py). These tests check the
privacy guarantees directly: content is ciphertext in the database, erasure
makes it unrecoverable while the evidence still verifies, and holds and
retention behave as specified."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from aegistrace.evidence.bundle import write_bundle_records
from aegistrace.evidence.signing import LocalEd25519Signer
from aegistrace.evidence.trust import TrustStore
from aegistrace.evidence.verifier import Status, verify_bundle
from aegistrace.orchestration.service import checkpoint, load_events
from aegistrace.persistence.db import tenant_tx
from tests.conftest import trust_doc
from tests.contract.conftest import auth

SECRET = "acme-merger-codename-bluebird"


_granted: set[tuple[int, str]] = set()


def _run(h, t):
    if (id(h), t.agent_id) not in _granted:
        h.grant(t, "calc.add", 0)
        _granted.add((id(h), t.agent_id))
    run_id = h.submit(t, [{"tool": "calc.add", "args": {"a": 2, "b": 3}}, {"final": f"done {SECRET}"}], task=SECRET)
    h.pump()
    assert h.state(t, run_id) == "SUCCEEDED"
    return run_id


def _raw(owner_engine, run_id):
    with owner_engine.begin() as c:
        ev = c.execute(text("SELECT string_agg(record::text, '') FROM events WHERE run_id=:r"), {"r": run_id}).scalar()
        run = c.execute(
            text("SELECT input::text || coalesce(result::text,'') FROM runs WHERE id=:r"), {"r": run_id}
        ).scalar()
    return ev + run


def _verify(h, t, run_id):
    signer = LocalEd25519Signer()
    with tenant_tx(h.app_engine, t.tenant_id) as c:
        cp = checkpoint(c, run_id, signer)
        bundle = write_bundle_records(t.tenant_id, run_id, load_events(c, run_id), [cp], {})
    return verify_bundle(bundle, TrustStore.from_json(trust_doc(signer)), t.tenant_id, run_id)


def test_content_is_ciphertext_at_rest_but_readable_through_the_api(client, issuer, harness, tenant, owner_engine):
    run_id = _run(harness, tenant)
    assert SECRET not in _raw(owner_engine, run_id)  # neither input, model output nor result in clear
    h = auth(issuer, tenant.tenant_id)
    assert client.get(f"/v1/runs/{run_id}", headers=h).json()["result"] == {"text": f"done {SECRET}"}
    events = client.get(f"/v1/runs/{run_id}/events", headers=h).json()["items"]
    assert any(SECRET in str(e.get("payload")) for e in events)
    assert _verify(harness, tenant, run_id).status is Status.VALID


def test_erasing_a_run_destroys_content_but_evidence_still_verifies(client, issuer, harness, tenant, owner_engine):
    run_id = _run(harness, tenant)
    h = auth(issuer, tenant.tenant_id)
    r = client.post(f"/v1/runs/{run_id}/erase", headers=h, json={"reason": "GDPR Art.17 request #42"})
    assert r.status_code == 200, r.text
    assert r.json()["run_ids"] == [run_id]

    run = client.get(f"/v1/runs/{run_id}", headers=h).json()
    assert run["result"] is None and run["erased"] is True
    events = client.get(f"/v1/runs/{run_id}/events", headers=h).json()["items"]
    sealed_types = {"run.created", "model.invoked", "tool.execution_succeeded"}
    assert all("payload" not in e for e in events if e["event_type"] in sealed_types)
    assert all("payload" in e for e in events if e["event_type"] == "tool.authorization")  # control data stays

    report = _verify(harness, tenant, run_id)
    assert report.status is Status.VALID, report.as_dict()  # hashes, digests and signatures untouched
    assert any("withheld" in w for w in report.warnings)
    with owner_engine.begin() as c:
        assert c.execute(text("SELECT wrapped FROM payload_keys WHERE run_id=:r"), {"r": run_id}).scalar() is None
    assert client.get(f"/v1/runs/{run_id}/data-status", headers=h).json()["erased"] is True
    assert client.post(f"/v1/runs/{run_id}/erase", headers=h, json={"reason": "again"}).status_code == 409
    log = client.get("/v1/erasures", headers=h).json()["items"]
    assert log[0]["run_ids"] == [run_id] and log[0]["reason"] == "GDPR Art.17 request #42"
    assert (
        client.post(
            f"/v1/runs/{run_id}/fork", headers={**h, "Idempotency-Key": "k_fork_erased_0001"}, json={"reason": "x"}
        ).status_code
        == 410
    )


def test_legal_hold_blocks_erasure_even_at_the_database(client, issuer, harness, tenant, owner_engine):
    run_id = _run(harness, tenant)
    h = auth(issuer, tenant.tenant_id)
    assert (
        client.put(f"/v1/runs/{run_id}/legal-hold", headers=h, json={"hold": True, "reason": "litigation"}).status_code
        == 200
    )
    r = client.post(f"/v1/runs/{run_id}/erase", headers=h, json={"reason": "request"})
    assert r.status_code == 409 and "legal hold" in r.text
    with pytest.raises(Exception, match="legal hold"), owner_engine.begin() as c:
        c.execute(text("UPDATE payload_keys SET wrapped=NULL, shredded_at=now() WHERE run_id=:r"), {"r": run_id})
    client.put(f"/v1/runs/{run_id}/legal-hold", headers=h, json={"hold": False})
    assert client.post(f"/v1/runs/{run_id}/erase", headers=h, json={"reason": "hold released"}).status_code == 200


def test_shredded_keys_cannot_be_restored_or_deleted(harness, tenant, client, issuer, owner_engine):
    run_id = _run(harness, tenant)
    client.post(f"/v1/runs/{run_id}/erase", headers=auth(issuer, tenant.tenant_id), json={"reason": "request"})
    for sql in (
        "UPDATE payload_keys SET wrapped='\\x00', shredded_at=NULL WHERE run_id=:r",
        "DELETE FROM payload_keys WHERE run_id=:r",
    ):
        with pytest.raises(DBAPIError), owner_engine.begin() as c:
            c.execute(text(sql), {"r": run_id})


def test_erase_all_for_tenant_keeps_held_runs_and_other_tenants(
    client, issuer, harness, tenant, other_tenant, owner_engine
):
    mine, held = _run(harness, tenant), _run(harness, tenant)
    theirs = _run(harness, other_tenant)
    h = auth(issuer, tenant.tenant_id)
    client.put(f"/v1/runs/{held}/legal-hold", headers=h, json={"hold": True})
    assert (
        client.post("/v1/data/erase", headers=h, json={"reason": "offboarding", "confirm": "wrong"}).status_code == 422
    )
    r = client.post("/v1/data/erase", headers=h, json={"reason": "customer offboarding", "confirm": tenant.tenant_id})
    assert r.status_code == 200, r.text
    assert mine in r.json()["run_ids"] and held not in r.json()["run_ids"]
    assert r.json()["kept_under_legal_hold"] == [held]
    other = client.get(f"/v1/runs/{theirs}", headers=auth(issuer, other_tenant.tenant_id)).json()
    assert other["result"] == {"text": f"done {SECRET}"}  # untouched


def test_retention_shreds_old_runs_per_tenant_setting(harness, tenant, other_tenant, owner_engine, app_engine):
    from aegistrace.persistence.erasure import apply_retention

    old, held, fresh = _run(harness, tenant), _run(harness, tenant), _run(harness, tenant)
    other_old = _run(harness, other_tenant)  # no retention setting: kept
    with owner_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO tenant_rules (tenant_id, settings, updated_by) VALUES (:t, :s, 'test') "
                "ON CONFLICT (tenant_id) DO UPDATE SET settings = EXCLUDED.settings"
            ),
            {"t": tenant.tenant_id, "s": '{"payload_retention_days": 30}'},
        )
        c.execute(
            text("UPDATE runs SET updated_at = now() - interval '31 days' WHERE id = ANY(:r)"),
            {"r": [old, held, other_old]},
        )
        c.execute(text("UPDATE payload_keys SET legal_hold = true WHERE run_id = :r"), {"r": held})
    with app_engine.begin() as c:  # the worker's role, with no tenant set
        assert apply_retention(c) >= 1
    with owner_engine.begin() as c:
        status = dict(
            c.execute(
                text("SELECT run_id, shredded_at IS NOT NULL FROM payload_keys WHERE run_id = ANY(:r)"),
                {"r": [old, held, fresh, other_old]},
            ).all()
        )
        log = c.execute(
            text("SELECT scope, run_ids FROM erasures WHERE tenant_id=:t AND scope='retention'"),
            {"t": tenant.tenant_id},
        ).all()
    assert status == {old: True, held: False, fresh: False, other_old: False}
    assert any(old in ids for _, ids in log)


def test_erasure_needs_the_data_erase_scope(client, issuer, harness, tenant):
    run_id = _run(harness, tenant)
    reader = auth(issuer, tenant.tenant_id, ["runs:read", "audit:read", "payloads:read"])
    assert client.post(f"/v1/runs/{run_id}/erase", headers=reader, json={"reason": "x" * 5}).status_code == 403
    assert client.put(f"/v1/runs/{run_id}/legal-hold", headers=reader, json={"hold": True}).status_code == 403


def test_approval_arguments_are_sealed_and_shown_only_until_erased(client, issuer, harness, tenant, owner_engine):
    h_, t = harness, tenant
    h_.grant(t, "data.export", 3)
    run_id = h_.submit(
        t,
        [
            {
                "tool": "data.export",
                "args": {"dataset": "bluebird", "destination": "s3.partner", "classification": "CONFIDENTIAL"},
            },
            {"final": "x"},
        ],
    )
    h_.pump()
    with owner_engine.begin() as c:
        raw = c.execute(text("SELECT summary::text FROM approvals WHERE run_id=:r"), {"r": run_id}).scalar()
    assert "bluebird" not in raw and "data.export" in raw
    h = auth(issuer, t.tenant_id)
    item = next(a for a in client.get("/v1/approvals", headers=h).json()["items"] if a["run_id"] == run_id)
    assert item["summary"]["arguments"]["dataset"] == "bluebird"
