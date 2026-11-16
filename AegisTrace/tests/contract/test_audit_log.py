# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Every administrative change leaves an audit entry, written in the same transaction."""

from __future__ import annotations

from tests.contract.conftest import auth


def _events(client, issuer, tenant):
    return client.get("/v1/audit-events?limit=200", headers=auth(issuer, tenant.tenant_id)).json()["items"]


def test_admin_actions_are_audited(client, issuer, harness, tenant):
    h = auth(issuer, tenant.tenant_id)
    pid = client.post("/v1/projects", headers=h, json={"name": "audit-proj"}).json()["id"]
    aid = client.post(
        "/v1/agents",
        headers=h,
        json={"project_id": pid, "name": "audit-agent", "model_provider": "mock", "model_id": "m"},
    ).json()["id"]
    assert (
        client.put(f"/v1/agents/{aid}/grants", headers=h, json={"tool": "calc.add", "max_risk_class": 0}).status_code
        == 200
    )
    assert client.delete(f"/v1/agents/{aid}/grants/calc.add", headers=h).status_code == 204
    rules = client.get("/v1/rules", headers=h).json()["rules"]
    assert (
        client.put(
            "/v1/rules", headers=h, json={"rules": {**rules, "approval_ttl_minutes": 30}, "note": "tighter"}
        ).status_code
        == 200
    )

    harness.grant(tenant, "calc.add", 0)
    run_id = harness.submit(tenant, [{"tool": "calc.add", "args": {"a": 1, "b": 1}}, {"final": "2"}])
    harness.pump()
    assert (
        client.put(f"/v1/runs/{run_id}/legal-hold", headers=h, json={"hold": True, "reason": "case 7"}).status_code
        == 200
    )
    assert client.put(f"/v1/runs/{run_id}/legal-hold", headers=h, json={"hold": False}).status_code == 200
    assert client.post(f"/v1/runs/{run_id}/erase", headers=h, json={"reason": "request 9"}).status_code == 200

    got = {(e["action"], e["target"]) for e in _events(client, issuer, tenant)}
    for want in [
        ("project.created", pid),
        ("agent.created", aid),
        ("grant.set", aid),
        ("grant.revoked", aid),
        ("legal_hold.placed", run_id),
        ("legal_hold.released", run_id),
        ("data.erased", run_id),
    ]:
        assert want in got, want
    assert any(a == "rules.updated" for a, _ in got)
    by = {e["actor_id"] for e in _events(client, issuer, tenant)}
    assert by == {"usr_alice"}  # who did it


def test_failed_changes_leave_no_audit_entry(client, issuer, tenant):
    h = auth(issuer, tenant.tenant_id)
    before = len(_events(client, issuer, tenant))
    assert client.delete("/v1/agents/agt_000000000000000000000000/grants/calc.add", headers=h).status_code == 404
    assert (
        client.post("/v1/runs/run_000000000000000000000000/erase", headers=h, json={"reason": "nope"}).status_code
        == 404
    )
    assert len(_events(client, issuer, tenant)) == before


def test_audit_log_is_tenant_scoped(client, issuer, tenant, other_tenant):
    client.post("/v1/projects", headers=auth(issuer, tenant.tenant_id), json={"name": "only-mine"})
    theirs = _events(client, issuer, other_tenant)
    assert all(e["detail"].get("name") != "only-mine" for e in theirs)
