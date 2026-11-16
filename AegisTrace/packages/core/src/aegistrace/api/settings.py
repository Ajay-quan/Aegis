# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    opa_url: str
    oidc_issuer: str
    oidc_audience: str
    oidc_jwks: str
    signing_key_file: str

    @classmethod
    def from_env(cls) -> Settings:
        def need(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"missing required setting {name}")
            return value

        return cls(
            database_url=need("AEGIS_DATABASE_URL"),
            redis_url=need("AEGIS_REDIS_URL"),
            opa_url=need("AEGIS_OPA_URL"),
            oidc_issuer=need("AEGIS_OIDC_ISSUER"),
            oidc_audience=need("AEGIS_OIDC_AUDIENCE"),
            oidc_jwks=need("AEGIS_OIDC_JWKS"),
            signing_key_file=need("AEGIS_SIGNING_KEY_FILE"),
        )
