# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""INV-007: untrusted code runs with no network, no privileges, bounded resources.
Requires a local Docker daemon."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from aegisguard.sandbox.docker_runner import DockerSandbox, SandboxLimits

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "info"], capture_output=True, check=False).returncode != 0,
    reason="docker daemon not available",
)


@pytest.fixture(scope="module")
def sbx():
    return DockerSandbox(limits=SandboxLimits(timeout_seconds=15))


def run(sbx, code):
    return sbx.run_python(code)


def test_basic_execution(sbx):
    r = run(sbx, "print(6*7)")
    assert r.exit_code == 0 and r.stdout.strip() == "42"


def test_no_network_and_no_metadata(sbx):
    r = run(
        sbx,
        """
import socket
for host in [("169.254.169.254", 80), ("1.1.1.1", 443), ("10.0.0.1", 22)]:
    try:
        socket.create_connection(host, timeout=2); print("CONNECTED", host)
    except OSError as e:
        print("blocked")
print("routes", len(open('/proc/net/route').read().splitlines()) - 1)
""",
    )
    assert "CONNECTED" not in r.stdout and r.stdout.count("blocked") == 3
    # Only inert tunnel devices may exist besides lo; there must be no routes at all.
    assert "routes 0" in r.stdout


def test_unprivileged_no_capabilities(sbx):
    r = run(
        sbx,
        """
import os
print(os.getuid(), os.getgid())
print([l for l in open('/proc/self/status') if l.startswith(('CapEff', 'CapPrm', 'NoNewPrivs'))])
""",
    )
    assert r.stdout.startswith("65534 65534")
    assert "CapEff:\\t0000000000000000" in r.stdout and "NoNewPrivs:\\t1" in r.stdout


def test_read_only_root_and_noexec_tmp(sbx):
    r = run(
        sbx,
        """
import os, subprocess
for p in ['/etc/evil', '/usr/evil', '/evil']:
    try:
        open(p, 'w'); print('WROTE', p)
    except OSError:
        print('ro')
open('/tmp/x.sh', 'w').write('#!/bin/sh\\necho pwned')
os.chmod('/tmp/x.sh', 0o755)
try:
    subprocess.run(['/tmp/x.sh'], check=True); print('EXECUTED')
except (PermissionError, OSError, subprocess.CalledProcessError):
    print('noexec')
""",
    )
    assert "WROTE" not in r.stdout and "EXECUTED" not in r.stdout and "noexec" in r.stdout


def test_host_secrets_not_visible(sbx, monkeypatch):
    monkeypatch.setenv("AEGIS_SECRET", "s3cret")
    r = run(sbx, "import os; print(sorted(os.environ))")
    assert "AEGIS_SECRET" not in r.stdout and "s3cret" not in r.stdout
    r = run(sbx, "import os; print(os.path.exists('/var/run/docker.sock'), os.path.exists('/run/aegis'))")
    assert r.stdout.strip() == "False False"


def test_fork_bomb_is_contained(sbx):
    r = run(
        sbx,
        """
import os
n = 0
try:
    while True:
        if os.fork() == 0:
            import time; time.sleep(5); os._exit(0)
        n += 1
except OSError:
    print('limited at', n)
""",
    )
    assert "limited at" in r.stdout or r.timed_out
    assert int(r.stdout.split()[-1]) < 70 if "limited at" in r.stdout else True


def test_memory_limit(sbx):
    r = run(sbx, "x = bytearray(512 * 1024 * 1024); print('allocated')")
    assert "allocated" not in r.stdout and r.exit_code != 0


def test_timeout_enforced():
    s = DockerSandbox(limits=SandboxLimits(timeout_seconds=3))
    r = s.run_python("import time\nwhile True: time.sleep(1)")
    assert r.timed_out


def test_output_and_file_size_limits():
    s = DockerSandbox(limits=SandboxLimits(max_output_bytes=1000))
    r = s.run_python("print('A' * 100000)")
    assert r.truncated and len(r.stdout) <= 1000
    r = s.run_python("open('/tmp/big','wb').write(b'0' * 5_000_000)")
    assert r.exit_code != 0
