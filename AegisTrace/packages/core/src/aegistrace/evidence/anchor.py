# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""External checkpoint anchoring.

An anchor is an append-only record of signed checkpoints held outside the
AegisTrace database. A verifier given an anchor learns which checkpoint to
expect for a run, which closes the tail-truncation gap: a bundle missing
events (or checkpoints) that the anchor has recorded fails verification.

FileAnchor appends JSON lines with O_APPEND and fsync. It is append-only by
convention only; production deployments must back it with storage that
enforces immutability (e.g. S3 Object Lock in compliance mode, or a
transparency log) under a different administrative domain than the database.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from .canonical import canonicalize, strict_loads

MAX_ANCHOR_BYTES = 256 * 1024 * 1024


class Anchor(Protocol):
    def publish(self, checkpoint: dict[str, Any]) -> None: ...


class FileAnchor:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def publish(self, checkpoint: dict[str, Any]) -> None:
        line = canonicalize(checkpoint) + b"\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)


def load_anchor(data: bytes) -> list[dict[str, Any]]:
    if len(data) > MAX_ANCHOR_BYTES:
        raise ValueError("anchor file too large")
    out = []
    for line in data.splitlines():
        if line.strip():
            rec = strict_loads(line)
            if not isinstance(rec, dict) or "body" not in rec or "signature" not in rec:
                raise ValueError("malformed anchor record")
            out.append(rec)
    return out
