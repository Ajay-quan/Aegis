"""Boots a real API server (Docker-free dev mode) and runs the TypeScript SDK suite against it."""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
TS = ROOT / "sdk" / "typescript"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (TS / "node_modules").exists(),
    reason="node and sdk/typescript/node_modules required (npm install in sdk/typescript)",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path):
    port = _free_port()
    env = {**os.environ, "APP_ENV": "development", "AUTH_ENABLED": "false",
           "MEMORY_BACKEND": "memory", "VECTOR_BACKEND": "memory", "GRAPH_BACKEND": "none",
           "CONTROL_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path}/control.db",
           "OUTBOX_WORKER_ENABLED": "false", "LOG_LEVEL": "WARNING"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "apps.api.main:app", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{url}/ready", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError(proc.stdout.read().decode() if proc.poll() is not None else "server not ready")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_typescript_sdk_end_to_end(live_server):
    r = subprocess.run(["node", "--experimental-strip-types", "--test", "test/client.test.ts"],
                       cwd=TS, env={**os.environ, "AEGIS_E2E_URL": live_server},
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "# skipped 0" in r.stdout and "# fail 0" in r.stdout
