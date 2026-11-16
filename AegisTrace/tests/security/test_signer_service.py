# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""Dedicated signing service: keys never enter the API/worker process, only
checkpoints are signed, rotation keeps old receipts valid, and verifiers get
validity windows through the exported trust store."""

from __future__ import annotations

import os
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

import aegistrace.evidence.signer_service as svc
from aegistrace.evidence.checkpoint import CHECKPOINT_DOMAIN, CheckpointBody, sign_checkpoint
from aegistrace.evidence.signer_service import KeyRing, RemoteSigner, SignRefused, sign_with
from aegistrace.evidence.signing import unb64, verify_signature
from aegistrace.evidence.trust import TrustStore
from tests.end_to_end.conftest import harness  # noqa: F401 - fixture
from tests.integration.conftest import (  # noqa: F401 - fixtures
    app_engine,
    dispatcher_engine,
    make_tenant,
    owner_engine,
    tenant,
)


@pytest.fixture
def ring(tmp_path):
    r = KeyRing(tmp_path / "keys")
    r.init()
    return r


@pytest.fixture
def remote(ring):
    # A short socket path: macOS limits Unix socket paths to ~104 bytes.
    d = tempfile.mkdtemp(prefix="sg", dir="/tmp")
    sock = os.path.join(d, "s.sock")
    server = uvicorn.Server(uvicorn.Config(svc.create_app(ring), uds=sock, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.02)
    yield ring, sock
    server.should_exit = True
    t.join(5)


def _body(key_id: str, seq: int = 1) -> CheckpointBody:
    return CheckpointBody(
        tenant_id="tnt_a",
        run_id="run_1",
        first_sequence=1,
        last_sequence=seq,
        final_event_hash="sha256:" + "0" * 64,
        key_id=key_id,
        created_at="2026-11-16T12:00:00Z",
    )


def test_remote_signer_signs_checkpoints_that_verify(remote):
    ring, sock = remote
    signer = RemoteSigner(sock)
    assert not hasattr(signer, "_key")  # the client holds no private key
    body = _body(signer.key_id)
    cp = sign_checkpoint(body, signer)
    trust = TrustStore.from_json(ring.trust_store())
    key = trust.get(signer.key_id)
    assert key is not None and signer.public_key_raw() == key.public_key_raw
    assert verify_signature(key.public_key_raw, unb64(cp["signature"]), body.signing_input())


def test_only_checkpoint_bodies_are_signed(ring, remote):
    _, sock = remote
    with pytest.raises(SignRefused):
        sign_with(ring, ring.active_id(), b"arbitrary payload, e.g. a JWT to forge")
    with httpx.Client(transport=httpx.HTTPTransport(uds=sock), base_url="http://signer") as c:
        r = c.post("/sign", json={"key_id": ring.active_id(), "message": "aGVsbG8="})
    assert r.status_code == 403


def test_rotation_keeps_old_receipts_valid_and_switches_new_ones(remote):
    ring, sock = remote
    signer = RemoteSigner(sock)
    old = signer.key_id
    before = sign_checkpoint(_body(old), signer)
    retired, new = ring.rotate()
    assert retired == old and new != old
    signer._refresh(force=True)
    assert signer.key_id == new
    after = sign_checkpoint(_body(new, 2), signer)
    store = ring.trust_store()
    by_id = {k["key_id"]: k for k in store["keys"]}
    assert "not_after" in by_id[old] and "not_after" not in by_id[new]  # old key: closed validity window
    trust = TrustStore.from_json(store)
    assert trust.get(old) and trust.get(new)
    assert before["body"]["key_id"] == old and after["body"]["key_id"] == new


def test_in_flight_checkpoint_survives_rotation_within_grace(ring):
    old = ring.active_id()
    ring.rotate()
    msg = CHECKPOINT_DOMAIN + b"{}"
    assert sign_with(ring, old, msg)  # retired seconds ago: still allowed


def test_retired_key_refuses_after_grace(ring, monkeypatch):
    old = ring.active_id()
    ring.rotate()
    real = svc._now
    monkeypatch.setattr(svc, "_now", lambda: real() + svc.GRACE + timedelta(seconds=1))
    with pytest.raises(SignRefused, match="retired"):
        sign_with(ring, old, CHECKPOINT_DOMAIN + b"{}")


def test_existing_key_can_be_imported_so_old_receipts_keep_verifying(tmp_path):
    key = Ed25519PrivateKey.generate()
    pem = tmp_path / "old.pem"
    pem.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    ring = KeyRing(tmp_path / "ring")
    kid = ring.init(pem)
    from aegistrace.evidence.signing import LocalEd25519Signer

    assert kid == LocalEd25519Signer(key).key_id
    assert ring.trust_store()["keys"][0]["not_before"] == "2026-01-01T00:00:00Z"


def test_key_files_are_private(ring):
    assert oct(Path(ring.dir).stat().st_mode & 0o777) == "0o700"
    for f in Path(ring.dir).glob("*.pem"):
        assert oct(f.stat().st_mode & 0o777) == "0o600"


def test_full_run_signed_through_the_service_verifies(remote, harness, tenant):
    from aegistrace.evidence.bundle import write_bundle_records
    from aegistrace.evidence.verifier import Status, verify_bundle
    from aegistrace.orchestration.service import checkpoint, load_events
    from aegistrace.persistence.db import tenant_tx

    ring, sock = remote
    h, t = harness, tenant
    h.grant(t, "calc.add", 0)
    run_id = h.submit(t, [{"tool": "calc.add", "args": {"a": 1, "b": 1}}, {"final": "2"}])
    h.pump()
    signer = RemoteSigner(sock)
    with tenant_tx(h.app_engine, t.tenant_id) as c:
        cp = checkpoint(c, run_id, signer)
        bundle = write_bundle_records(t.tenant_id, run_id, load_events(c, run_id), [cp], {})
    report = verify_bundle(bundle, TrustStore.from_json(ring.trust_store()), t.tenant_id, run_id)
    assert report.status is Status.VALID, report.as_dict()
