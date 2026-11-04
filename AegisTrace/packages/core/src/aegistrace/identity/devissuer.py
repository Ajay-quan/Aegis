# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Development-only token issuer standing in for a real OIDC provider.

Never enable in production: it mints tokens with a locally stored key. The
API only trusts it when its JWKS file is explicitly configured.
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from jwt.algorithms import OKPAlgorithm

ISSUER = "https://dev-issuer.aegistrace.local"
AUDIENCE = "aegistrace-api"


class DevIssuer:
    def __init__(
        self,
        key: Ed25519PrivateKey | None = None,
        kid: str | None = None,  # gitleaks:allow (type annotation)
        issuer: str = ISSUER,
        audience: str = AUDIENCE,
    ) -> None:
        self.key = key or Ed25519PrivateKey.generate()
        self.kid = kid or "dev-" + secrets.token_hex(4)
        self.issuer = issuer
        self.audience = audience

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(OKPAlgorithm.to_jwk(self.key.public_key()))
        return {"keys": [{**jwk, "kid": self.kid, "alg": "EdDSA", "use": "sig"}]}

    def mint(
        self, sub: str, tenant_id: str, scopes: list[str], ttl: int = 900, kind: str = "user", **overrides: Any
    ) -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": sub,
            "iat": now,
            "nbf": now,
            "exp": now + ttl,
            "jti": secrets.token_hex(12),
            "aegis_tenant": tenant_id,
            "scope": " ".join(scopes),
            "client_kind": kind,
            **overrides,
        }
        return jwt.encode(claims, self.key, algorithm="EdDSA", headers={"kid": self.kid})

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        pem = self.key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        (directory / "issuer-key.pem").write_bytes(pem)
        (directory / "issuer-key.pem").chmod(0o600)
        (directory / "jwks.json").write_text(json.dumps(self.jwks()))
        (directory / "kid").write_text(self.kid)

    @classmethod
    def load(cls, directory: Path) -> DevIssuer:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        key = load_pem_private_key((directory / "issuer-key.pem").read_bytes(), None)
        assert isinstance(key, Ed25519PrivateKey)
        return cls(key, (directory / "kid").read_text().strip())
