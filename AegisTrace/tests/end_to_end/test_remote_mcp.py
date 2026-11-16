# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Remote MCP servers over Streamable HTTP with OAuth 2.1 client credentials:
audience-bound tokens, issuer pinning, token reuse, destination checks, and
the same policy/evidence path as every other tool."""

from __future__ import annotations

import httpx
import pytest
from mcp.client.auth.exceptions import OAuthFlowError, OAuthTokenError

from aegistrace.mcpgw.bridge import (
    McpDestinationDenied,
    McpOAuth,
    McpServerConfig,
    McpToolMapping,
    check_remote_url,
    discover,
    register_server,
)
from aegistrace.orchestration.service import load_events
from aegistrace.persistence.db import tenant_tx
from aegistrace.tools.registry import RiskClass
from tests.fixtures.remote_mcp import AuthServer, Served, free_port, mcp_app

SECRET = "s3cret-client-credential"


def _leaf(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup):
        exc = exc.exceptions[0]
    return exc


@pytest.fixture(scope="module")
def remote():
    ap, mp = free_port(), free_port()
    auth = AuthServer(issuer=f"http://127.0.0.1:{ap}", clients={"aegis-client": SECRET})
    resource = f"http://127.0.0.1:{mp}/mcp"
    with Served(auth.app(), ap), Served(mcp_app(auth, resource), mp):
        yield auth, resource


def _cfg(remote, server_id="remote", tools=None, **oauth_kw):
    auth, resource = remote
    oauth = McpOAuth(
        **{
            "issuer": auth.issuer,
            "client_id": "aegis-client",
            "client_secret": SECRET,
            "scope": "notes:read",
            **oauth_kw,
        }
    )
    return McpServerConfig(server_id, url=resource, tools=tools or {}, oauth=oauth, allow_insecure_http=True)


def test_discovers_and_runs_remote_tools_through_policy_and_evidence(harness, tenant, remote):
    auth, resource = remote
    tools = {t.name: t for t in discover(_cfg(remote, "remote1"))}
    assert set(tools) == {"read_notes"}
    issued = [r for r in auth.requests if r.get("grant_type") == "client_credentials"]
    assert issued and all(r["resource"] == resource for r in issued)  # RFC 8707: token bound to this server
    assert all(r.get("scope") == "notes:read" for r in issued)

    cfg = _cfg(
        remote, "remote1", {"read_notes": McpToolMapping(RiskClass.CONTROLLED_READ, tools["read_notes"].schema_digest)}
    )
    assert register_server(harness.worker.registry, cfg, discovered=list(tools.values())).registered == ["read_notes"]
    h, t = harness, tenant
    h.grant(t, "mcp.remote1.read_notes", 1)
    run_id = h.submit(t, [{"tool": "mcp.remote1.read_notes", "args": {"topic": "launch"}}, {"final": "ok"}])
    h.pump()
    assert h.state(t, run_id) == "SUCCEEDED"
    with tenant_tx(h.app_engine, t.tenant_id) as c:
        out = [
            e["payload"]["output"]["text"]
            for e in load_events(c, run_id)
            if e["event_type"] == "tool.execution_succeeded"
        ]
    assert out == ["Remote notes on launch: ship on Friday."]


def test_tokens_are_cached_per_server_until_expiry(remote):
    auth, _ = remote
    cfg = _cfg(remote, "remote2")
    discover(cfg)
    before = len(auth.requests)
    discover(cfg)
    discover(cfg)
    assert len(auth.requests) == before  # reused, not re-requested


def test_wrong_client_secret_gets_no_access(remote):
    auth, _ = remote
    before_req, before_tok = len(auth.requests), len(auth.tokens)
    with pytest.raises(BaseException) as exc:  # the SDK surfaces the OAuth failure inside an exception group
        discover(_cfg(remote, "remote3", client_secret="wrong"))
    leaf = _leaf(exc.value)
    assert isinstance(leaf, OAuthTokenError) and "invalid_client" in str(leaf)
    assert len(auth.requests) > before_req  # it did try the configured authorization server ...
    assert len(auth.tokens) == before_tok  # ... and was refused: no token issued


def test_only_the_configured_issuer_is_trusted(remote):
    auth, _ = remote
    before = len(auth.requests)
    with pytest.raises(BaseException) as exc:
        discover(_cfg(remote, "remote4", issuer="https://attacker-idp.example"))
    leaf = _leaf(exc.value)
    assert isinstance(leaf, OAuthFlowError) and "issuer mismatch" in str(leaf)
    assert len(auth.requests) == before  # credentials were never sent to any authorization server


def test_server_refuses_tokens_issued_for_another_server(remote):
    auth, resource = remote
    other = httpx.post(
        auth.issuer + "/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "aegis-client",
            "client_secret": SECRET,
            "resource": "https://other.example/mcp",
            "scope": "notes:read",
        },
    ).json()["access_token"]
    r = httpx.post(
        resource,
        headers={"Authorization": f"Bearer {other}", "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert r.status_code == 401


def _resolver(mapping):
    return lambda host: mapping.get(host, [])


@pytest.mark.parametrize(
    ("url", "addrs", "kw", "ok"),
    [
        ("https://mcp.example.com/mcp", ["93.184.216.34"], {}, True),
        ("http://mcp.example.com/mcp", ["93.184.216.34"], {}, False),  # plain http
        ("http://mcp.example.com/mcp", ["93.184.216.34"], {"allow_insecure_http": True}, False),  # only loopback
        ("https://mcp.example.com/mcp", ["169.254.169.254"], {"allow_private_network": True}, False),  # metadata
        ("https://mcp.internal/mcp", ["10.0.0.5"], {}, False),  # private, not allowed
        ("https://mcp.internal/mcp", ["10.0.0.5"], {"allow_private_network": True}, True),
        ("https://mcp.example.com/mcp", ["93.184.216.34", "127.0.0.1"], {}, False),  # one bad answer is enough
        ("https://user:pw@mcp.example.com/mcp", ["93.184.216.34"], {}, False),  # credentials in URL
        ("http://127.0.0.1:9/mcp", ["127.0.0.1"], {"allow_insecure_http": True}, True),  # local development
    ],
)
def test_destination_rules(url, addrs, kw, ok):
    cfg = McpServerConfig("x", url=url, **kw)
    host = url.split("//", 1)[1].split("/", 1)[0].split("@")[-1].split(":")[0]
    if ok:
        check_remote_url(cfg, _resolver({host: addrs}))
    else:
        with pytest.raises(McpDestinationDenied):
            check_remote_url(cfg, _resolver({host: addrs}))


def test_config_requires_exactly_one_transport():
    with pytest.raises(ValueError):
        McpServerConfig("x")
    with pytest.raises(ValueError):
        McpServerConfig("x", command="srv", url="https://a/mcp")
    with pytest.raises(ValueError):
        McpServerConfig("x", command="srv", oauth=McpOAuth("https://i", "c", "s"))


def test_servers_file_wires_remote_tools_and_keeps_secrets_out_of_the_file(remote, tmp_path, capsys):
    import yaml

    from aegistrace.cli.main import main as cli
    from aegistrace.mcpgw.config import load_servers, register_from_env
    from aegistrace.tools.registry import ToolRegistry

    auth, resource = remote
    digest = discover(_cfg(remote, "remote5"))[0].schema_digest
    doc = {
        "servers": [
            {
                "id": "notes",
                "url": resource,
                "allow_insecure_http": True,
                "oauth": {
                    "issuer": auth.issuer,
                    "client_id": "aegis-client",
                    "client_secret_env": "NOTES_MCP_SECRET",
                    "scope": "notes:read",
                },
                "tools": {"read_notes": {"risk_class": 1, "schema_digest": digest, "retry_safe": True}},
            }
        ]
    }
    path = tmp_path / "mcp.yaml"
    path.write_text(yaml.safe_dump(doc))
    assert SECRET not in path.read_text()
    with pytest.raises(ValueError, match="NOTES_MCP_SECRET"):
        load_servers(str(path), {})
    env = {"AEGIS_MCP_SERVERS_FILE": str(path), "NOTES_MCP_SECRET": SECRET}
    reg = ToolRegistry()
    assert register_from_env(reg, env)["notes"]["registered"] == ["read_notes"]
    assert reg.get("mcp.notes.read_notes") is not None

    import os

    os.environ["NOTES_MCP_SECRET"] = SECRET
    try:
        assert cli(["mcp", "discover", "notes", "--config", str(path)]) == 0
    finally:
        del os.environ["NOTES_MCP_SECRET"]
    out = capsys.readouterr().out
    assert f"read_notes\t{digest}\tpinned" in out


def test_unreachable_server_is_reported_not_fatal(tmp_path):
    import yaml

    from aegistrace.mcpgw.config import register_from_env
    from aegistrace.tools.registry import ToolRegistry

    path = tmp_path / "mcp.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "servers": [
                    {"id": "down", "url": "http://127.0.0.1:9/mcp", "allow_insecure_http": True, "timeout_seconds": 2}
                ]
            }
        )
    )
    reg = ToolRegistry()
    assert "error" in register_from_env(reg, {"AEGIS_MCP_SERVERS_FILE": str(path)})["down"]
    assert reg.describe() == []
