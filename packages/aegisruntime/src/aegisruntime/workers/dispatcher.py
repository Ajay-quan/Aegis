# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Transactional outbox dispatcher (runs as the aegis_dispatcher DB role).

Publishes committed outbox rows to Redis Streams. Delivery is at-least-once:
a crash between XADD and the status update re-publishes, so consumers must
be idempotent (run claims are: a second claim of a non-QUEUED run is a no-op).
"""

from __future__ import annotations

import json
import logging

import redis
from sqlalchemy import Engine, text

from aegistrace.observability import OUTBOX_DISPATCHED, OUTBOX_FAILURES

log = logging.getLogger(__name__)

STREAM = "aegis:runs"
MAX_ATTEMPTS = 10


def dispatch_once(engine: Engine, r: redis.Redis, batch: int = 100) -> int:
    sent = 0
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, tenant_id, run_id, topic, payload, attempts FROM outbox "
                "WHERE status = 'pending' AND available_at <= now() ORDER BY id LIMIT :n FOR UPDATE SKIP LOCKED"
            ),
            {"n": batch},
        ).all()
        for oid, tenant_id, run_id, topic, payload, attempts in rows:
            try:
                r.xadd(
                    STREAM,
                    {
                        "outbox_id": str(oid),
                        "tenant_id": tenant_id,
                        "run_id": run_id or "",
                        "topic": topic,
                        "payload": json.dumps(payload),
                    },
                )
            except redis.RedisError as exc:
                dead = attempts + 1 >= MAX_ATTEMPTS
                conn.execute(
                    text(
                        "UPDATE outbox SET attempts = attempts + 1, last_error = :e, "
                        "status = CASE WHEN :dead THEN 'dead' ELSE status END, "
                        "available_at = now() + make_interval(secs => least(300, power(2, attempts + 1))) "
                        "WHERE id = :id"
                    ),
                    {"e": type(exc).__name__, "dead": dead, "id": oid},
                )
                OUTBOX_FAILURES.inc()
                log.warning("outbox publish failed", extra={"outbox_id": oid, "dead": dead})
                continue
            conn.execute(
                text(
                    "UPDATE outbox SET status = 'dispatched', dispatched_at = now(), "
                    "attempts = attempts + 1 WHERE id = :id"
                ),
                {"id": oid},
            )
            sent += 1
    OUTBOX_DISPATCHED.inc(sent)
    return sent


def dispatch_lag_seconds(engine: Engine) -> float:
    with engine.begin() as conn:
        return float(
            conn.execute(
                text(
                    "SELECT COALESCE(EXTRACT(EPOCH FROM now() - min(created_at)), 0) "
                    "FROM outbox WHERE status = 'pending'"
                )
            ).scalar_one()
        )
