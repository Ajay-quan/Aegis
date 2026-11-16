# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Token usage per model call and estimated cost from the organization's own price list."""

from __future__ import annotations

from aegistrace.agents.model import ModelResponse, ToolCall, normalize_usage
from tests.contract.conftest import auth


def _run(h, t, final="ok"):
    h.grant(t, "calc.add", 0) if not getattr(h, "_granted_usage", None) else None
    h._granted_usage = True
    rid = h.submit(t, [{"tool": "calc.add", "args": {"a": 1, "b": 2}}, {"final": final}])
    h.pump()
    return rid


def test_provider_counts_are_used_as_reported_and_others_are_estimated():
    msgs = [{"role": "user", "content": "x" * 400}]
    resp = ModelResponse(None, "y" * 40)
    assert normalize_usage({"prompt_tokens": 12, "completion_tokens": 3}, msgs, [], resp) == {
        "input_tokens": 12,
        "output_tokens": 3,
        "source": "provider",
    }
    assert normalize_usage({"input_tokens": 7, "output_tokens": 2}, msgs, [], resp)["source"] == "provider"
    est = normalize_usage({}, msgs, [], resp)
    assert est["source"] == "estimate" and est["input_tokens"] >= 100 and est["output_tokens"] == 10
    call = normalize_usage({}, msgs, [], ModelResponse(ToolCall("calc.add", {"a": 1}), None))
    assert call["output_tokens"] > 0


def test_each_model_call_is_recorded_once_with_no_cost_until_a_price_is_set(client, issuer, harness, tenant):
    h = auth(issuer, tenant.tenant_id)
    rid = _run(harness, tenant)
    u = client.get(f"/v1/runs/{rid}/usage", headers=h).json()
    assert [s["step"] for s in u["steps"]] == [0, 1]  # two model calls: the tool proposal and the answer
    assert u["estimated"] is True and u["cost_usd"] is None  # mock model reports nothing; no price set
    assert u["input_tokens"] > 0 and u["output_tokens"] > 0


def test_cost_uses_the_price_list_and_rounds_up(client, issuer, harness, tenant):
    h = auth(issuer, tenant.tenant_id)
    r = client.put(
        "/v1/model-prices",
        headers=h,
        json={
            "provider": "mock",
            "model_id": "mock-deterministic-1",
            "input_usd_per_mtok": 3.0,
            "output_usd_per_mtok": 15.0,
        },
    )
    assert r.status_code == 200
    rid = _run(harness, tenant)
    u = client.get(f"/v1/runs/{rid}/usage", headers=h).json()
    expected = sum(
        -(-(s["input_tokens"] * 3_000_000 + s["output_tokens"] * 15_000_000) // 1_000_000) for s in u["steps"]
    )
    assert u["cost_usd"] == round(expected / 1_000_000, 6)
    summary = client.get("/v1/usage?range=24h", headers=h).json()
    mock = next(m for m in summary["by_model"] if m["model_id"] == "mock-deterministic-1")
    assert mock["calls"] >= 2 and mock["cost_usd"] is not None
    prices = client.get("/v1/model-prices", headers=h).json()
    assert prices["items"][0]["input_usd_per_mtok"] == 3.0
    events = client.get("/v1/audit-events", headers=h).json()["items"]
    assert any(e["action"] == "model_price.set" for e in events)


def test_usage_and_prices_are_tenant_scoped(client, issuer, harness, tenant, other_tenant):
    _run(harness, tenant)
    theirs = client.get("/v1/usage?range=24h", headers=auth(issuer, other_tenant.tenant_id)).json()
    assert theirs["totals"]["calls"] == 0


def test_setting_prices_needs_policies_write(client, issuer, tenant):
    reader = auth(issuer, tenant.tenant_id, ["agents:read", "runs:read"])
    r = client.put(
        "/v1/model-prices",
        headers=reader,
        json={"provider": "mock", "model_id": "m", "input_usd_per_mtok": 1, "output_usd_per_mtok": 1},
    )
    assert r.status_code == 403
