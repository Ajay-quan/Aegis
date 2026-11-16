# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Process entry points: `aegistrace-worker` and `aegistrace-dispatcher`."""

from __future__ import annotations

import logging
import os
import signal
import time
from typing import Any

import redis
from prometheus_client import start_http_server

from aegistrace.agents.model import MockModel, ModelAdapter, OpenAICompatibleModel
from aegistrace.api.logging import configure
from aegistrace.authorization.policy import OpaPolicyEngine
from aegistrace.observability import OUTBOX_LAG, QUEUE_DEPTH
from aegistrace.persistence.db import make_engine
from aegistrace.tools.demo import DemoSink, build_registry
from aegistrace.tools.gateway import ToolGateway

from .dispatcher import STREAM, dispatch_lag_seconds, dispatch_once
from .worker import GROUP, Worker

log = logging.getLogger("aegistrace.worker")
_stop = False


def _on_signal(*_: Any) -> None:
    global _stop
    _stop = True


def model_factory(provider: str, model_id: str, run_input: dict[str, Any]) -> ModelAdapter:
    if provider == "mock":
        return MockModel(run_input.get("mock_script", []))
    if provider == "openai-compatible":
        key = os.environ.get("AEGIS_OPENAI_API_KEY")
        if not key:
            raise RuntimeError("openai-compatible provider not configured")
        return OpenAICompatibleModel(os.environ["AEGIS_OPENAI_BASE_URL"], key, model_id)
    raise RuntimeError(f"unknown provider {provider}")


def worker_main() -> None:
    configure()
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    start_http_server(int(os.environ.get("AEGIS_METRICS_PORT", "9101")))
    engine = make_engine(os.environ["AEGIS_DATABASE_URL"])
    r = redis.Redis.from_url(os.environ["AEGIS_REDIS_URL"], decode_responses=True)
    hosts = {h for h in os.environ.get("AEGIS_FETCH_ALLOWED_HOSTS", "").split(",") if h}
    registry = build_registry(DemoSink(), fetch_hosts=hosts)
    gateway = ToolGateway(engine, registry, OpaPolicyEngine(os.environ["AEGIS_OPA_URL"]))
    from aegistrace.evidence.anchor import FileAnchor
    from aegistrace.evidence.signing import load_local_signer

    # Fail at startup, not mid-run, if evidence prerequisites are missing (INV-004).
    signer = load_local_signer(
        os.environ["AEGIS_SIGNING_KEY_FILE"], allow_shared_file=os.environ.get("AEGIS_DEV_ALLOW_SHARED_KEY_FILE") == "1"
    )
    anchor_path = os.environ.get("AEGIS_ANCHOR_FILE")
    worker = Worker(
        engine,
        r,
        gateway,
        registry,
        model_factory,
        signer=signer,
        anchor=FileAnchor(anchor_path) if anchor_path else None,
    )
    log.info("worker started", extra={"worker_id": worker.id})
    last_maint = 0.0
    while not _stop:
        try:
            worker.poll_once(block_ms=1000)
            if time.monotonic() - last_maint > 5:
                worker.maintenance()
                QUEUE_DEPTH.set(r.xpending(STREAM, GROUP)["pending"])
                last_maint = time.monotonic()
        except Exception:
            log.exception("worker loop error")
            time.sleep(1)
    log.info("worker stopped")


def dispatcher_main() -> None:
    configure()
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    start_http_server(int(os.environ.get("AEGIS_METRICS_PORT", "9102")))
    engine = make_engine(os.environ["AEGIS_DISPATCHER_DATABASE_URL"])
    r = redis.Redis.from_url(os.environ["AEGIS_REDIS_URL"], decode_responses=True)
    while not _stop:
        try:
            if dispatch_once(engine, r) == 0:
                time.sleep(0.2)
            OUTBOX_LAG.set(dispatch_lag_seconds(engine))
        except Exception:
            log.exception("dispatcher loop error")
            time.sleep(1)
