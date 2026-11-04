# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aegis_api.app import Deps, create_app
from aegisguard.identity.devissuer import AUDIENCE, ISSUER, DevIssuer
from aegisguard.identity.jwt import JwksCache, TokenValidator
from aegistrace.evidence.signing import LocalEd25519Signer
from tests.e2e.conftest import harness  # noqa: F401
from tests.integration.conftest import (  # noqa: F401
    app_engine,
    dispatcher_engine,
    make_tenant,
    other_tenant,
    owner_engine,
    tenant,
)

ALL_SCOPES = [
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


@pytest.fixture(scope="session")
def issuer() -> DevIssuer:
    return DevIssuer()


@pytest.fixture
def signer() -> LocalEd25519Signer:
    return LocalEd25519Signer()


@pytest.fixture
def client(app_engine, issuer, signer, harness) -> TestClient:
    validator = TokenValidator(ISSUER, AUDIENCE, JwksCache(issuer.jwks))
    app = create_app(Deps(app_engine, validator, signer, harness.redis, gateway=harness.worker.gateway))
    return TestClient(app, raise_server_exceptions=False)


def auth(
    issuer: DevIssuer, tenant_id: str, scopes: list[str] | None = None, sub: str = "usr_alice", **kw
) -> dict[str, str]:
    return {"Authorization": "Bearer " + issuer.mint(sub, tenant_id, ALL_SCOPES if scopes is None else scopes, **kw)}
