# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""INV-006: replay cannot cause side effects."""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from aegistrace.agents.model import MockModel
from aegistrace.replay.engine import ReplayStatus, reconstruct, replay_decisions

REPLAY_DIR = Path(__file__).resolve().parents[2] / "packages/core/src/aegistrace/replay"
FORBIDDEN = (
    "aegistrace.persistence",
    "aegistrace.tools",
    "aegistrace.workers",
    "aegistrace.api",
    "sqlalchemy",
    "httpx",
    "redis",
    "socket",
    "requests",
    "urllib",
)


def test_replay_package_import_boundary():
    for path in REPLAY_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for n in names:
                assert not n.startswith(FORBIDDEN), f"{path.name} imports {n}"


def _records():
    from aegistrace.evidence.events import ChainBuilder

    c = ChainBuilder("tnt_a", "prj", "run_1")
    rows = [
        ("run.created", {"agent_id": "agt", "input": {"task": "t"}}),
        ("run.state_changed", {"from": "CREATED", "to": "VALIDATING"}),
        ("run.state_changed", {"from": "VALIDATING", "to": "QUEUED"}),
        ("run.state_changed", {"from": "QUEUED", "to": "RUNNING"}),
        (
            "model.invoked",
            {
                "step": 0,
                "response": {
                    "tool_call": {"tool": "email.send", "arguments": {"to": "x@y.z"}},
                    "text": None,
                    "usage": {},
                },
            },
        ),
        ("tool.execution_succeeded", {"step": 0, "tool": "email.send", "output": {"message_id": "m1"}}),
        ("model.invoked", {"step": 1, "response": {"tool_call": None, "text": "sent", "usage": {}}}),
        ("run.state_changed", {"from": "RUNNING", "to": "SUCCEEDED", "result": {"text": "sent"}}),
    ]
    for i, (t, p) in enumerate(rows):
        c.append(
            event_id=f"e{i}",
            event_type=t,
            actor_id="a",
            correlation_id="run_1",
            timestamp="2026-01-01T00:00:00Z",
            payload=p,
        )
    return [e.to_record() for e in c.events]


@pytest.fixture
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network access during replay")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)


def test_reconstruct(no_network):
    v = reconstruct(_records())
    assert v.state == "SUCCEEDED" and v.attempts == 1 and v.tool_calls[0]["tool"] == "email.send"


def test_decision_replay_identical_without_side_effects(no_network):
    r = replay_decisions(_records())
    assert r.status is ReplayStatus.IDENTICAL and r.steps_compared == 2


def test_divergence_detected_with_new_agent_version(no_network):
    new_version = MockModel([{"tool": "email.send", "args": {"to": "other@y.z"}}])
    r = replay_decisions(_records(), new_version)
    assert r.status is ReplayStatus.DIVERGED and r.divergence.step == 0


def test_missing_and_incompatible(no_network):
    recs = _records()
    del recs[5]["payload"]
    assert replay_decisions(recs).status is ReplayStatus.MISSING_DEPENDENCY
    recs = _records()
    recs[0]["schema_version"] = 9
    assert replay_decisions(recs).status is ReplayStatus.INCOMPATIBLE_VERSION
    assert replay_decisions(_records()[:3] + _records()[4:]).status is ReplayStatus.INCOMPLETE_HISTORY
