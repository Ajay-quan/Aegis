# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Run worker: consumes run.execute messages, claims a lease, runs the agent.

Messages are acknowledged only after the run step's outcome has committed.
Messages left pending by a crashed consumer are reclaimed with XAUTOCLAIM;
the DB lease/fencing logic makes reprocessing safe. Messages that keep
failing are moved to a dead-letter stream (poison-message handling).
"""

from __future__ import annotations

import logging
import secrets
import socket
from datetime import timedelta
from typing import Any

import redis
from sqlalchemy import Engine

from aegistrace.agents.runner import ModelFactory, run_agent
from aegistrace.evidence.anchor import Anchor
from aegistrace.evidence.signing import Signer
from aegistrace.observability import ANCHOR_FAILURES
from aegistrace.orchestration import leases
from aegistrace.orchestration.service import checkpoint
from aegistrace.persistence.db import InvalidTenant, tenant_tx
from aegistrace.tools.gateway import ToolGateway
from aegistrace.tools.registry import ToolRegistry

from .dispatcher import STREAM

log = logging.getLogger(__name__)

GROUP = "aegis-workers"
DEAD_LETTER = "aegis:runs:dead"
MAX_DELIVERIES = 5


class Worker:
    def __init__(
        self,
        engine: Engine,
        r: Any,
        gateway: ToolGateway,
        registry: ToolRegistry,
        model_factory: ModelFactory,
        lease_ttl: timedelta = timedelta(seconds=30),
        worker_id: str | None = None,
        signer: Signer | None = None,
        anchor: Anchor | None = None,
    ) -> None:
        self.signer = signer
        self.anchor = anchor
        self.engine = engine
        self.redis: Any = r  # redis-py's typing does not model decode_responses=True
        self.gateway = gateway
        self.registry = registry
        self.model_factory = model_factory
        self.ttl = lease_ttl
        self.id = worker_id or f"wrk_{socket.gethostname()[:20]}_{secrets.token_hex(4)}"
        try:
            r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def handle(self, fields: dict[str, str]) -> None:
        if fields.get("topic") != "run.execute":
            return
        tenant_id, run_id = fields["tenant_id"], fields["run_id"]
        with tenant_tx(self.engine, tenant_id) as c:
            lease = leases.claim(c, run_id, self.id, self.ttl)
        if lease is None:
            return  # duplicate delivery or run no longer queued
        run_agent(self.engine, tenant_id, lease, self.model_factory, self.gateway, self.registry, self.ttl, self.id)
        self.seal(tenant_id, run_id)

    def seal(self, tenant_id: str, run_id: str) -> None:
        """Sign a checkpoint at every resting point and publish it to the anchor."""
        if self.signer is None:
            return
        with tenant_tx(self.engine, tenant_id) as c:
            cp = checkpoint(c, run_id, self.signer)
        if self.anchor is not None:
            try:
                self.anchor.publish(cp)
            except OSError:
                ANCHOR_FAILURES.inc()
                log.exception("checkpoint anchoring failed", extra={"run_id": run_id})

    def _process(self, msg_id: str, fields: dict[str, str]) -> None:
        try:
            self.handle(fields)
        except (InvalidTenant, KeyError):
            self.redis.xadd(DEAD_LETTER, {**fields, "error": "malformed"})
        except Exception:
            log.exception("run processing failed", extra={"msg_id": msg_id})
            return  # leave pending; reclaimed later, DB recovery handles the run
        self.redis.xack(STREAM, GROUP, msg_id)

    def poll_once(self, block_ms: int = 1000, count: int = 10, reclaim_idle_ms: int = 60_000) -> int:
        handled = 0
        _, claimed, _ = self.redis.xautoclaim(STREAM, GROUP, self.id, min_idle_time=reclaim_idle_ms, count=count)
        for msg_id, fields in claimed:
            info = self.redis.xpending_range(STREAM, GROUP, min=msg_id, max=msg_id, count=1)
            if info and info[0]["times_delivered"] > MAX_DELIVERIES:
                self.redis.xadd(DEAD_LETTER, {**fields, "error": "max_deliveries"})
                self.redis.xack(STREAM, GROUP, msg_id)
                continue
            self._process(msg_id, fields)
            handled += 1
        resp = self.redis.xreadgroup(GROUP, self.id, {STREAM: ">"}, count=count, block=block_ms)
        for _stream, msgs in resp or []:
            for msg_id, fields in msgs:
                self._process(msg_id, fields)
                handled += 1
        return handled

    def maintenance(self) -> None:
        leases.recover_expired(self.engine)
        leases.requeue_due_retries(self.engine)
        leases.expire_overdue(self.engine)
