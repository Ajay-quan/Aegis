# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
import pytest
from pydantic import ValidationError

from aegistrace.authorization.rules import PRESETS, OrgRules, parse_rules_file, preset_of
from aegistrace.insights import AgentReport, classify


def agent(**kw):
    base = dict(
        agent_id="agt",
        name="a",
        runs=10,
        succeeded=10,
        failed=0,
        requests=10,
        allowed=10,
        denied=0,
        approvals_requested=0,
        approvals_rejected=0,
        needs_review=0,
    )
    return classify(AgentReport(**{**base, **kw}))


def test_healthy_agent():
    assert agent().status == "healthy"


def test_idle_agent():
    assert agent(runs=0, succeeded=0, requests=0, allowed=0).status == "idle"


def test_frequent_denials_are_a_concern_with_reason():
    a = agent(requests=20, allowed=12, denied=8)
    assert a.status == "concern" and "40%" in a.reasons[0]


def test_small_samples_are_not_judged():
    assert agent(requests=3, allowed=1, denied=2).status == "healthy"


def test_failures_and_rejections():
    assert agent(succeeded=9, failed=1).status == "watch"
    assert agent(succeeded=6, failed=4).status == "concern"
    assert agent(approvals_rejected=1).status == "watch"
    assert agent(needs_review=1).status == "concern"


def test_presets_and_detection():
    assert preset_of(PRESETS["strict"]) == "strict"
    assert preset_of(OrgRules()) == "balanced"
    assert preset_of(OrgRules(blocked_tools=["email.send"])) is None


def test_rules_validation():
    with pytest.raises(ValidationError):
        OrgRules(approval_min_risk_class=0)
    with pytest.raises(ValidationError):
        OrgRules(blocked_tools=["../etc"])
    with pytest.raises(ValidationError):
        OrgRules.model_validate({"unknown": 1})


def test_rules_file_parsing():
    doc = parse_rules_file("""
version: 1
preset: strict
rules:
  blocked_tools: [email.send]
agents:
  agt_000000000000000000000001:
    - {tool: calc.add, max_risk_class: 0}
""")
    r = doc.resolved()
    assert r.approval_min_risk_class == 2 and r.blocked_tools == ["email.send"]
    with pytest.raises(ValueError):
        parse_rules_file("!!python/object/apply:os.system ['echo pwned']")
    with pytest.raises(ValueError):
        parse_rules_file("version: 2")
