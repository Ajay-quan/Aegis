# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""Ed25519 signing behind a key-backend interface.

The local backend is for development only. A production backend must keep the
private key outside the application process (KMS/HSM); see docs/cryptography.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def key_id_for(public_key_raw: bytes) -> str:
    return "ed25519:" + hashlib.sha256(public_key_raw).hexdigest()[:32]


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(data: str) -> bytes:
    return base64.b64decode(data, validate=True)


class Signer(Protocol):
    @property
    def key_id(self) -> str: ...

    def public_key_raw(self) -> bytes: ...

    def sign(self, message: bytes) -> bytes: ...


class LocalEd25519Signer:
    """In-process key. Never log or serialize `_key`."""

    def __init__(self, private_key: Ed25519PrivateKey | None = None) -> None:  # gitleaks:allow (type annotation)
        self._key = private_key or Ed25519PrivateKey.generate()
        self._pub = self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    @property
    def key_id(self) -> str:
        return key_id_for(self._pub)

    def public_key_raw(self) -> bytes:
        return self._pub

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)

    def __repr__(self) -> str:
        return f"LocalEd25519Signer(key_id={self.key_id!r})"


def verify_signature(public_key_raw: bytes, signature: bytes, message: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_key_raw).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


def load_local_signer(path: str, allow_shared_file: bool = False) -> LocalEd25519Signer:
    """Development backend: PEM file readable only by the service user.

    allow_shared_file exists solely for local docker compose, where a host
    bind mount cannot be chowned to the container user. Never set it in a
    deployed environment.
    """
    import logging
    import os
    import stat

    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    mode = os.stat(path).st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        if not allow_shared_file:
            raise PermissionError(f"signing key {path} must not be group/world accessible")
        logging.getLogger(__name__).warning("DEV ONLY: signing key file is group/world readable")
    with open(path, "rb") as fh:
        key = load_pem_private_key(fh.read(), None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("signing key must be Ed25519")
    return LocalEd25519Signer(key)
