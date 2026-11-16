# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""DNS-rebinding defence: each hop is resolved once, every answer is checked,
and the connection goes to the checked address while TLS still verifies the
real hostname."""

from __future__ import annotations

import datetime as dt
import http.server
import ssl
import threading

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from aegistrace.tools import egress
from aegistrace.tools.egress import EgressDenied, fetch

PUBLIC = "93.184.216.34"


class Rebinding:
    """First answer is public; every later lookup says 127.0.0.1 (the classic rebinding attack)."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, host: str) -> list[str]:
        self.calls += 1
        return [PUBLIC] if self.calls == 1 else ["127.0.0.1"]


def test_connection_goes_to_the_checked_address_not_a_second_lookup():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=b"ok")

    resolver = Rebinding()
    status, body = fetch(
        "https://docs.example.com/a?b=1",
        {"docs.example.com"},
        resolver,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert (status, body) == (200, b"ok")
    assert resolver.calls == 1  # one lookup per hop; nothing left for the attacker's second answer
    req = seen[0]
    assert req.url.host == PUBLIC and req.url.path == "/a" and req.url.query == b"b=1"
    assert req.headers["host"] == "docs.example.com"
    assert req.extensions["sni_hostname"] == "docs.example.com"  # TLS verifies the name, not the IP


def test_one_bad_answer_among_several_is_enough_to_refuse():
    with pytest.raises(EgressDenied):
        fetch(
            "https://docs.example.com/",
            {"docs.example.com"},
            lambda h: [PUBLIC, "169.254.169.254"],
            client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
        )


def test_redirect_hop_is_resolved_and_checked_again_by_name():
    hosts = {"docs.example.com": [PUBLIC], "evil.example.com": ["10.0.0.7"]}

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example.com/steal"})

    with pytest.raises(EgressDenied, match="10.0.0.7|not allowed|allowlisted"):
        fetch(
            "https://docs.example.com/",
            {"docs.example.com", "evil.example.com"},
            lambda h: hosts[h],
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )


def test_ipv6_addresses_are_bracketed():
    seen = []
    fetch(
        "https://docs.example.com:8443/x",
        {"docs.example.com"},
        lambda h: ["2606:2800:220:1:248:1893:25c8:1946"],
        client=httpx.Client(transport=httpx.MockTransport(lambda r: (seen.append(r), httpx.Response(200))[1])),
    )
    assert seen[0].url.host == "2606:2800:220:1:248:1893:25c8:1946" and seen[0].url.port == 8443
    assert seen[0].headers["host"] == "docs.example.com:8443"


# -- real TLS: certificate verification still uses the hostname -------------------------------


def _ca_and_leaf(tmp_path, name: str):
    now = dt.datetime.now(dt.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(1)
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(2)
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    (tmp_path / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (tmp_path / "leaf.pem").write_bytes(
        leaf.public_bytes(serialization.Encoding.PEM)
        + key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return tmp_path / "ca.pem", tmp_path / "leaf.pem"


@pytest.fixture
def https_server(tmp_path):
    servers = []

    def start(cert_name: str) -> tuple[int, ssl.SSLContext]:
        ca, leaf = _ca_and_leaf(tmp_path, cert_name)

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"host=" + self.headers["Host"].encode())

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(leaf)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        client_ctx = ssl.create_default_context(cafile=str(ca))
        return srv.server_address[1], client_ctx

    yield start
    for s in servers:
        s.shutdown()


def test_tls_verifies_the_hostname_over_a_pinned_ip(https_server, monkeypatch):
    monkeypatch.setattr(egress, "_check_ip", lambda ip: None)  # the test server is on loopback
    port, ctx = https_server("docs.test")
    status, body = fetch(
        f"https://docs.test:{port}/", {"docs.test"}, lambda h: ["127.0.0.1"], client=httpx.Client(verify=ctx)
    )
    assert status == 200 and body == f"host=docs.test:{port}".encode()


def test_tls_rejects_a_certificate_for_another_name(https_server, monkeypatch):
    monkeypatch.setattr(egress, "_check_ip", lambda ip: None)
    port, ctx = https_server("attacker.test")
    with pytest.raises(httpx.ConnectError):
        fetch(f"https://docs.test:{port}/", {"docs.test"}, lambda h: ["127.0.0.1"], client=httpx.Client(verify=ctx))
