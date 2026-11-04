# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any

import pytest
import redis
from sqlalchemy import text

from aegistrace.agents.model import MockModel
from aegistrace.authorization.policy import OpaPolicyEngine
from aegistrace.orchestration.service import Actor, create_run
from aegistrace.persistence.db import tenant_tx
from aegistrace.tools.demo import DemoSink, build_registry
from aegistrace.tools.gateway import ToolGateway
from aegistrace.workers.dispatcher import dispatch_once
from aegistrace.workers.worker import Worker
from tests.integration.conftest import (  # noqa: F401 - fixtures
    TenantCtx,
    app_engine,
    dispatcher_engine,
    make_tenant,
    other_tenant,
    owner_engine,
    tenant,
)

OPA_URL = os.environ.get("AEGIS_OPA_URL", "http://127.0.0.1:58181")
REDIS_URL = os.environ.get("AEGIS_REDIS_URL", "redis://127.0.0.1:56379/1")


def fake_resolver(host: str) -> list[str]:
    return {"docs.example.com": ["93.184.216.34"], "rebind.example.com": ["169.254.169.254"]}.get(host, [])


@dataclass
class Harness:
    app_engine: Any
    dispatcher_engine: Any
    redis: Any
    sink: DemoSink
    worker: Worker
    policy: Any

    def grant(self, t: TenantCtx, tool: str, max_class: int, hosts: list[str] | None = None) -> None:
        with tenant_tx(self.app_engine, t.tenant_id) as c:
            c.execute(
                text(
                    "INSERT INTO tool_grants (tenant_id, agent_id, tool, max_risk_class, allowed_hosts, "
                    "granted_by) VALUES (:t, :a, :tool, :m, :h, 'usr_admin')"
                ),
                {"t": t.tenant_id, "a": t.agent_id, "tool": tool, "m": max_class, "h": hosts or []},
            )

    def submit(self, t: TenantCtx, script: list[dict[str, Any]], task: str = "demo") -> str:
        with tenant_tx(self.app_engine, t.tenant_id) as c:
            run_id, _ = create_run(
                c,
                t.tenant_id,
                t.agent_id,
                {"task": task, "mock_script": script},
                Actor("usr_alice", "user"),
                "k_" + secrets.token_hex(8),
            )
        return run_id

    def pump(self, rounds: int = 5) -> None:
        for _ in range(rounds):
            dispatch_once(self.dispatcher_engine, self.redis)
            self.worker.poll_once(block_ms=50)

    def state(self, t: TenantCtx, run_id: str) -> str:
        with tenant_tx(self.app_engine, t.tenant_id) as c:
            return c.execute(text("SELECT state FROM runs WHERE id=:r"), {"r": run_id}).scalar_one()

    def event_types(self, t: TenantCtx, run_id: str) -> list[str]:
        with tenant_tx(self.app_engine, t.tenant_id) as c:
            return list(
                c.execute(
                    text("SELECT event_type FROM events WHERE run_id=:r ORDER BY sequence_number"), {"r": run_id}
                ).scalars()
            )


@pytest.fixture
def harness(app_engine, dispatcher_engine) -> Harness:
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    r.ping()
    stream = "aegis:runs"
    r.delete(stream, "aegis:runs:dead")
    sink = DemoSink()
    registry = build_registry(sink, resolver=fake_resolver, fetch_hosts={"docs.example.com", "rebind.example.com"})
    policy = OpaPolicyEngine(OPA_URL)
    gateway = ToolGateway(app_engine, registry, policy)
    worker = Worker(
        app_engine,
        r,
        gateway,
        registry,
        lambda provider, model_id, run_input: MockModel(run_input.get("mock_script", [])),
        worker_id="wrk_test",
    )
    return Harness(app_engine, dispatcher_engine, r, sink, worker, policy)
