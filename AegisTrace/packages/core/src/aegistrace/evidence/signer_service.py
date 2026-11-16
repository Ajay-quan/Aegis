# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""Dedicated signing service: the only process that holds checkpoint signing keys.

The API and workers sign through `RemoteSigner` over a Unix socket, so a
compromise of an internet-facing process does not expose a private key. The
service signs checkpoint bodies only (domain-separated input); it refuses any
other message, so it cannot be used as a general-purpose signing oracle.

Keys live in a key ring directory (`<id>.pem`, mode 0600) with exactly one
active key. Rotation adds a new active key and retires the old one; a retired
key keeps signing for a short grace period so checkpoints already in flight
complete. Verifiers learn about keys through the trust store this service
exports (`trust-store`), with each key's validity window.

Production: run this service on an isolated host or replace `KeyRing` with an
HSM/KMS backend that supports Ed25519 (verify support first; see
docs/operations/SIGNING_KEYS.md). The wire protocol stays the same.

  aegistrace-signer init --keys DIR [--import key.pem]
  aegistrace-signer rotate --keys DIR
  aegistrace-signer trust-store --keys DIR [-o trust.json]
  aegistrace-signer serve --keys DIR --socket /run/aegis-signer/signer.sock
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)
from pydantic import BaseModel

from .checkpoint import CHECKPOINT_DOMAIN
from .signing import b64, key_id_for, unb64, verify_signature

GRACE = timedelta(minutes=5)  # a retired key may still sign this long (in-flight checkpoints)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RingKey:
    key_id: str
    private: Ed25519PrivateKey
    public_raw: bytes
    created_at: datetime
    retired_at: datetime | None


class KeyRing:
    """Directory-backed key ring. State: <hex>.pem per key, ring.json (active id, timestamps)."""

    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self._lock = threading.Lock()

    def _meta(self) -> dict[str, Any]:
        path = self.dir / "ring.json"
        meta: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {"active": None, "keys": {}}
        return meta

    def _save_meta(self, meta: dict[str, Any]) -> None:
        tmp = self.dir / "ring.json.tmp"
        tmp.write_text(json.dumps(meta, indent=2))
        tmp.replace(self.dir / "ring.json")

    def _add(self, key: Ed25519PrivateKey, meta: dict[str, Any]) -> str:
        pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        kid = key_id_for(pub)
        path = self.dir / (kid.split(":", 1)[1] + ".pem")
        path.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
        path.chmod(0o600)
        meta["keys"][kid] = {"created_at": _iso(_now()), "retired_at": None}
        return kid

    def init(self, import_pem: Path | None = None) -> str:
        """Create the ring with one active key (optionally importing an existing key so old receipts stay valid)."""
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            os.chmod(self.dir, 0o700)
            meta = self._meta()
            if meta["active"]:
                return str(meta["active"])
            key = Ed25519PrivateKey.generate()
            if import_pem is not None:
                loaded = load_pem_private_key(import_pem.read_bytes(), None)
                if not isinstance(loaded, Ed25519PrivateKey):
                    raise ValueError("imported key is not Ed25519")
                key = loaded
            meta["active"] = self._add(key, meta)
            if import_pem is not None:
                meta["keys"][meta["active"]]["created_at"] = "2026-01-01T00:00:00Z"  # it signed before the ring existed
            self._save_meta(meta)
            return str(meta["active"])

    def rotate(self) -> tuple[str, str]:
        with self._lock:
            meta = self._meta()
            old = meta["active"]
            if not old:
                raise RuntimeError("key ring not initialized")
            new = self._add(Ed25519PrivateKey.generate(), meta)
            meta["keys"][old]["retired_at"] = _iso(_now())
            meta["active"] = new
            self._save_meta(meta)
            return old, new

    def all_keys(self) -> list[RingKey]:
        meta = self._meta()
        out = []
        for kid, info in meta["keys"].items():
            pem = (self.dir / (kid.split(":", 1)[1] + ".pem")).read_bytes()
            key = load_pem_private_key(pem, None)
            assert isinstance(key, Ed25519PrivateKey)
            retired = info.get("retired_at")
            out.append(
                RingKey(
                    kid,
                    key,
                    key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
                    datetime.fromisoformat(info["created_at"].replace("Z", "+00:00")),
                    datetime.fromisoformat(retired.replace("Z", "+00:00")) if retired else None,
                )
            )
        return out

    def active_id(self) -> str:
        active = self._meta()["active"]
        if not active:
            raise RuntimeError("key ring not initialized")
        return str(active)

    def trust_store(self) -> dict[str, Any]:
        """Trust store for verifiers: every key with its validity window (retired keys end after the grace)."""
        entries = []
        for k in sorted(self.all_keys(), key=lambda k: k.created_at):
            e: dict[str, Any] = {"key_id": k.key_id, "public_key": b64(k.public_raw), "not_before": _iso(k.created_at)}
            if k.retired_at is not None:
                e["not_after"] = _iso(k.retired_at + GRACE)
            entries.append(e)
        return {"version": 1, "keys": entries}


class SignRefused(Exception):
    pass


def sign_with(ring: KeyRing, key_id: str, message: bytes) -> bytes:
    if not message.startswith(CHECKPOINT_DOMAIN):
        raise SignRefused("only checkpoint bodies are signed")
    key = next((k for k in ring.all_keys() if k.key_id == key_id), None)
    if key is None:
        raise SignRefused("unknown key")
    if key.retired_at is not None and _now() > key.retired_at + GRACE:
        raise SignRefused("key retired")
    return key.private.sign(message)


class SignIn(BaseModel):  # module level: FastAPI must resolve it as the request body
    key_id: str
    message: str  # base64


def create_app(ring: KeyRing) -> Any:
    from fastapi import FastAPI, HTTPException

    app = FastAPI(title="AegisTrace signer", docs_url=None, redoc_url=None)

    @app.get("/keys")
    def keys() -> dict[str, Any]:
        active = ring.active_id()
        return {
            "active": active,
            "keys": [
                {
                    "key_id": k.key_id,
                    "public_key": b64(k.public_raw),
                    "created_at": _iso(k.created_at),
                    "retired_at": _iso(k.retired_at) if k.retired_at else None,
                }
                for k in ring.all_keys()
            ],
        }

    @app.post("/sign")
    def sign(body: SignIn) -> dict[str, str]:
        try:
            return {"signature": b64(sign_with(ring, body.key_id, unb64(body.message)))}
        except SignRefused as exc:
            raise HTTPException(403, str(exc)) from exc

    return app


class RemoteSigner:
    """Signer client for the signing service (implements the `Signer` protocol). Holds no private key."""

    REFRESH_SECONDS = 30.0

    def __init__(self, socket_path: str, timeout: float = 5.0) -> None:
        self._http = httpx.Client(
            transport=httpx.HTTPTransport(uds=socket_path), base_url="http://signer", timeout=timeout
        )
        self._loaded_at = 0.0
        self._active = ""
        self._pubs: dict[str, bytes] = {}
        self._refresh(force=True)

    def _refresh(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._loaded_at < self.REFRESH_SECONDS:
            return
        r = self._http.get("/keys")
        r.raise_for_status()
        doc = r.json()
        pubs = {k["key_id"]: unb64(k["public_key"]) for k in doc["keys"]}
        for kid, raw in pubs.items():
            if key_id_for(raw) != kid:
                raise RuntimeError("signer reported a key id that does not match its public key")
        self._pubs, self._active, self._loaded_at = pubs, doc["active"], time.monotonic()

    @property
    def key_id(self) -> str:
        self._refresh()
        return self._active

    def public_key_raw(self) -> bytes:
        return self._pubs[self.key_id]

    def sign(self, message: bytes) -> bytes:
        kid = self._active  # the key id the caller just put into the checkpoint body
        r = self._http.post("/sign", json={"key_id": kid, "message": b64(message)})
        r.raise_for_status()
        sig = unb64(r.json()["signature"])
        if not verify_signature(self._pubs[kid], sig, message):  # never trust the service blindly
            raise RuntimeError("signing service returned an invalid signature")
        return sig

    def __repr__(self) -> str:
        return f"RemoteSigner(key_id={self._active!r})"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aegistrace-signer")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("init", "rotate", "trust-store", "serve"):
        s = sub.add_parser(name)
        s.add_argument("--keys", required=True)
        if name == "init":
            s.add_argument("--import", dest="import_pem")
        if name == "trust-store":
            s.add_argument("-o", "--output")
        if name == "serve":
            s.add_argument("--socket", required=True)
    a = p.parse_args(argv)
    ring = KeyRing(a.keys)
    if a.cmd == "init":
        print(ring.init(Path(a.import_pem) if a.import_pem else None))
    elif a.cmd == "rotate":
        old, new = ring.rotate()
        print(f"retired {old}\nactive  {new}\nPublish the updated trust store to verifiers before {GRACE} passes.")
    elif a.cmd == "trust-store":
        doc = json.dumps(ring.trust_store(), indent=2)
        if a.output:
            Path(a.output).write_text(doc)
        else:
            print(doc)
    else:
        import uvicorn

        sock = Path(a.socket)
        sock.parent.mkdir(parents=True, exist_ok=True)
        sock.unlink(missing_ok=True)
        ring.active_id()  # fail fast if not initialized
        os.umask(0o007)  # socket usable by the service group only
        uvicorn.run(create_app(ring), uds=str(sock), log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def signer_from_env(env: dict[str, str] | None = None) -> Any:
    """AEGIS_SIGNER_SOCKET -> the signing service (key outside this process); otherwise the
    development key file AEGIS_SIGNING_KEY_FILE."""
    from .signing import load_local_signer

    e = os.environ if env is None else env
    if e.get("AEGIS_SIGNER_SOCKET"):
        return RemoteSigner(e["AEGIS_SIGNER_SOCKET"])
    return load_local_signer(
        e["AEGIS_SIGNING_KEY_FILE"], allow_shared_file=e.get("AEGIS_DEV_ALLOW_SHARED_KEY_FILE") == "1"
    )
