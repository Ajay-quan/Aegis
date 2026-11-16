# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""The dev identity provider enforces the OIDC/PKCE rules a client could get
wrong, so the dashboard's sign-in is tested against a strict server."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from aegistrace.identity.devidp import Config, create_app
from aegistrace.identity.devissuer import AUDIENCE, ISSUER, DevIssuer
from aegistrace.identity.jwt import JwksCache, TokenValidator

CB = "http://localhost:3000/auth/callback"


@pytest.fixture
def issuer() -> DevIssuer:
    return DevIssuer()


@pytest.fixture
def idp(issuer) -> TestClient:
    cfg = Config(issuer, "http://idp.public", "dash", frozenset({CB}), "tnt_x")
    return TestClient(create_app(cfg), follow_redirects=False)


def pkce() -> tuple[str, str]:
    v = secrets.token_urlsafe(48)
    return v, base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()


def get_code(idp, challenge, sub="usr_dev_admin", state="s" * 16, redirect=CB, client="dash"):
    r = idp.post(
        "/authorize",
        data={"client_id": client, "redirect_uri": redirect, "state": state, "code_challenge": challenge, "sub": sub},
    )
    assert r.status_code == 303, r.text
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert r.headers["location"].startswith(CB + "?") and q["state"] == [state]
    return q["code"][0]


def exchange(idp, code, verifier, redirect=CB, client="dash"):
    return idp.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": client,
            "code_verifier": verifier,
        },
    )


def test_full_flow_yields_token_the_api_accepts(idp, issuer):
    d = idp.get("/.well-known/openid-configuration").json()
    assert d["authorization_endpoint"] == "http://idp.public/authorize"
    assert d["token_endpoint"] == "http://testserver/token"  # back channel follows the request
    v, ch = pkce()
    page = idp.get(
        "/authorize",
        params={
            "client_id": "dash",
            "redirect_uri": CB,
            "state": "s" * 16,
            "code_challenge": ch,
            "code_challenge_method": "S256",
            "response_type": "code",
        },
    )
    assert page.status_code == 200 and "usr_dev_admin" in page.text
    r = exchange(idp, get_code(idp, ch), v)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    claims = TokenValidator(ISSUER, AUDIENCE, JwksCache(issuer.jwks)).validate(r.json()["access_token"])
    assert claims.tenant_id == "tnt_x" and "payloads:read" in claims.scopes


def test_auditor_gets_read_only_scopes(idp, issuer):
    v, ch = pkce()
    tok = exchange(idp, get_code(idp, ch, sub="usr_dev_auditor"), v).json()["access_token"]
    scopes = TokenValidator(ISSUER, AUDIENCE, JwksCache(issuer.jwks)).validate(tok).scopes
    assert "runs:read" in scopes and "approvals:decide" not in scopes and "payloads:read" not in scopes


def test_code_is_single_use(idp):
    v, ch = pkce()
    code = get_code(idp, ch)
    assert exchange(idp, code, v).status_code == 200
    assert exchange(idp, code, v).json() == {"error": "invalid_grant"}


def test_wrong_verifier_burns_the_code(idp):
    v, ch = pkce()
    code = get_code(idp, ch)
    assert exchange(idp, code, pkce()[0]).status_code == 400
    assert exchange(idp, code, v).status_code == 400  # stolen code + later correct guess still fails


def test_redirect_and_client_must_match_the_code(idp):
    v, ch = pkce()
    assert exchange(idp, get_code(idp, ch), v, redirect=CB + "x").status_code == 400
    assert exchange(idp, get_code(idp, ch), v, client="other").status_code == 400


def test_unregistered_redirect_is_never_followed(idp):
    _, ch = pkce()
    for bad in ("https://evil.example/cb", CB + "/../x", CB + "?next=evil"):
        page = idp.get(
            "/authorize",
            params={
                "client_id": "dash",
                "redirect_uri": bad,
                "state": "s" * 16,
                "code_challenge": ch,
                "code_challenge_method": "S256",
            },
        )
        assert page.status_code == 400
        r = idp.post(
            "/authorize",
            data={
                "client_id": "dash",
                "redirect_uri": bad,
                "state": "s" * 16,
                "code_challenge": ch,
                "sub": "usr_dev_admin",
            },
        )
        assert r.status_code == 400 and "location" not in r.headers


def test_pkce_plain_and_unknown_users_rejected(idp):
    _, ch = pkce()
    plain = idp.get(
        "/authorize",
        params={
            "client_id": "dash",
            "redirect_uri": CB,
            "state": "s" * 16,
            "code_challenge": ch,
            "code_challenge_method": "plain",
        },
    )
    assert plain.status_code == 400
    r = idp.post(
        "/authorize",
        data={"client_id": "dash", "redirect_uri": CB, "state": "s" * 16, "code_challenge": ch, "sub": "usr_root"},
    )
    assert r.status_code == 400


def test_expired_code_rejected(idp, monkeypatch):
    import aegistrace.identity.devidp as m

    v, ch = pkce()
    code = get_code(idp, ch)
    real = m.time.time
    monkeypatch.setattr(m.time, "time", lambda: real() + m.CODE_TTL + 1)
    assert exchange(idp, code, v).status_code == 400


def test_state_html_is_escaped(idp):
    _, ch = pkce()
    page = idp.get(
        "/authorize",
        params={
            "client_id": "dash",
            "redirect_uri": CB,
            "state": '"><script>alert(1)</script>xx',
            "code_challenge": ch,
            "code_challenge_method": "S256",
        },
    )
    assert page.status_code == 200 and "<script>alert(1)" not in page.text
