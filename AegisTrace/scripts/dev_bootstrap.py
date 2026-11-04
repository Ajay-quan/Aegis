# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Create development-only secrets in .dev/secrets (git-ignored):
an Ed25519 checkpoint signing key, a dev token issuer + JWKS, a verifier
trust store, then provision a demo tenant and print tokens.

Usage: uv run python scripts/dev_bootstrap.py [--tenant tnt_demo]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from aegistrace.evidence.signing import b64, load_local_signer
from aegistrace.identity.devissuer import DevIssuer
from aegistrace.persistence.admin import provision_tenant
from aegistrace.persistence.db import make_engine

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / ".dev" / "secrets"
OWNER_URL = os.environ.get(
    "AEGIS_OWNER_DATABASE_URL", "postgresql+psycopg://aegis_owner:dev-owner-password@127.0.0.1:55432/aegistrace"
)
USER_SCOPES = [
    "agents:read",
    "agents:write",
    "runs:read",
    "runs:write",
    "runs:reconcile",
    "policies:write",
    "receipts:export",
    "approvals:read",
    "approvals:decide",
    "replay:read",
    "replay:fork",
    "payloads:read",
    "audit:read",
]
AUDITOR_SCOPES = ["runs:read", "receipts:export", "replay:read", "audit:read"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="tnt_demo")
    ap.add_argument("--ttl", type=int, default=8 * 3600)
    args = ap.parse_args()

    SECRETS.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRETS.parent, 0o700)
    key_path = SECRETS / "signing-key.pem"
    if not key_path.exists():
        pem = Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        key_path.write_bytes(pem)
    # Compose containers (uid 10001) read this through a bind mount, so it is
    # world-readable locally; the API accepts that only with
    # AEGIS_DEV_ALLOW_SHARED_KEY_FILE=1 (set in compose.yaml, dev only).
    key_path.chmod(0o644)
    if (SECRETS / "issuer-key.pem").exists():
        issuer = DevIssuer.load(SECRETS)
    else:
        issuer = DevIssuer()
        issuer.save(SECRETS)
    (SECRETS / "jwks.json").chmod(0o644)

    signer = load_local_signer(str(key_path), allow_shared_file=True)
    trust = {
        "version": 1,
        "keys": [
            {"key_id": signer.key_id, "public_key": b64(signer.public_key_raw()), "not_before": "2026-01-01T00:00:00Z"}
        ],
    }
    (ROOT / ".dev" / "trust.json").write_text(json.dumps(trust, indent=2))

    provision_tenant(make_engine(OWNER_URL), args.tenant, args.tenant)
    tokens = {
        "user": issuer.mint("usr_dev_admin", args.tenant, USER_SCOPES, ttl=args.ttl),
        "auditor": issuer.mint("usr_dev_auditor", args.tenant, AUDITOR_SCOPES, ttl=args.ttl),
    }
    (ROOT / ".dev" / "tokens.json").write_text(json.dumps(tokens, indent=2))
    (ROOT / ".dev" / "tokens.json").chmod(0o600)
    print(f"tenant:       {args.tenant}")
    print(f"signing key:  {signer.key_id}")
    print(f"trust store:  {ROOT / '.dev' / 'trust.json'}")
    print(f"tokens:       {ROOT / '.dev' / 'tokens.json'} (dev only, expire in {args.ttl // 3600}h)")


if __name__ == "__main__":
    main()
