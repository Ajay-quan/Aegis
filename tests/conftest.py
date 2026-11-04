# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any

import pytest

from aegistrace.evidence.bundle import write_bundle
from aegistrace.evidence.checkpoint import CheckpointBody, sign_checkpoint
from aegistrace.evidence.events import ChainBuilder, artifact_digest
from aegistrace.evidence.signing import LocalEd25519Signer, b64
from aegistrace.evidence.trust import TrustStore

TENANT, RUN = "tnt_alpha", "run_001"


def trust_doc(*signers: LocalEd25519Signer, **overrides: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "keys": [
            {
                "key_id": s.key_id,
                "public_key": b64(s.public_key_raw()),
                "not_before": "2026-01-01T00:00:00Z",
                **overrides,
            }
            for s in signers
        ],
    }


@dataclass
class Fixture:
    signer: LocalEd25519Signer
    trust: TrustStore
    chain: ChainBuilder
    artifact: bytes
    bundle: bytes


def build_run(signer: LocalEd25519Signer | None = None, n_tool_events: int = 3) -> Fixture:
    signer = signer or LocalEd25519Signer()
    chain = ChainBuilder(TENANT, "prj_1", RUN)
    artifact = b"quarterly report contents"
    ad = artifact_digest(artifact)
    chain.append(
        event_id="ev_1",
        event_type="run.created",
        actor_id="usr_1",
        correlation_id=RUN,
        timestamp="2026-10-31T10:00:00Z",
        payload={"task": "report"},
    )
    for i in range(n_tool_events):
        chain.append(
            event_id=f"ev_t{i}",
            event_type="tool.executed",
            actor_id="agt_1",
            correlation_id=RUN,
            timestamp=f"2026-10-31T10:00:0{i + 1}Z",
            payload={"tool": "docs.read", "doc": f"d{i}"},
        )
    chain.append(
        event_id="ev_out",
        event_type="artifact.created",
        actor_id="agt_1",
        correlation_id=RUN,
        timestamp="2026-10-31T10:01:00Z",
        payload={"artifact_digest": ad, "name": "report.txt"},
    )
    cp = sign_checkpoint(
        CheckpointBody(TENANT, RUN, 1, len(chain.events), chain.head, signer.key_id, "2026-10-31T10:02:00Z"),
        signer,
    )
    bundle = write_bundle(TENANT, RUN, chain.events, [cp], {ad: artifact})
    return Fixture(signer, TrustStore.from_json(trust_doc(signer)), chain, artifact, bundle)


@pytest.fixture
def run() -> Fixture:
    return build_run()


def unpack(bundle: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(bundle)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def repack(files: dict[str, bytes], fix_manifest: bool = True) -> bytes:
    """Rebuild a zip, optionally recomputing manifest digests the way an
    attacker who controls the bundle would."""
    import hashlib

    if fix_manifest:
        m = json.loads(files["manifest.json"])
        m["files"] = [
            {"path": p, "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}
            for p, b in sorted(files.items())
            if p != "manifest.json"
        ]
        files = {**files, "manifest.json": json.dumps(m).encode()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, b in files.items():
            zf.writestr(n, b)
    return buf.getvalue()


def edit_events(bundle: bytes, fn: Any) -> bytes:
    files = unpack(bundle)
    lines = [json.loads(x) for x in files["events.jsonl"].splitlines()]
    lines = fn(lines)
    files["events.jsonl"] = b"".join(json.dumps(x).encode() + b"\n" for x in lines)
    return repack(files)
