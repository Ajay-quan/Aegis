# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Members and roles: membership required, role caps permissions, owners protected, every change audited."""

from __future__ import annotations

from tests.contract.conftest import ALL_SCOPES, auth


def as_(issuer, tenant, sub, scopes=None):
    return auth(issuer, tenant.tenant_id, ALL_SCOPES if scopes is None else scopes, sub=sub)


def test_first_user_becomes_owner_and_strangers_are_refused(client, issuer, tenant):
    me = client.get("/v1/me", headers=as_(issuer, tenant, "usr_alice")).json()
    assert me["role"] == "owner" and "members:manage" in me["scopes"]
    r = client.get("/v1/runs", headers=as_(issuer, tenant, "usr_mallory"))
    assert r.status_code == 403 and "not a member" in r.text


def test_role_caps_what_a_token_allows(client, issuer, tenant):
    owner = as_(issuer, tenant, "usr_alice")
    client.get("/v1/me", headers=owner)  # bootstrap
    assert client.put("/v1/members/usr_vic", headers=owner, json={"role": "viewer"}).status_code == 200
    vic = as_(issuer, tenant, "usr_vic")  # the token claims every scope ...
    me = client.get("/v1/me", headers=vic).json()
    assert me["role"] == "viewer" and "runs:write" not in me["scopes"] and "payloads:read" not in me["scopes"]
    assert client.get("/v1/runs", headers=vic).status_code == 200
    r = client.post(
        "/v1/runs",
        headers={**vic, "Idempotency-Key": "k_viewer_write_01"},
        json={"agent_id": tenant.agent_id, "input": {"task": "x"}},
    )
    assert r.status_code == 403  # ... but the role does not allow it
    # And the token caps the role: an owner whose token lacks a scope does not get it.
    narrow = as_(issuer, tenant, "usr_alice", ["runs:read"])
    assert "members:manage" not in client.get("/v1/me", headers=narrow).json()["scopes"]


def test_admins_cannot_touch_owners_and_the_last_owner_stays(client, issuer, tenant):
    owner = as_(issuer, tenant, "usr_alice")
    client.get("/v1/me", headers=owner)
    client.put("/v1/members/usr_ada", headers=owner, json={"role": "admin"})
    ada = as_(issuer, tenant, "usr_ada")
    assert client.put("/v1/members/usr_dev", headers=ada, json={"role": "developer"}).status_code == 200
    assert (
        client.put("/v1/members/usr_ada", headers=ada, json={"role": "owner"}).status_code == 403
    )  # no self-promotion
    assert client.put("/v1/members/usr_alice", headers=ada, json={"role": "viewer"}).status_code == 403
    assert client.delete("/v1/members/usr_alice", headers=ada).status_code == 403
    r = client.put("/v1/members/usr_alice", headers=owner, json={"role": "admin"})  # last owner demoting herself
    assert r.status_code == 409
    assert client.delete("/v1/members/usr_alice", headers=owner).status_code == 409
    assert client.put("/v1/members/usr_ada", headers=owner, json={"role": "owner"}).status_code == 200
    assert client.put("/v1/members/usr_alice", headers=owner, json={"role": "admin"}).status_code == 200  # now allowed


def test_developers_cannot_manage_members(client, issuer, tenant):
    owner = as_(issuer, tenant, "usr_alice")
    client.get("/v1/me", headers=owner)
    client.put("/v1/members/usr_dan", headers=owner, json={"role": "developer"})
    dan = as_(issuer, tenant, "usr_dan")
    assert client.put("/v1/members/usr_x", headers=dan, json={"role": "viewer"}).status_code == 403


def test_removed_member_loses_access_immediately_and_changes_are_audited(client, issuer, tenant):
    owner = as_(issuer, tenant, "usr_alice")
    client.get("/v1/me", headers=owner)
    client.put("/v1/members/usr_tmp", headers=owner, json={"role": "developer"})
    tmp = as_(issuer, tenant, "usr_tmp")
    assert client.get("/v1/runs", headers=tmp).status_code == 200
    client.put("/v1/members/usr_tmp", headers=owner, json={"role": "viewer"})
    assert client.delete("/v1/members/usr_tmp", headers=owner).status_code == 204
    assert client.get("/v1/runs", headers=tmp).status_code == 403
    acts = [(e["action"], e["target"]) for e in client.get("/v1/audit-events", headers=owner).json()["items"]]
    for a in ("member.added", "member.role_changed", "member.removed"):
        assert (a, "usr_tmp") in acts


def test_membership_is_per_organization(client, issuer, tenant, other_tenant):
    owner = as_(issuer, tenant, "usr_alice")
    client.get("/v1/me", headers=owner)
    client.put("/v1/members/usr_vic", headers=owner, json={"role": "admin"})
    client.get("/v1/me", headers=auth(issuer, other_tenant.tenant_id, sub="usr_bob"))  # bob owns the other org
    r = client.get("/v1/runs", headers=auth(issuer, other_tenant.tenant_id, sub="usr_vic"))
    assert r.status_code == 403  # an admin in one organization is a stranger in another
    listed = client.get("/v1/members", headers=auth(issuer, other_tenant.tenant_id, sub="usr_bob")).json()["items"]
    assert [m["subject"] for m in listed] == ["usr_bob"]
