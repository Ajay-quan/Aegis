# Sandbox guarantees (`aegisguard.sandbox.docker_runner`)

## What runs where

- **API and workers never run untrusted code.** Their containers have no Docker socket, no privileges, a read-only root filesystem, and all capabilities dropped.
- **`code.run`** is registered only when a `DockerSandbox` is supplied, which is intended for **dedicated sandbox hosts**.

## Per-execution container settings

Each execution gets a fresh container:

| Control | Setting |
|---|---|
| Network | `--network none` (only `lo`; tests assert zero routes) |
| Filesystem | `--read-only` root; `/tmp` tmpfs 16 MiB with `noexec,nosuid,nodev` |
| Privileges | `--cap-drop ALL`, `no-new-privileges`, uid/gid 65534 |
| Syscalls | Docker default seccomp profile |
| Resources | Memory 128 MiB (no swap), 0.5 CPU, 64 PIDs, fsize 1 MiB, 64 open files |
| Time and output | 10 s wall clock (container killed), 64 KiB output cap |
| Environment | Only `PYTHONDONTWRITEBYTECODE`. Host secrets are not inherited. |
| Logging | `--log-driver none`; the container is removed after the run |

Verified by `tests/security/test_sandbox.py` (9 tests) on Docker Desktop 29.2.1 (linux/arm64 VM).

## What this does NOT guarantee

A Linux container shares the host kernel. Kernel or runtime vulnerabilities can allow escape. For genuinely hostile multi-tenant code:

1. Run sandbox hosts in a separate node pool or account with no credentials.
2. Use a microVM or user-space-kernel runtime: pass `runtime="kata-fc"` (Firecracker via Kata Containers) or `runtime="runsc"` (gVisor). The flag exists, but it has **not been tested here**.
3. Keep the sandbox host's Docker socket off any shared host.
