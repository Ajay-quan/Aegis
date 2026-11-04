"""Signed erasure receipts.

A receipt proves *what* was erased *when*, and how it was verified, without retaining the
erased content. Each erased item is fingerprinted with a keyed HMAC, not a plain hash: a plain
hash of short personal data ("lives in Austin") can be brute-forced, while the keyed form
can only be checked by the operator holding the key (for example to answer "was this exact
text erased?" during an audit).

The receipt body is canonical JSON signed with HMAC-SHA256. Swap in asymmetric signing
(Ed25519) when third parties need to verify receipts without the server key.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def fingerprint(key: bytes, content: str) -> str:
    return hmac.new(key, content.encode("utf-8"), hashlib.sha256).hexdigest()


def _canonical(body: dict[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign(key: bytes, body: dict[str, Any]) -> str:
    return hmac.new(key, _canonical(body), hashlib.sha256).hexdigest()


def verify(key: bytes, body: dict[str, Any], signature: str) -> bool:
    return hmac.compare_digest(sign(key, body), signature)
