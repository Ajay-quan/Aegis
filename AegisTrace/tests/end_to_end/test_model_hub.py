# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Model Hub: registrations with encrypted keys, real connection tests, endpoint safety, and agents
running on a registered OpenAI-compatible endpoint (a local stand-in server)."""

from __future__ import annotations

import json

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from aegistrace.agents import models_hub
from aegistrace.api.app import Deps, create_app
from aegistrace.evidence.signing import LocalEd25519Signer
from aegistrace.identity.devissuer import AUDIENCE, ISSUER, DevIssuer
from aegistrace.identity.jwt import JwksCache, TokenValidator
from aegistrace.persistence import sealing
from tests.fixtures.remote_mcp import Served, free_port

KEY = "sk-test-not-a-real-key"


def provider_app() -> Starlette:
    async def models(req: Request) -> JSONResponse:
        if req.headers.get("authorization") != f"Bearer {KEY}":
            return JSONResponse({"error": "bad key"}, status_code=401)
        return JSONResponse({"data": [{"id": "tiny-1"}, {"id": "tiny-2"}]})

    async def chat(req: Request) -> JSONResponse:
        body = await req.json()
        step = sum(1 for m in body["messages"] if m["role"] == "assistant")
        usage = {"prompt_tokens": 120 + step, "completion_tokens": 7}
        if step == 0:
            msg = {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "calc.add", "arguments": json.dumps({"a": 2, "b": 2})}}],
            }
        else:
            msg = {"role": "assistant", "content": "four"}
        return JSONResponse({"choices": [{"message": msg}], "usage": usage})

    return Starlette(routes=[Route("/v1/models", models), Route("/v1/chat/completions", chat, methods=["POST"])])


@pytest.fixture(scope="module")
def provider():
    port = free_port()
    with Served(provider_app(), port):
        yield f"http://127.0.0.1:{port}/v1"


@pytest.fixture
def issuer() -> DevIssuer:
    return DevIssuer()


@pytest.fixture
def api(app_engine, harness, issuer) -> TestClient:
    deps = Deps(
        app_engine,
        TokenValidator(ISSUER, AUDIENCE, JwksCache(issuer.jwks)),
        LocalEd25519Signer(),
        harness.redis,
        gateway=harness.worker.gateway,
    )
    return TestClient(create_app(deps), raise_server_exceptions=False)


ADMIN = ["agents:read", "agents:write", "policies:write", "runs:read", "audit:read"]


def h(issuer, tenant, scopes=ADMIN):
    return {"Authorization": "Bearer " + issuer.mint("usr_alice", tenant.tenant_id, scopes)}


def register(api, issuer, tenant, provider, **kw):
    body = {
        "name": kw.pop("name", "tiny"),
        "provider": "openai-compatible",
        "model_id": "tiny-1",
        "base_url": provider,
        "api_key": KEY,
        "allow_private_network": True,
        **kw,
    }
    return api.post("/v1/models", headers=h(issuer, tenant), json=body)


def test_key_is_stored_encrypted_and_never_returned(api, issuer, tenant, provider, owner_engine):
    r = register(api, issuer, tenant, provider)
    assert r.status_code == 201 and "api_key" not in r.text and KEY not in r.text
    listed = api.get("/v1/models", headers=h(issuer, tenant)).json()["items"]
    assert listed[0]["has_key"] is True and KEY not in json.dumps(listed, default=str)
    with owner_engine.begin() as c:
        blob = c.execute(text("SELECT secret FROM model_registrations WHERE id=:i"), {"i": r.json()["id"]}).scalar()
    assert KEY.encode() not in bytes(blob)
    with pytest.raises(InvalidTag):  # bound to its registration: useless under another id
        sealing.open_secret(f"{tenant.tenant_id}:mdl_other", bytes(blob))


def test_connection_test_reports_real_outcomes(api, issuer, tenant, provider):
    ok = register(api, issuer, tenant, provider).json()["id"]
    bad_key = register(api, issuer, tenant, provider, name="badkey", api_key="sk-wrong").json()["id"]
    missing = register(api, issuer, tenant, provider, name="missing", model_id="huge-9").json()["id"]
    t = lambda i: api.post(f"/v1/models/{i}/test", headers=h(issuer, tenant)).json()  # noqa: E731
    assert t(ok)["status"] == "connected" and "tiny-1" in t(ok)["detail"]
    assert t(bad_key)["status"] == "failed" and "refused the credentials" in t(bad_key)["detail"]
    assert t(missing)["status"] == "failed" and "not among" in t(missing)["detail"]


@pytest.mark.parametrize(
    ("url", "addrs", "allow", "ok"),
    [
        ("https://api.example.com/v1", ["93.184.216.34"], False, True),
        ("http://api.example.com/v1", ["93.184.216.34"], False, False),  # public must be https
        ("http://10.0.0.9:8000/v1", ["10.0.0.9"], False, False),  # private needs the flag
        ("http://10.0.0.9:8000/v1", ["10.0.0.9"], True, True),
        ("http://169.254.169.254/v1", ["169.254.169.254"], True, False),  # metadata: never
    ],
)
def test_endpoint_rules(url, addrs, allow, ok):
    if ok:
        models_hub.check_endpoint(url, allow, lambda h_: addrs)
    else:
        with pytest.raises(models_hub.EndpointRefused):
            models_hub.check_endpoint(url, allow, lambda h_: addrs)


def test_agent_runs_on_a_registered_model_with_provider_reported_usage(
    api, issuer, tenant, provider, harness, app_engine
):
    mid = register(api, issuer, tenant, provider).json()["id"]
    agent = api.post(
        "/v1/agents",
        headers=h(issuer, tenant),
        json={"project_id": tenant.project_id, "name": "hub-agent", "model_provider": "registry", "model_id": mid},
    ).json()["id"]
    from tests.integration.conftest import TenantCtx

    t2 = TenantCtx(tenant.tenant_id, tenant.project_id, agent)
    harness.grant(t2, "calc.add", 0)
    run_id = harness.submit(t2, [], task="add two and two")
    harness.pump()
    assert harness.state(t2, run_id) == "SUCCEEDED"
    u = api.get(f"/v1/runs/{run_id}/usage", headers=h(issuer, tenant)).json()
    assert u["estimated"] is False and [s["input_tokens"] for s in u["steps"]] == [120, 121]
    assert api.delete(f"/v1/models/{mid}", headers=h(issuer, tenant)).status_code == 409  # in use


def test_unrunnable_provider_fails_the_run_with_a_reason(api, issuer, tenant, harness):
    mid = api.post(
        "/v1/models", headers=h(issuer, tenant), json={"name": "claude", "provider": "anthropic", "model_id": "x"}
    ).json()["id"]
    agent = api.post(
        "/v1/agents",
        headers=h(issuer, tenant),
        json={"project_id": tenant.project_id, "name": "a2", "model_provider": "registry", "model_id": mid},
    ).json()["id"]
    from tests.integration.conftest import TenantCtx

    t2 = TenantCtx(tenant.tenant_id, tenant.project_id, agent)
    run_id = harness.submit(t2, [], task="x")
    harness.pump()
    assert harness.state(t2, run_id) == "FAILED"
    run = api.get(f"/v1/runs/{run_id}", headers=h(issuer, tenant)).json()
    assert "cannot run on anthropic" in json.dumps(run["result"])


def test_registering_needs_policies_write(api, issuer, tenant, provider):
    r = api.post(
        "/v1/models",
        headers=h(issuer, tenant, ["agents:read"]),
        json={"name": "x", "provider": "mock", "model_id": "m"},
    )
    assert r.status_code == 403
