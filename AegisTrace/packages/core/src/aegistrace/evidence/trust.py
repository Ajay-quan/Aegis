# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""Verifier-side trust policy. A valid signature is not trust: the key must
also be listed here and be acceptable for the checkpoint's time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .signing import key_id_for, unb64


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return dt


@dataclass(frozen=True)
class TrustedKey:
    key_id: str
    public_key_raw: bytes
    tenant_ids: frozenset[str] | None  # None = any tenant
    not_before: datetime
    not_after: datetime | None
    revoked_at: datetime | None
    compromised: bool


class TrustStore:
    def __init__(self, keys: list[TrustedKey]) -> None:
        self._keys = {k.key_id: k for k in keys}

    @classmethod
    def from_json(cls, doc: dict[str, Any]) -> TrustStore:
        if doc.get("version") != 1:
            raise ValueError("unsupported trust store version")
        keys = []
        for entry in doc["keys"]:
            raw = unb64(entry["public_key"])
            if key_id_for(raw) != entry["key_id"]:
                raise ValueError(f"key_id mismatch for {entry['key_id']}")
            tenants = entry.get("tenant_ids")
            keys.append(
                TrustedKey(
                    key_id=entry["key_id"],
                    public_key_raw=raw,
                    tenant_ids=frozenset(tenants) if tenants is not None else None,
                    not_before=parse_time(entry["not_before"]),
                    not_after=parse_time(entry["not_after"]) if entry.get("not_after") else None,
                    revoked_at=parse_time(entry["revoked_at"]) if entry.get("revoked_at") else None,
                    compromised=bool(entry.get("compromised", False)),
                )
            )
        return cls(keys)

    def get(self, key_id: str) -> TrustedKey | None:
        return self._keys.get(key_id)

    def acceptance_problem(self, key: TrustedKey, tenant_id: str, created_at: str) -> str | None:
        """Return None if the key may vouch for this checkpoint, else a reason.

        created_at is asserted by the signer, so a compromised key could
        backdate it. Compromised keys are therefore rejected for all
        checkpoints unless a separate external anchor is verified (not yet
        implemented; see OPEN_ISSUES).
        """
        if key.compromised:
            return "signing key is marked compromised"
        if key.tenant_ids is not None and tenant_id not in key.tenant_ids:
            return "signing key not trusted for this tenant"
        try:
            ts = parse_time(created_at)
        except ValueError:
            return "invalid checkpoint timestamp"
        if ts < key.not_before or (key.not_after and ts > key.not_after):
            return "checkpoint outside key validity window"
        if key.revoked_at and ts >= key.revoked_at:
            return "checkpoint created after key revocation"
        return None
