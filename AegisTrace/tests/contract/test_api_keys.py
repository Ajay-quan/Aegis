# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Settings → API keys: shown once, stored only as a peppered hash, scoped, revocable, audited,
tenant-isolated, and never able to escalate privileges."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from aegistrace.api.app import Deps, create_app
from aegistrace.identity.devissuer import AUDIENCE, ISSUER
from aegistrace.identity.jwt import JwksCache, TokenValidator
from tests.contract.conftest import auth

PEPPER = b"test-pepper-not-secret"


@pytest.fixture
def kc(app_engine, issuer, signer, harness) -> TestClient:
    validator = TokenValidator(ISSUER, AUDIENCE, JwksCache(issuer.jwks))
    deps = Deps(app_engine, validator, signer, harness.redis, gateway=harness.worker.gateway, api_key_pepper=PEPPER)
    return TestClient(create_app(deps), raise_server_exceptions=False)


def _new_key(kc, issuer, tenant, scopes, **kw):
    r = kc.post("/v1/api-keys", headers=auth(issuer, tenant.tenant_id), json={"name": "ci", "scopes": scopes, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def test_key_is_shown_once_and_stored_only_as_a_hash(kc, issuer, tenant, owner_engine):
    created = _new_key(kc, issuer, tenant, ["runs:read"])
    raw = created["key"]
    assert raw.startswith("aet_") and created["prefix"] == raw[:12]
    listed = kc.get("/v1/api-keys", headers=auth(issuer, tenant.tenant_id)).json()["items"]
    row = next(k for k in listed if k["id"] == created["id"])
    assert "key" not in row and "key_hash" not in row
    with owner_engine.begin() as c:
        dump = c.execute(text("SELECT row_to_json(k)::text FROM api_keys k WHERE id=:i"), {"i": created["id"]}).scalar()
    assert raw not in dump and raw[12:] not in dump  # neither the key nor its secret part is stored


def test_key_authenticates_with_exactly_its_scopes(kc, issuer, tenant):
    raw = _new_key(kc, issuer, tenant, ["runs:read"])["key"]
    assert kc.get("/v1/runs", headers=bearer(raw)).status_code == 200
    r = kc.post(
        "/v1/runs",
        headers={**bearer(raw), "Idempotency-Key": "k_key_scope_00001"},
        json={"agent_id": tenant.agent_id, "input": {"task": "x"}},
    )
    assert r.status_code == 403  # runs:write was not granted


def test_revoked_key_is_refused_on_the_next_request_and_both_actions_are_audited(kc, issuer, tenant):
    created = _new_key(kc, issuer, tenant, ["runs:read"])
    assert kc.get("/v1/runs", headers=bearer(created["key"])).status_code == 200
    h = auth(issuer, tenant.tenant_id)
    assert kc.delete(f"/v1/api-keys/{created['id']}", headers=h).status_code == 200
    assert kc.get("/v1/runs", headers=bearer(created["key"])).status_code == 401
    assert kc.delete(f"/v1/api-keys/{created['id']}", headers=h).status_code == 200  # idempotent
    events = kc.get("/v1/audit-events", headers=h).json()["items"]
    actions = [(e["action"], e["target"]) for e in events if e["target"] == created["id"]]
    assert actions == [("api_key.revoked", created["id"]), ("api_key.created", created["id"])]  # revoked once


def test_no_privilege_escalation(kc, issuer, tenant):
    limited = auth(issuer, tenant.tenant_id, ["keys:manage", "runs:read"])
    r = kc.post("/v1/api-keys", headers=limited, json={"name": "x", "scopes": ["runs:read", "data:erase"]})
    assert r.status_code == 403 and "data:erase" in r.text
    r = kc.post("/v1/api-keys", headers=auth(issuer, tenant.tenant_id), json={"name": "x", "scopes": ["keys:manage"]})
    assert r.status_code == 422  # keys never manage keys
    raw = _new_key(kc, issuer, tenant, ["runs:read", "audit:read"])["key"]
    assert kc.get("/v1/api-keys", headers=bearer(raw)).status_code == 403
    no_manage = auth(issuer, tenant.tenant_id, ["runs:read"])
    assert kc.post("/v1/api-keys", headers=no_manage, json={"name": "x", "scopes": ["runs:read"]}).status_code == 403


def test_keys_are_isolated_between_organizations(kc, issuer, tenant, other_tenant):
    mine = _new_key(kc, issuer, tenant, ["runs:read"])
    theirs = auth(issuer, other_tenant.tenant_id)
    assert all(k["id"] != mine["id"] for k in kc.get("/v1/api-keys", headers=theirs).json()["items"])
    assert kc.delete(f"/v1/api-keys/{mine['id']}", headers=theirs).status_code == 404
    key = _new_key(kc, issuer, tenant, ["agents:read"])["key"]
    ids = {a["id"] for a in kc.get("/v1/agents", headers=bearer(key)).json()["items"]}
    assert tenant.agent_id in ids  # the key sees its own organization ...
    assert other_tenant.agent_id not in ids  # ... and nothing of another


def test_expired_tampered_and_unknown_keys_are_refused(kc, issuer, tenant, owner_engine):
    created = _new_key(kc, issuer, tenant, ["runs:read"], expires_in_days=30)
    raw = created["key"]
    for bad in (raw[:-1] + ("A" if raw[-1] != "A" else "B"), "aet_00000000_" + "x" * 43, "aet_"):
        assert kc.get("/v1/runs", headers=bearer(bad)).status_code == 401
    with owner_engine.begin() as c:
        c.execute(
            text("UPDATE api_keys SET expires_at = now() - interval '1 minute' WHERE id=:i"), {"i": created["id"]}
        )
    assert kc.get("/v1/runs", headers=bearer(raw)).status_code == 401


def test_keys_off_when_no_pepper_is_configured(client, issuer, tenant):
    assert client.get("/v1/runs", headers=bearer("aet_abcdefgh_" + "x" * 43)).status_code == 401
    assert client.get("/v1/api-keys", headers=auth(issuer, tenant.tenant_id)).status_code == 404


def test_database_refuses_deleting_or_unrevoking_keys(kc, issuer, tenant, owner_engine):
    created = _new_key(kc, issuer, tenant, ["runs:read"])
    kc.delete(f"/v1/api-keys/{created['id']}", headers=auth(issuer, tenant.tenant_id))
    for sql in (
        "DELETE FROM api_keys WHERE id=:i",
        "UPDATE api_keys SET revoked_at=NULL WHERE id=:i",
        "UPDATE api_keys SET scopes='{admin}' WHERE id=:i",
    ):
        with pytest.raises(DBAPIError), owner_engine.begin() as c:
            c.execute(text(sql), {"i": created["id"]})
