# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Create development-only secrets in .dev/secrets (git-ignored):
an Ed25519 checkpoint signing key, a dev token issuer + JWKS, a verifier
trust store, then provision a demo tenant and print tokens.

Usage: uv run python scripts/dev_bootstrap.py [--tenant tnt_demo]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
from pathlib import Path

from sqlalchemy import text

from aegistrace.evidence.signer_service import KeyRing
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
    "data:erase",
    "keys:manage",
    "members:manage",
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
    key_path = SECRETS / "signing-key.pem"  # legacy location, imported into the key ring below
    # Pepper for API key hashes (AEGIS_API_KEY_PEPPER_FILE). Changing it invalidates every API key.
    pepper_path = SECRETS / "api-key-pepper"
    if not pepper_path.exists():
        pepper_path.write_text(secrets.token_urlsafe(32))
    pepper_path.chmod(0o644)  # read by the API container through the bind mount (dev only)
    # Development key-encryption key for payloads at rest (production: a KMS key).
    kek_path = SECRETS / "payload-kek"
    if not kek_path.exists():
        kek_path.write_text(base64.b64encode(secrets.token_bytes(32)).decode())
    kek_path.chmod(0o644)  # read by compose containers through the bind mount (dev only)
    # The dev identity provider's token-signing key is mounted only into the dev-idp service; the API
    # and workers get just the public JWKS.
    idp = ROOT / ".dev" / "idp"
    idp.mkdir(parents=True, exist_ok=True)
    for name in ("issuer-key.pem", "kid"):  # move from the old shared location
        if (SECRETS / name).exists() and not (idp / name).exists():
            (SECRETS / name).replace(idp / name)
    (SECRETS / "issuer-key.pem").unlink(missing_ok=True)
    if (idp / "issuer-key.pem").exists():
        issuer = DevIssuer.load(idp)
    else:
        issuer = DevIssuer()
        issuer.save(idp)
    (SECRETS / "jwks.json").write_text(json.dumps(issuer.jwks()))
    (SECRETS / "jwks.json").chmod(0o644)

    # Checkpoint signing keys live only in the signing service's key ring (.dev/signer). The first
    # run imports the earlier dev key so receipts signed before the ring existed keep verifying, then
    # removes it from .dev/secrets, which the API and workers mount.
    ring = KeyRing(ROOT / ".dev" / "signer")
    ring.init(key_path if key_path.exists() else None)
    key_path.unlink(missing_ok=True)
    trust = ring.trust_store()
    (ROOT / ".dev" / "trust.json").write_text(json.dumps(trust, indent=2))
    active = ring.active_id()

    owner_engine = make_engine(OWNER_URL)
    provision_tenant(owner_engine, args.tenant, args.tenant)
    # Dev users: the admin owns the organization, the auditor is a read-only viewer.
    with owner_engine.begin() as c:
        for subject, role in (("usr_dev_admin", "owner"), ("usr_dev_auditor", "viewer")):
            c.execute(
                text("INSERT INTO members (tenant_id, subject, role, added_by) VALUES (:t, :s, :r, 'bootstrap') "
                     "ON CONFLICT (tenant_id, subject) DO NOTHING"),
                {"t": args.tenant, "s": subject, "r": role},
            )
    tokens = {
        "user": issuer.mint("usr_dev_admin", args.tenant, USER_SCOPES, ttl=args.ttl),
        "auditor": issuer.mint("usr_dev_auditor", args.tenant, AUDITOR_SCOPES, ttl=args.ttl),
    }
    (ROOT / ".dev" / "tokens.json").write_text(json.dumps(tokens, indent=2))
    (ROOT / ".dev" / "tokens.json").chmod(0o600)
    print(f"tenant:       {args.tenant}")
    print(f"signing key:  {active} (held by the signing service)")
    print(f"trust store:  {ROOT / '.dev' / 'trust.json'}")
    print(f"tokens:       {ROOT / '.dev' / 'tokens.json'} (dev only, expire in {args.ttl // 3600}h)")


if __name__ == "__main__":
    main()
