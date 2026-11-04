# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
from __future__ import annotations

import logging
import time

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aegistrace.api.logging import JsonFormatter
from aegistrace.evidence.trust import TrustStore
from aegistrace.evidence.verifier import Status, verify_bundle
from aegistrace.identity.devissuer import AUDIENCE, ISSUER, DevIssuer
from aegistrace.persistence.db import tenant_tx
from tests.conftest import trust_doc
from tests.contract.conftest import auth

SCRIPT = [{"tool": "calc.add", "args": {"a": 2, "b": 3}}, {"final": "5"}]


def _setup(client, issuer, t):
    h = auth(issuer, t.tenant_id)
    r = client.put(f"/v1/agents/{t.agent_id}/grants", json={"tool": "calc.add", "max_risk_class": 0}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post(
        "/v1/runs",
        json={"agent_id": t.agent_id, "input": {"task": "add", "mock_script": SCRIPT}},
        headers={**h, "Idempotency-Key": "idem-key-0001"},
    )
    assert r.status_code == 201, r.text
    return h, r.json()["id"]


# -- authentication -------------------------------------------------------------


def test_missing_and_garbage_tokens(client):
    assert client.get("/v1/runs").status_code == 401
    assert client.get("/v1/runs", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_wrong_audience_issuer_expired_rejected(client, issuer, tenant):
    for kw in ({"aud": "other-api"}, {"iss": "https://evil.example"}, {"exp": int(time.time()) - 120}):
        r = client.get("/v1/runs", headers=auth(issuer, tenant.tenant_id, **kw))
        assert r.status_code == 401, kw
        assert r.json() == {"error": {"code": "unauthenticated", "message": "invalid token"}}


def test_untrusted_key_and_alg_none_rejected(client, issuer, tenant):
    rogue = DevIssuer(kid=issuer.kid)  # same kid, different key
    assert (
        client.get(
            "/v1/runs", headers={"Authorization": "Bearer " + rogue.mint("u", tenant.tenant_id, ["runs:read"])}
        ).status_code
        == 401
    )
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "u",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "aegis_tenant": tenant.tenant_id,
        "scope": "runs:read",
    }
    none_tok = jwt.encode(claims, key=None, algorithm="none", headers={"kid": issuer.kid})
    assert client.get("/v1/runs", headers={"Authorization": f"Bearer {none_tok}"}).status_code == 401
    hs_tok = jwt.encode(claims, "secret-secret-secret-secret-1234", algorithm="HS256", headers={"kid": issuer.kid})
    assert client.get("/v1/runs", headers={"Authorization": f"Bearer {hs_tok}"}).status_code == 401


def test_missing_tenant_claim_rejected(client, issuer):
    tok = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "u",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
            "scope": "runs:read",
        },
        issuer.key,
        algorithm="EdDSA",
        headers={"kid": issuer.kid},
    )
    assert client.get("/v1/runs", headers={"Authorization": f"Bearer {tok}"}).status_code == 401


def test_scope_enforced(client, issuer, tenant):
    r = client.post(
        "/v1/runs",
        json={"agent_id": tenant.agent_id, "input": {}},
        headers={**auth(issuer, tenant.tenant_id, ["runs:read"]), "Idempotency-Key": "idem-key-0002"},
    )
    assert r.status_code == 403


# -- tenant isolation at the API (INV-003) ------------------------------------------


def test_cross_tenant_access_is_404(client, issuer, tenant, other_tenant):
    _, run_id = _setup(client, issuer, tenant)
    other = auth(issuer, other_tenant.tenant_id)
    for path in (
        f"/v1/runs/{run_id}",
        f"/v1/runs/{run_id}/events",
        f"/v1/runs/{run_id}/receipt",
        f"/v1/runs/{run_id}/replay",
    ):
        assert client.get(path, headers=other).status_code == 404, path
    assert client.post(f"/v1/runs/{run_id}/cancel", headers=other).status_code == 404
    assert client.get("/v1/runs", headers=other).json()["items"] == []
    # Body cannot select a tenant: submitting with tenant A's agent from tenant B fails.
    r = client.post(
        "/v1/runs",
        json={"agent_id": tenant.agent_id, "input": {}},
        headers={**other, "Idempotency-Key": "idem-key-0003"},
    )
    assert r.status_code == 404
    r = client.put(
        f"/v1/agents/{tenant.agent_id}/grants", json={"tool": "email.send", "max_risk_class": 4}, headers=other
    )
    assert r.status_code == 404


def test_extra_body_fields_rejected(client, issuer, tenant):
    r = client.post(
        "/v1/runs",
        json={"agent_id": tenant.agent_id, "input": {}, "tenant_id": "tnt_other"},
        headers={**auth(issuer, tenant.tenant_id), "Idempotency-Key": "idem-key-0004"},
    )
    assert r.status_code == 422
    assert "tnt_other" not in r.text


# -- runs, idempotency, receipts ----------------------------------------------------


def test_idempotent_submission(client, issuer, tenant):
    h, run_id = _setup(client, issuer, tenant)
    body = {"agent_id": tenant.agent_id, "input": {"task": "add", "mock_script": SCRIPT}}
    r = client.post("/v1/runs", json=body, headers={**h, "Idempotency-Key": "idem-key-0001"})
    assert r.status_code == 200 and r.json() == {"id": run_id, "created": False}
    body["input"]["task"] = "different"
    assert client.post("/v1/runs", json=body, headers={**h, "Idempotency-Key": "idem-key-0001"}).status_code == 409


def test_full_flow_receipt_verifies_and_redaction(client, issuer, signer, tenant, harness):
    h, run_id = _setup(client, issuer, tenant)
    harness.pump()
    assert client.get(f"/v1/runs/{run_id}", headers=h).json()["state"] == "SUCCEEDED"
    trust = TrustStore.from_json(trust_doc(signer))

    full = client.get(f"/v1/runs/{run_id}/receipt", headers=h)
    assert full.status_code == 200
    assert verify_bundle(full.content, trust, tenant.tenant_id, run_id).status is Status.VALID

    auditor = auth(issuer, tenant.tenant_id, ["receipts:export", "runs:read"], sub="usr_auditor")
    redacted = client.get(f"/v1/runs/{run_id}/receipt", headers=auditor)
    rep = verify_bundle(redacted.content, trust, tenant.tenant_id, run_id)
    assert rep.status is Status.VALID and any("withheld" in w for w in rep.warnings)
    events = client.get(f"/v1/runs/{run_id}/events", headers=auditor).json()
    assert events["payloads_included"] is False and all("payload" not in e for e in events["items"])


def test_replay_endpoint(client, issuer, tenant, harness):
    h, run_id = _setup(client, issuer, tenant)
    harness.pump()
    r = client.get(f"/v1/runs/{run_id}/replay", headers=h).json()
    assert r["state_matches_projection"] is True
    assert r["decision_replay"]["status"] == "IDENTICAL"


def test_fork_creates_new_run_and_requires_scope(client, issuer, tenant, harness):
    h, run_id = _setup(client, issuer, tenant)
    harness.pump()
    no_fork = auth(issuer, tenant.tenant_id, ["runs:write", "runs:read"])
    assert (
        client.post(
            f"/v1/runs/{run_id}/fork", json={"reason": "x"}, headers={**no_fork, "Idempotency-Key": "fork-key-001"}
        ).status_code
        == 403
    )
    r = client.post(
        f"/v1/runs/{run_id}/fork", json={"reason": "investigate"}, headers={**h, "Idempotency-Key": "fork-key-001"}
    )
    assert r.status_code == 201 and r.json()["id"] != run_id


def test_approval_via_api(client, issuer, tenant, harness):
    h = auth(issuer, tenant.tenant_id)
    client.put(f"/v1/agents/{tenant.agent_id}/grants", json={"tool": "email.send", "max_risk_class": 4}, headers=h)
    run_id = client.post(
        "/v1/runs",
        json={
            "agent_id": tenant.agent_id,
            "input": {
                "mock_script": [
                    {"tool": "email.send", "args": {"to": "a@b.example", "subject": "s", "body": "b"}},
                    {"final": "ok"},
                ]
            },
        },
        headers={**h, "Idempotency-Key": "idem-key-0005"},
    ).json()["id"]
    harness.pump()
    pending = client.get("/v1/approvals", headers=h).json()["items"]
    assert len(pending) == 1 and pending[0]["run_id"] == run_id
    svc = auth(issuer, tenant.tenant_id, ["approvals:decide"], sub="svc_bot", kind="service")
    assert (
        client.post(f"/v1/approvals/{pending[0]['id']}/decision", json={"approve": True}, headers=svc).status_code
        == 403
    )
    assert (
        client.post(f"/v1/approvals/{pending[0]['id']}/decision", json={"approve": True}, headers=h).status_code == 200
    )
    assert (
        client.post(f"/v1/approvals/{pending[0]['id']}/decision", json={"approve": True}, headers=h).status_code == 409
    )
    harness.pump()
    assert client.get(f"/v1/runs/{run_id}", headers=h).json()["state"] == "SUCCEEDED"
    assert len(harness.sink.effects) == 1


def test_cancel_terminal_conflict(client, issuer, tenant, harness):
    h, run_id = _setup(client, issuer, tenant)
    assert client.post(f"/v1/runs/{run_id}/cancel", headers=h).status_code == 200
    assert client.post(f"/v1/runs/{run_id}/cancel", headers=h).status_code == 409
    harness.pump()  # queued message for a cancelled run is a no-op
    assert client.get(f"/v1/runs/{run_id}", headers=h).json()["state"] == "CANCELLED"


def test_openapi_is_generated(client):
    spec = client.get("/openapi.json").json()
    assert "/v1/runs" in spec["paths"] and "/v1/runs/{run_id}/receipt" in spec["paths"]


# -- secrets in logs (INV-011) ------------------------------------------------------


def test_log_redaction():
    key = Ed25519PrivateKey.generate()
    tok = jwt.encode({"sub": "x"}, key, algorithm="EdDSA")
    rec = logging.makeLogRecord(
        {
            "msg": f"auth header Bearer {tok} api_key=sk-live-123",
            "levelname": "INFO",
            "authorization": "Bearer abc",
            "nested": {"password": "hunter2"},
        }
    )
    out = JsonFormatter().format(rec)
    for secret in (tok, "sk-live-123", "hunter2", "Bearer abc"):
        assert secret not in out


def test_stats_decisions_verification(client, issuer, tenant, other_tenant, harness):
    h, run_id = _setup(client, issuer, tenant)
    harness.pump()
    st = client.get("/v1/stats", headers=h).json()
    assert st["runs_by_state"] == {"SUCCEEDED": 1}
    v = client.get(f"/v1/runs/{run_id}/verification", headers=h).json()
    assert v["status"] == "VALID" and v["independent"] is False
    assert client.get("/v1/policy-decisions", headers=h).json()["items"][0]["decision"] == "allow"
    other = auth(issuer, other_tenant.tenant_id)
    assert client.get("/v1/stats", headers=other).json()["runs_by_state"] == {}
    assert client.get("/v1/policy-decisions", headers=other).json()["items"] == []
    assert client.get(f"/v1/runs/{run_id}/verification", headers=other).status_code == 404


def test_metrics_not_exposed_by_default(client):
    assert client.get("/metrics").status_code == 404


def test_reconcile_requires_valid_outcome(client, issuer, tenant):
    h, run_id = _setup(client, issuer, tenant)
    r = client.post(f"/v1/runs/{run_id}/reconcile", json={"outcome": "HACKED"}, headers=h)
    assert r.status_code == 422


def test_logout_revokes_token(client, issuer, tenant):
    h = auth(issuer, tenant.tenant_id)
    assert client.get("/v1/runs", headers=h).status_code == 200
    assert client.post("/v1/auth/logout", headers=h).status_code == 204
    assert client.get("/v1/runs", headers=h).status_code == 401
    assert client.get("/v1/runs", headers=auth(issuer, tenant.tenant_id)).status_code == 200  # other tokens unaffected


def test_grants_list_delete_and_policy_simulation(client, issuer, tenant, other_tenant, harness):
    h = auth(issuer, tenant.tenant_id)
    sim = {"agent_id": tenant.agent_id, "tool": "calc.add", "arguments": {"a": 1, "b": 2}}
    assert client.post("/v1/policy/simulate", json=sim, headers=h).json()["result"] == "deny"
    client.put(f"/v1/agents/{tenant.agent_id}/grants", json={"tool": "calc.add", "max_risk_class": 0}, headers=h)
    assert client.post("/v1/policy/simulate", json=sim, headers=h).json()["result"] == "allow"
    exp = {
        "agent_id": tenant.agent_id,
        "tool": "data.export",
        "arguments": {"dataset": "d", "destination": "x", "classification": "INTERNAL"},
    }
    client.put(f"/v1/agents/{tenant.agent_id}/grants", json={"tool": "data.export", "max_risk_class": 3}, headers=h)
    assert client.post("/v1/policy/simulate", json=exp, headers=h).json()["result"] == "require_approval"
    assert [g["tool"] for g in client.get(f"/v1/agents/{tenant.agent_id}/grants", headers=h).json()["items"]] == [
        "calc.add",
        "data.export",
    ]
    other = auth(issuer, other_tenant.tenant_id)
    assert client.delete(f"/v1/agents/{tenant.agent_id}/grants/calc.add", headers=other).status_code == 404
    assert client.post("/v1/policy/simulate", json=sim, headers=other).status_code == 404
    assert client.delete(f"/v1/agents/{tenant.agent_id}/grants/calc.add", headers=h).status_code == 204
    assert client.post("/v1/policy/simulate", json=sim, headers=h).json()["result"] == "deny"
    # Simulation never records anything.
    with tenant_tx(harness.app_engine, tenant.tenant_id) as c:
        from sqlalchemy import text

        assert c.execute(text("SELECT count(*) FROM policy_decisions")).scalar_one() == 0
    assert any(t["name"] == "email.send" for t in client.get("/v1/tools", headers=h).json()["items"])


def test_timeseries_counts_and_isolation(client, issuer, tenant, other_tenant, harness):
    h, _ = _setup(client, issuer, tenant)
    harness.pump()
    ts = client.get("/v1/stats/timeseries?range=1h", headers=h).json()
    assert 59 <= len(ts["points"]) <= 62
    assert sum(p["succeeded"] for p in ts["points"]) == 1
    assert sum(p["allowed"] for p in ts["points"]) == 1
    other = client.get("/v1/stats/timeseries?range=24h", headers=auth(issuer, other_tenant.tenant_id)).json()
    assert sum(p["succeeded"] + p["allowed"] for p in other["points"]) == 0
    assert client.get("/v1/stats/timeseries?range=99y", headers=h).status_code == 422


def test_org_rules_change_decisions_and_are_isolated(client, issuer, tenant, other_tenant, harness):
    h = auth(issuer, tenant.tenant_id)
    client.put(f"/v1/agents/{tenant.agent_id}/grants", json={"tool": "calc.add", "max_risk_class": 0}, headers=h)
    sim = {"agent_id": tenant.agent_id, "tool": "calc.add", "arguments": {"a": 1, "b": 2}}
    assert client.get("/v1/rules", headers=h).json()["preset"] == "balanced"
    assert client.post("/v1/policy/simulate", json=sim, headers=h).json()["result"] == "allow"

    rules = client.get("/v1/rules", headers=h).json()["presets"]["balanced"]["rules"]
    r = client.put(
        "/v1/rules", json={"rules": {**rules, "blocked_tools": ["calc.add"]}, "source": "dashboard"}, headers=h
    )
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["preset"] is None
    d = client.post("/v1/policy/simulate", json=sim, headers=h).json()
    assert (d["result"], d["reason"]) == ("deny", "tool_blocked_by_org_policy")

    r = client.put("/v1/rules", json={"rules": {**rules, "always_require_approval": ["calc.add"]}}, headers=h)
    assert client.post("/v1/policy/simulate", json=sim, headers=h).json()["result"] == "require_approval"
    hist = client.get("/v1/rules/history", headers=h).json()["items"]
    assert [x["version"] for x in hist] == [2, 1] and hist[1]["source"] == "dashboard"

    # Another organization is unaffected and cannot see these rules.
    other = auth(issuer, other_tenant.tenant_id)
    assert client.get("/v1/rules", headers=other).json()["version"] == 0
    assert client.get("/v1/rules/history", headers=other).json()["items"] == []
    # Services cannot change rules.
    svc = auth(issuer, tenant.tenant_id, sub="svc_bot", kind="service")
    assert client.put("/v1/rules", json={"rules": rules}, headers=svc).status_code == 403


def test_rules_are_enforced_on_real_runs(client, issuer, tenant, harness):
    h = auth(issuer, tenant.tenant_id)
    client.put(f"/v1/agents/{tenant.agent_id}/grants", json={"tool": "calc.add", "max_risk_class": 0}, headers=h)
    strict = client.get("/v1/rules", headers=h).json()["presets"]["strict"]["rules"]
    client.put("/v1/rules", json={"rules": {**strict, "approval_min_risk_class": 1, "blocked_tools": []}}, headers=h)
    # calc.add is class 0: still allowed. docs.search (class 1) now needs approval.
    client.put(f"/v1/agents/{tenant.agent_id}/grants", json={"tool": "docs.search", "max_risk_class": 1}, headers=h)
    run = client.post(
        "/v1/runs",
        json={
            "agent_id": tenant.agent_id,
            "input": {
                "mock_script": [
                    {"tool": "calc.add", "args": {"a": 1, "b": 1}},
                    {"tool": "docs.search", "args": {"query": "x"}},
                    {"final": "ok"},
                ]
            },
        },
        headers={**h, "Idempotency-Key": "rules-run-0001"},
    ).json()["id"]
    harness.pump()
    assert client.get(f"/v1/runs/{run}", headers=h).json()["state"] == "WAITING_FOR_APPROVAL"
    ap = client.get("/v1/approvals", headers=h).json()["items"][0]
    assert ap["tool"] == "docs.search"


def test_rules_file_apply_dry_run_and_export(client, issuer, tenant, harness):
    h = auth(issuer, tenant.tenant_id)
    doc = f"""version: 1
preset: strict
rules:
  blocked_tools: [email.send]
agents:
  {tenant.agent_id}:
    - {{tool: calc.add, max_risk_class: 0}}
    - {{tool: docs.search, max_risk_class: 1}}
"""
    dry = client.post("/v1/rules/file?dry_run=true", content=doc, headers=h).json()
    assert dry["dry_run"] and "organization rules" in dry["changes"]
    assert client.get(f"/v1/agents/{tenant.agent_id}/grants", headers=h).json()["items"] == []  # nothing applied
    applied = client.post("/v1/rules/file", content=doc, headers=h).json()
    assert len(applied["changes"]) == 3
    assert [g["tool"] for g in client.get(f"/v1/agents/{tenant.agent_id}/grants", headers=h).json()["items"]] == [
        "calc.add",
        "docs.search",
    ]
    assert client.post("/v1/rules/file", content=doc, headers=h).json()["changes"] == []  # idempotent
    exported = client.get("/v1/rules/file", headers=h).text
    assert "email.send" in exported and tenant.agent_id in exported
    bad = client.post("/v1/rules/file", content="version: 1\nagents:\n  agt_ffffffffffffffffffffffff: []\n", headers=h)
    assert bad.status_code == 422 and "unknown agent" in bad.json()["error"]["message"]
    assert client.post("/v1/rules/file", content="!!python/object/apply:os.system ['id']", headers=h).status_code == 422


def test_insights_report(client, issuer, tenant, harness):
    h, _ = _setup(client, issuer, tenant)
    run = client.post(
        "/v1/runs",
        json={
            "agent_id": tenant.agent_id,
            "input": {
                "mock_script": [
                    {"tool": "email.send", "args": {"to": "a@b.example", "subject": "s", "body": "b"}} for _ in range(4)
                ]
                + [{"final": "x"}]
            },
        },
        headers={**h, "Idempotency-Key": "insights-run-01"},
    )
    assert run.status_code == 201
    harness.pump()
    rep = client.get("/v1/insights?range=7d", headers=h).json()
    a = rep["agents"][0]
    assert a["requests"] == 5 and a["denied"] == 4 and a["status"] == "concern"
    assert any("email.send 4 times without permission" in r["title"] for r in rep["recommendations"])
    assert rep["verdict"] == "concern"
