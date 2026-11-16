# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""Signed checkpoints over a contiguous range of a run's chain."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .canonical import canonicalize
from .events import PROTOCOL_VERSION
from .signing import Signer, b64

CHECKPOINT_DOMAIN = b"aegistrace.v1.checkpoint\x00"


@dataclass(frozen=True)
class CheckpointBody:
    tenant_id: str
    run_id: str
    first_sequence: int
    last_sequence: int
    final_event_hash: str
    key_id: str
    created_at: str
    protocol: str = PROTOCOL_VERSION

    def signing_input(self) -> bytes:
        return CHECKPOINT_DOMAIN + canonicalize(asdict(self))


def sign_checkpoint(body: CheckpointBody, signer: Signer) -> dict[str, Any]:
    if body.key_id != signer.key_id:
        raise ValueError("checkpoint key_id does not match signer")
    return {"body": asdict(body), "signature": b64(signer.sign(body.signing_input()))}
