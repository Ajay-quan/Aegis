# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Agent Builder: configuration, versions, the memory switch (real grants), limits and instructions in runs."""

from __future__ import annotations

from aegistrace.agents.model import MockModel
from tests.contract.conftest import auth
from tests.integration.conftest import TenantCtx


def _create(client, h, tenant, **kw):
    r = client.post(
        "/v1/agents", headers=h, json={"project_id": tenant.project_id, "name": kw.pop("name", "builder"), **kw}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_create_edit_and_version_history(client, issuer, tenant):
    h = auth(issuer, tenant.tenant_id)
    aid = _create(client, h, tenant, instructions="Answer briefly.", max_steps=5)
    a = client.get(f"/v1/agents/{aid}", headers=h).json()
    assert (a["version"], a["instructions"], a["max_steps"]) == (1, "Answer briefly.", 5)
    r = client.put(f"/v1/agents/{aid}", headers=h, json={"instructions": "Answer in French.", "note": "locale"})
    assert r.json()["version"] == 2
    assert (
        client.put(f"/v1/agents/{aid}", headers=h, json={"instructions": "Answer in French."}).json()["version"] == 2
    )  # no-op
    versions = client.get(f"/v1/agents/{aid}/versions", headers=h).json()["items"]
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[1]["config"]["instructions"] == "Answer briefly." and versions[0]["note"] == "locale"
    events = client.get("/v1/audit-events", headers=h).json()["items"]
    assert any(e["action"] == "agent.updated" and e["target"] == aid for e in events)


def test_memory_switch_is_a_real_permission_change(client, issuer, tenant):
    h = auth(issuer, tenant.tenant_id)
    aid = _create(client, h, tenant, name="mem")
    dev = auth(issuer, tenant.tenant_id, ["agents:read", "agents:write"])
    assert client.put(f"/v1/agents/{aid}", headers=dev, json={"memory_enabled": True}).status_code == 403
    assert client.put(f"/v1/agents/{aid}", headers=h, json={"memory_enabled": True}).status_code == 200
    tools = {g["tool"]: g["max_risk_class"] for g in client.get(f"/v1/agents/{aid}/grants", headers=h).json()["items"]}
    assert tools == {"memory.recall": 1, "memory.remember": 2}
    client.put(f"/v1/agents/{aid}", headers=h, json={"memory_enabled": False})
    assert client.get(f"/v1/agents/{aid}/grants", headers=h).json()["items"] == []


def test_model_must_exist_in_the_hub(client, issuer, tenant):
    h = auth(issuer, tenant.tenant_id)
    aid = _create(client, h, tenant, name="m")
    r = client.put(f"/v1/agents/{aid}", headers=h, json={"model_provider": "registry", "model_id": "mdl_missing"})
    assert r.status_code == 422


def test_runs_use_the_agents_instructions_and_step_limit(client, issuer, tenant, harness, monkeypatch):
    h = auth(issuer, tenant.tenant_id)
    seen: list[str] = []
    real = MockModel.complete

    def spy(self, messages, tools):
        seen.append(messages[0]["content"])
        return real(self, messages, tools)

    monkeypatch.setattr(MockModel, "complete", spy)
    aid = _create(client, h, tenant, name="limited", instructions="Never use email.", max_steps=1)
    t = TenantCtx(tenant.tenant_id, tenant.project_id, aid)
    harness.grant(t, "calc.add", 0)
    rid = harness.submit(t, [{"tool": "calc.add", "args": {"a": 1, "b": 1}}, {"final": "2"}])
    harness.pump()
    assert "Never use email." in seen[0]
    assert harness.state(t, rid) == "FAILED"  # one step allowed; the answer would have needed a second
    run = client.get(f"/v1/runs/{rid}", headers=h).json()
    assert run["result"] == {"error": "step_budget"}


def test_agents_are_tenant_scoped(client, issuer, tenant, other_tenant):
    aid = _create(client, auth(issuer, tenant.tenant_id), tenant, name="mine")
    other = auth(issuer, other_tenant.tenant_id)
    assert client.get(f"/v1/agents/{aid}", headers=other).status_code == 404
    assert client.put(f"/v1/agents/{aid}", headers=other, json={"instructions": "x"}).status_code == 404
