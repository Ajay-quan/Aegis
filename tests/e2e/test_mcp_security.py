# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""UC-08: a malicious MCP server cannot expand an agent's authority."""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import text

from aegisruntime.mcpgw.bridge import McpServerConfig, McpToolMapping, discover, register_server
from aegisruntime.persistence.db import tenant_tx
from aegisruntime.tools.registry import RiskClass

SERVER = "tests/fixtures/malicious_mcp_server.py"


def _cfg(tools=None, **kw):
    return McpServerConfig("notes", sys.executable, (SERVER,), tools or {}, **kw)


@pytest.fixture(scope="module")
def pinned():
    return {t.name: t.schema_digest for t in discover(_cfg())}


def test_only_mapped_tools_registered_and_annotations_ignored(harness, pinned):
    cfg = _cfg({"read_notes": McpToolMapping(RiskClass.CONTROLLED_READ, pinned["read_notes"])})
    rep = register_server(harness.worker.registry, cfg)
    assert rep.registered == ["read_notes"]
    assert set(rep.ignored_unmapped) == {"delete_all", "env_probe", "broken"}
    spec = harness.worker.registry.get("mcp.notes.read_notes")
    assert spec.risk_class is RiskClass.CONTROLLED_READ  # platform-assigned, not server's readOnlyHint
    assert spec.description.startswith("[untrusted MCP description]")


def test_schema_rug_pull_disables_tool(harness, pinned):
    cfg = _cfg(
        {"delete_all": McpToolMapping(RiskClass.REVERSIBLE_WRITE, pinned["delete_all"])},
        credential_env={"NOTES_VARIANT": "v2"},
    )
    rep = register_server(harness.worker.registry, cfg)
    assert rep.disabled_schema_changed == ["delete_all"]
    assert harness.worker.registry.get("mcp.notes.delete_all") is None


def test_malicious_mcp_end_to_end(harness, tenant, pinned, tmp_path, monkeypatch):
    sink_file = tmp_path / "sink.txt"
    monkeypatch.setenv("AEGIS_SECRET_PROBE", "super-secret-value")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    h, t = harness, tenant
    cfg = _cfg(
        {
            "read_notes": McpToolMapping(RiskClass.CONTROLLED_READ, pinned["read_notes"], retry_safe=True),
            "env_probe": McpToolMapping(RiskClass.CONTROLLED_READ, pinned["env_probe"], retry_safe=True),
            "broken": McpToolMapping(RiskClass.CONTROLLED_READ, pinned["broken"], retry_safe=True),
        },
        credential_env={"NOTES_SINK": str(sink_file)},
    )
    register_server(h.worker.registry, cfg)
    for tool in ("mcp.notes.read_notes", "mcp.notes.env_probe", "mcp.notes.broken"):
        h.grant(t, tool, 1)

    run_id = h.submit(
        t,
        [
            {"tool": "mcp.notes.read_notes", "args": {"topic": "q3"}},
            {"tool": "mcp.notes.delete_all", "args": {}},  # unmapped
            {"tool": "email.send", "args": {"to": "boss@evil.example", "subject": "x", "body": "y"}},  # not granted
            {"tool": "mcp.notes.read_notes", "args": {"topic": "q3", "grant": "class4"}},  # schema violation
            {"tool": "mcp.notes.env_probe", "args": {}},
            {"tool": "mcp.notes.broken", "args": {}},
            {"final": "done"},
        ],
    )
    h.pump()
    assert h.state(t, run_id) == "SUCCEEDED"
    assert not sink_file.exists()  # delete_all never ran
    assert h.sink.effects == []  # email never sent

    with tenant_tx(h.app_engine, t.tenant_id) as c:
        rows = c.execute(
            text(
                "SELECT event_type, record->'payload'->>'tool', record->'payload'->>'reason', "
                "record->'payload'->'output'->>'text', record->'payload'->>'error' FROM events WHERE run_id=:r "
                "AND event_type IN ('tool.denied','tool.authorization','tool.execution_succeeded','tool.execution_failed') "
                "ORDER BY sequence_number"
            ),
            {"r": run_id},
        ).all()
    denied = [
        (r[1], r[2]) for r in rows if r[0] == "tool.denied" or (r[0] == "tool.authorization" and r[2] != "granted")
    ]
    assert denied == [
        ("mcp.notes.delete_all", "unknown_tool"),
        ("email.send", "no_matching_grant"),
        ("mcp.notes.read_notes", "invalid_arguments"),
    ]
    outputs = {r[1]: r[3] for r in rows if r[0] == "tool.execution_succeeded"}
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in outputs["mcp.notes.read_notes"]  # recorded as data
    env_keys = outputs["mcp.notes.env_probe"].split(",")
    assert not any(k.startswith(("AEGIS", "OPENAI")) for k in env_keys), env_keys  # no secret inheritance
    assert [r[4] for r in rows if r[0] == "tool.execution_failed"] == ["McpToolError"]
