# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""Portable receipt bundle (zip) writer and bounded reader.

Layout:
  manifest.json        format/version, tenant/run binding, per-file sha256
  events.jsonl         one sealed event per line, ascending sequence
  checkpoints.json     list of signed checkpoints
  artifacts/<hex64>    artifact bytes, named by artifact digest
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

from .canonical import canonicalize
from .events import SealedEvent

FORMAT = "aegistrace.receipt"
FORMAT_VERSION = 1

ALLOWED_NAME = re.compile(r"\A(manifest\.json|events\.jsonl|checkpoints\.json|artifacts/[0-9a-f]{64})\Z")


@dataclass(frozen=True)
class Limits:
    max_entries: int = 10_000
    max_file_bytes: int = 64 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024
    max_compression_ratio: int = 200
    max_archive_bytes: int = 256 * 1024 * 1024


DEFAULT_LIMITS = Limits()


class BundleError(ValueError):
    """Bundle is structurally unsafe or malformed. Never partially trusted."""


@dataclass
class RawBundle:
    files: dict[str, bytes] = field(default_factory=dict)


def write_bundle(
    tenant_id: str,
    run_id: str,
    events: list[SealedEvent],
    checkpoints: list[dict[str, Any]],
    artifacts: dict[str, bytes] | None = None,
) -> bytes:
    """artifacts maps 'sha256:<hex>' artifact digests to content."""
    return write_bundle_records(tenant_id, run_id, [e.to_record() for e in events], checkpoints, artifacts)


def write_bundle_records(
    tenant_id: str,
    run_id: str,
    records: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    artifacts: dict[str, bytes] | None = None,
) -> bytes:
    files: dict[str, bytes] = {
        "events.jsonl": b"".join(canonicalize(r) + b"\n" for r in records),
        "checkpoints.json": canonicalize(checkpoints),
    }
    for digest, content in (artifacts or {}).items():
        files["artifacts/" + digest.removeprefix("sha256:")] = content
    manifest = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "tenant_id": tenant_id,
        "run_id": run_id,
        "files": [
            {"path": p, "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)} for p, b in sorted(files.items())
        ],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", canonicalize(manifest))
        for p, b in sorted(files.items()):
            zf.writestr(p, b)
    return buf.getvalue()


def read_bundle(data: bytes, limits: Limits = DEFAULT_LIMITS) -> RawBundle:
    if len(data) > limits.max_archive_bytes:
        raise BundleError("archive too large")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BundleError("not a valid zip archive") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > limits.max_entries:
            raise BundleError("too many entries")
        seen: set[str] = set()
        total = 0
        out = RawBundle()
        for info in infos:
            name = info.filename
            if not ALLOWED_NAME.match(name):
                raise BundleError(f"disallowed entry name: {name!r}")
            if name in seen:
                raise BundleError(f"duplicate entry: {name!r}")
            seen.add(name)
            if info.flag_bits & 0x1:
                raise BundleError("encrypted entries not supported")
            if info.file_size > limits.max_file_bytes:
                raise BundleError(f"entry too large: {name!r}")
            if info.compress_size and info.file_size / info.compress_size > limits.max_compression_ratio:
                raise BundleError(f"suspicious compression ratio: {name!r}")
            # Headers can lie; bound the actual decompressed read.
            with zf.open(info) as fh:
                content = fh.read(limits.max_file_bytes + 1)
            if len(content) > limits.max_file_bytes:
                raise BundleError(f"entry too large: {name!r}")
            total += len(content)
            if total > limits.max_total_bytes:
                raise BundleError("bundle too large when decompressed")
            out.files[name] = content
    if "manifest.json" not in out.files:
        raise BundleError("missing manifest.json")
    return out


def dump_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True)
