# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Run untrusted code in an ephemeral, locked-down container.

Security boundary: a Linux container under the Docker default seccomp
profile with every capability dropped. This reduces risk substantially but is
NOT a complete defence against kernel or runtime escapes. For hostile
multi-tenant code, run this on dedicated sandbox hosts (never on API/worker
hosts, never with the host Docker socket inside a worker) and prefer a
microVM runtime (e.g. Firecracker via Kata, or gVisor) by setting `runtime`.
See docs/security/SANDBOX.md.
"""

from __future__ import annotations

import secrets
import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_IMAGE = "python:3.12.11-slim-bookworm"


@dataclass(frozen=True)
class SandboxLimits:
    timeout_seconds: float = 10.0
    memory: str = "128m"
    cpus: str = "0.5"
    pids: int = 64
    max_output_bytes: int = 64 * 1024
    max_file_bytes: int = 1024 * 1024
    tmpfs_size: str = "16m"


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool


class SandboxUnavailable(RuntimeError):
    pass


class DockerSandbox:
    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        limits: SandboxLimits = SandboxLimits(),  # noqa: B008
        runtime: str | None = None,
        docker: str | None = None,
    ) -> None:
        self.image = image
        self.limits = limits
        self.runtime = runtime
        self.docker = docker or shutil.which("docker")
        if not self.docker:
            raise SandboxUnavailable("docker CLI not found")

    def command(self, name: str) -> list[str]:
        lim = self.limits
        cmd = [
            self.docker or "docker",
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--network",
            "none",  # no egress, no metadata service, no LAN
            "--read-only",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={lim.tmpfs_size}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            str(lim.pids),
            "--memory",
            lim.memory,
            "--memory-swap",
            lim.memory,
            "--cpus",
            lim.cpus,
            "--ulimit",
            f"fsize={lim.max_file_bytes}",
            "--ulimit",
            "nofile=64:64",
            "--ulimit",
            "nproc=64:64",
            "--user",
            "65534:65534",
            "--workdir",
            "/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--log-driver",
            "none",
            "--stop-timeout",
            "1",
        ]
        if self.runtime:
            cmd += ["--runtime", self.runtime]
        return [*cmd, self.image, "python", "-I", "-S", "-"]

    def run_python(self, code: str) -> SandboxResult:
        if len(code.encode()) > 256 * 1024:
            raise ValueError("code too large")
        name = "aegis-sbx-" + secrets.token_hex(8)
        lim = self.limits
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, code goes to stdin, never to a shell
                self.command(name),
                input=code.encode(),
                capture_output=True,
                timeout=lim.timeout_seconds,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            subprocess.run([self.docker or "docker", "kill", name], capture_output=True, check=False)  # noqa: S603
            out = (exc.stdout or b"")[: lim.max_output_bytes]
            return SandboxResult(None, out.decode("utf-8", "replace"), "", True, False)
        truncated = len(proc.stdout) > lim.max_output_bytes or len(proc.stderr) > lim.max_output_bytes
        return SandboxResult(
            proc.returncode,
            proc.stdout[: lim.max_output_bytes].decode("utf-8", "replace"),
            proc.stderr[: lim.max_output_bytes].decode("utf-8", "replace"),
            False,
            truncated,
        )
