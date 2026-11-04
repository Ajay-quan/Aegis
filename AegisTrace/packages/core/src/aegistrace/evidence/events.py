# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""Execution event model and hash-chain construction (protocol v1)."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from .canonical import canonicalize

PROTOCOL_VERSION = "aegistrace.v1"
EVENT_DOMAIN = b"aegistrace.v1.event\x00"
PAYLOAD_DOMAIN = b"aegistrace.v1.payload\x00"
GENESIS_DOMAIN = b"aegistrace.v1.genesis\x00"
ARTIFACT_DOMAIN = b"aegistrace.v1.artifact\x00"

HASH_PREFIX = "sha256:"


def _digest(domain: bytes, data: bytes) -> str:
    return HASH_PREFIX + hashlib.sha256(domain + data).hexdigest()


def payload_digest(payload: Any) -> str:
    return _digest(PAYLOAD_DOMAIN, canonicalize(payload))


def artifact_digest(content: bytes) -> str:
    return _digest(ARTIFACT_DOMAIN, content)


def genesis_hash(tenant_id: str, run_id: str) -> str:
    """Per-run chain root. Binding tenant and run here means a chain cannot be
    transplanted into another run even if every event field were rewritten."""
    return _digest(
        GENESIS_DOMAIN,
        canonicalize({"protocol": PROTOCOL_VERSION, "tenant_id": tenant_id, "run_id": run_id}),
    )


@dataclass(frozen=True)
class Event:
    event_id: str
    tenant_id: str
    project_id: str
    run_id: str
    sequence_number: int
    event_type: str
    schema_version: int
    actor_id: str
    causation_id: str | None
    correlation_id: str
    timestamp: str
    payload_digest: str
    previous_event_hash: str
    protocol: str = PROTOCOL_VERSION

    def hashed_fields(self) -> dict[str, Any]:
        return asdict(self)

    def compute_hash(self) -> str:
        return _digest(EVENT_DOMAIN, canonicalize(self.hashed_fields()))


@dataclass(frozen=True)
class SealedEvent:
    event: Event
    current_event_hash: str
    payload: Any = None  # may be absent (redacted); digest still binds it

    def to_record(self) -> dict[str, Any]:
        rec = self.event.hashed_fields()
        rec["current_event_hash"] = self.current_event_hash
        if self.payload is not None:
            rec["payload"] = self.payload
        return rec


class ChainBuilder:
    """Appends events to a single run's chain. Used by the event store and by
    test/demo tooling; the verifier never uses it."""

    def __init__(self, tenant_id: str, project_id: str, run_id: str) -> None:
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.run_id = run_id
        self.events: list[SealedEvent] = []

    @property
    def head(self) -> str:
        if self.events:
            return self.events[-1].current_event_hash
        return genesis_hash(self.tenant_id, self.run_id)

    def append(
        self,
        *,
        event_id: str,
        event_type: str,
        actor_id: str,
        correlation_id: str,
        timestamp: str,
        payload: Any,
        causation_id: str | None = None,
        schema_version: int = 1,
    ) -> SealedEvent:
        ev = Event(
            event_id=event_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            run_id=self.run_id,
            sequence_number=len(self.events) + 1,
            event_type=event_type,
            schema_version=schema_version,
            actor_id=actor_id,
            causation_id=causation_id,
            correlation_id=correlation_id,
            timestamp=timestamp,
            payload_digest=payload_digest(payload),
            previous_event_hash=self.head,
        )
        sealed = SealedEvent(ev, ev.compute_hash(), payload)
        self.events.append(sealed)
        return sealed
