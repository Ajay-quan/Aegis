# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Envelope encryption of payload content at rest, with crypto-shredding.

What is encrypted: the content fields of event payloads (run input, model
responses, tool output, errors, results), the run's stored input and result,
and approval summaries (which carry the proposed arguments). What stays in
clear: control fields the platform itself queries (tool name, call key,
execution id, decisions, digests). Digests, event hashes and signatures are
always computed over the plaintext, so encryption changes nothing a verifier
checks.

Keys: one random 256-bit data key per run (AES-256-GCM), stored only wrapped
by the platform key-encryption key (a KMS key in production; `LocalKeyWrapper`
reads a 32-byte key file for development). Each ciphertext is bound to where
it lives (table, row, field) through associated data, so it cannot be moved.

Erasure: shredding a run's wrapped key makes all of its content unrecoverable.
Its evidence chain still verifies; payloads are then reported as withheld.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path
from typing import Any, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from sqlalchemy.engine import Connection

ENVELOPE = "$aegis_enc"
# `error` stays clear: it is only an exception class name (e.g. "EgressDenied"), used by operators and queries.
SENSITIVE_EVENT_FIELDS = frozenset({"input", "response", "output", "errors", "result"})


class Erased(Exception):
    """The content's key was shredded: it is permanently unreadable."""


class KeyWrapper(Protocol):
    key_id: str

    def wrap(self, dek: bytes, aad: bytes) -> bytes: ...
    def unwrap(self, blob: bytes, aad: bytes) -> bytes: ...


class LocalKeyWrapper:
    """Development key-encryption key from a 32-byte file. Production: a KMS-backed KeyWrapper."""

    def __init__(self, key: bytes, key_id: str) -> None:
        if len(key) != 32:
            raise ValueError("key-encryption key must be 32 bytes")
        self._aead = AESGCM(key)
        self.key_id = key_id

    @classmethod
    def from_file(cls, path: str) -> LocalKeyWrapper:
        raw = Path(path).read_bytes()
        key = base64.b64decode(raw) if len(raw) != 32 else raw
        return cls(key, "local:" + AESGCM.__name__.lower() + ":" + _fingerprint(key))

    def wrap(self, dek: bytes, aad: bytes) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._aead.encrypt(nonce, dek, aad)

    def unwrap(self, blob: bytes, aad: bytes) -> bytes:
        return self._aead.decrypt(blob[:12], blob[12:], aad)


def _fingerprint(key: bytes) -> str:
    from hashlib import sha256

    return sha256(b"aegistrace.kek\x00" + key).hexdigest()[:16]


_wrapper: KeyWrapper | None = None


def configure(wrapper: KeyWrapper | None) -> None:
    """Enable (or, with None, disable) payload encryption for this process."""
    global _wrapper
    _wrapper = wrapper


def configure_from_env(env: dict[str, str] | None = None) -> None:
    e = os.environ if env is None else env
    path = e.get("AEGIS_PAYLOAD_KEK_FILE")
    configure(LocalKeyWrapper.from_file(path) if path else None)


def enabled() -> bool:
    return _wrapper is not None


def _run_key(conn: Connection, tenant_id: str, run_id: str, create: bool) -> bytes:
    assert _wrapper is not None
    aad = f"aegistrace.dek\x00{tenant_id}\x00{run_id}".encode()
    row = conn.execute(
        text("SELECT wrapped, shredded_at FROM payload_keys WHERE run_id = :r"), {"r": run_id}
    ).one_or_none()
    if row is None:
        if not create:
            raise Erased(run_id)  # never had a key: nothing readable was stored encrypted for this run
        dek = AESGCM.generate_key(bit_length=256)
        conn.execute(
            text(
                "INSERT INTO payload_keys (run_id, tenant_id, kek_id, wrapped) VALUES (:r, :t, :k, :w) "
                "ON CONFLICT (run_id) DO NOTHING"
            ),
            {"r": run_id, "t": tenant_id, "k": _wrapper.key_id, "w": _wrapper.wrap(dek, aad)},
        )
        return _run_key(conn, tenant_id, run_id, create=False)  # read back: concurrent creators agree on one key
    if row[0] is None:
        raise Erased(run_id)
    return _wrapper.unwrap(bytes(row[0]), aad)


def _aad(where: str) -> bytes:
    return b"aegistrace.payload\x00" + where.encode()


def seal_value(conn: Connection, tenant_id: str, run_id: str, where: str, value: Any) -> Any:
    """Encrypt one JSON value. `where` names its location (e.g. "event:<id>:output"). No-op when disabled."""
    if _wrapper is None or value is None:
        return value
    dek = _run_key(conn, tenant_id, run_id, create=True)
    nonce = secrets.token_bytes(12)
    ct = AESGCM(dek).encrypt(nonce, json.dumps(value, separators=(",", ":"), sort_keys=True).encode(), _aad(where))
    return {ENVELOPE: 1, "n": base64.b64encode(nonce).decode(), "c": base64.b64encode(ct).decode()}


def is_sealed(value: Any) -> bool:
    return isinstance(value, dict) and ENVELOPE in value


def open_value(conn: Connection, tenant_id: str, run_id: str, where: str, value: Any) -> Any:
    """Decrypt a value sealed by seal_value; plaintext passes through. Raises Erased if shredded."""
    if not is_sealed(value):
        return value
    if _wrapper is None:
        raise RuntimeError("payload is encrypted but no key-encryption key is configured")
    dek = _run_key(conn, tenant_id, run_id, create=False)
    pt = AESGCM(dek).decrypt(base64.b64decode(value["n"]), base64.b64decode(value["c"]), _aad(where))
    return json.loads(pt)


def seal_event_payload(conn: Connection, tenant_id: str, run_id: str, event_id: str, payload: Any) -> Any:
    if _wrapper is None or not isinstance(payload, dict):
        return payload
    return {
        k: (seal_value(conn, tenant_id, run_id, f"event:{event_id}:{k}", v) if k in SENSITIVE_EVENT_FIELDS else v)
        for k, v in payload.items()
    }


def open_event_record(conn: Connection, record: dict[str, Any]) -> dict[str, Any]:
    """Decrypt a stored event record. If its run was erased, the payload is withheld (digest still binds it)."""
    payload = record.get("payload")
    if not isinstance(payload, dict) or not any(is_sealed(v) for v in payload.values()):
        return record
    t, r, e = record["tenant_id"], record["run_id"], record["event_id"]
    try:
        opened = {k: open_value(conn, t, r, f"event:{e}:{k}", v) for k, v in payload.items()}
    except Erased:
        return {k: v for k, v in record.items() if k != "payload"}
    return {**record, "payload": opened}
