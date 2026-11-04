# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 AegisTrace contributors
"""`aegistrace` command-line interface.

Configuration: AEGIS_API_URL and AEGIS_TOKEN, or `aegistrace login`, which
stores them in ~/.config/aegistrace/config.json with mode 0600.

Exit codes: 0 ok, 1 operation/verification failed, 2 usage error,
3 authentication/permission, 4 not found, 5 conflict, 6 service unavailable.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from aegistrace_sdk import (
    AegisClient,
    AegisError,
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
)

CONFIG = Path(os.environ.get("AEGIS_CONFIG", Path.home() / ".config" / "aegistrace" / "config.json"))


def _config() -> dict[str, str]:
    cfg: dict[str, str] = {}
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text())
    url = os.environ.get("AEGIS_API_URL") or cfg.get("api_url")
    token = os.environ.get("AEGIS_TOKEN") or cfg.get("token")
    if not url or not token:
        raise SystemExit("not configured: run `aegistrace login` or set AEGIS_API_URL and AEGIS_TOKEN")
    return {"api_url": url, "token": token}


def _client() -> AegisClient:
    c = _config()
    return AegisClient(c["api_url"], c["token"])


def _out(args: argparse.Namespace, data: Any, human: str | None = None) -> None:
    if args.json or human is None:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(human)


def cmd_login(a: argparse.Namespace) -> int:
    token = a.token or sys.stdin.readline().strip()
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.touch(mode=0o600)
    CONFIG.chmod(0o600)
    CONFIG.write_text(json.dumps({"api_url": a.api_url, "token": token}))
    print(f"saved credentials to {CONFIG}")
    return 0


def cmd_agents(a: argparse.Namespace) -> int:
    with _client() as c:
        if a.action == "list":
            items = c.list_agents()
            _out(a, items, "\n".join(f"{i['id']}  {i['name']}  ({i['model_provider']})" for i in items) or "no agents")
        elif a.action == "register":
            res = c.register_agent(a.project, a.name, a.provider, a.model)
            _out(a, res, res["id"])
        elif a.action == "grant":
            res = c.grant_tool(a.agent, a.tool, a.max_class, a.host or [])
            _out(a, res, f"granted {a.tool} (class <= {a.max_class}) to {a.agent}")
    return 0


def cmd_runs(a: argparse.Namespace) -> int:
    with _client() as c:
        if a.action == "submit":
            payload = json.loads(Path(a.input).read_text()) if a.input else {}
            res = c.submit_run(a.agent, payload, a.idempotency_key)
            if a.wait:
                res = c.wait_for_run(res["id"], timeout=a.timeout)
            _out(a, res, f"{res['id']}  {res.get('state', 'submitted')}")
        elif a.action == "get":
            res = c.get_run(a.run)
            _out(a, res, f"{res['id']}  {res['state']}  events={res['last_sequence']}")
        elif a.action == "list":
            items = list(c.iter_runs(state=a.state))
            _out(a, items, "\n".join(f"{r['id']}  {r['state']}" for r in items) or "no runs")
        elif a.action == "events":
            items = c.events(a.run)
            _out(
                a,
                items,
                "\n".join(
                    f"#{e['sequence_number']:>4}  {e['timestamp']}  {e['event_type']:<28} {e['actor_id']}"
                    for e in items
                ),
            )
        elif a.action == "cancel":
            _out(a, c.cancel_run(a.run), "cancelled")
        elif a.action == "replay":
            res = c.replay(a.run)
            _out(
                a,
                res,
                f"state={res['reconstructed_state']['state']} matches_projection="
                f"{res['state_matches_projection']} decision_replay={res['decision_replay']['status']}",
            )
            return 0 if res["state_matches_projection"] and res["decision_replay"]["status"] == "IDENTICAL" else 1
    return 0


def cmd_receipt(a: argparse.Namespace) -> int:
    with _client() as c:
        data = c.export_receipt(a.run)
    out = Path(a.output or f"{a.run}.receipt.zip")
    out.write_bytes(data)
    _out(a, {"path": str(out), "bytes": len(data)}, f"wrote {out} ({len(data)} bytes)")
    return 0


def cmd_approvals(a: argparse.Namespace) -> int:
    with _client() as c:
        if a.action == "list":
            items = c.list_approvals(a.status)
            _out(
                a,
                items,
                "\n".join(
                    f"{i['id']}  run={i['run_id']}  {i['tool']}  class={i['risk_class']}  expires={i['expires_at']}"
                    for i in items
                )
                or "no approvals",
            )
        else:
            res = c.decide_approval(a.approval, a.action == "approve")
            _out(a, res, f"{a.approval}: {res['status']}")
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    from aegistrace.evidence.cli import main as verify_main

    argv = [a.bundle, "--trust", a.trust, "--tenant", a.tenant, "--run", a.run] + (["--json"] if a.json else [])
    return verify_main(argv)


def cmd_policy(a: argparse.Namespace) -> int:
    if a.action == "test":
        return cmd_policy_test(a)
    with _client() as c:
        if a.action == "export":
            text = c.export_rules_file()
            if a.output:
                Path(a.output).write_text(text)
                print(f"wrote {a.output}")
            else:
                print(text, end="")
            return 0
        if a.action == "show":
            r = c.get_rules()
            _out(
                a,
                r,
                f"preset: {r['preset'] or 'custom'} (version {r['version']})\n"
                + "\n".join(f"  {k}: {v}" for k, v in r["rules"].items()),
            )
            return 0
        res = c.apply_rules_file(Path(a.file).read_text(), dry_run=a.dry_run)
        verb = "would apply" if a.dry_run else "applied"
        _out(a, res, f"{verb} {len(res['changes'])} change(s)" + "".join(f"\n  - {x}" for x in res["changes"]))
    return 0


def cmd_insights(a: argparse.Namespace) -> int:
    with _client() as c:
        r = c.insights(a.range)
    if a.json:
        _out(a, r)
        return 0
    print(f"Verdict ({a.range}): {r['verdict'].upper()}")
    for line in r["working"]:
        print(f"  ok    {line}")
    for line in r["not_working"]:
        print(f"  issue {line}")
    print("Agents:")
    for ag in r["agents"]:
        print(f"  {ag['status']:<8} {ag['name']:<20} runs={ag['runs']:<5} blocked={ag['denied']:<5} {ag['reasons'][0]}")
    if r["recommendations"]:
        print("Recommendations:")
        for rec in r["recommendations"]:
            print(f"  [{rec['severity']}] {rec['title']}")
    return 1 if r["verdict"] == "concern" else 0


def cmd_policy_test(a: argparse.Namespace) -> int:
    policies = str(Path(a.path).resolve())
    if shutil.which("opa"):
        cmd = ["opa", "test", policies, "-v"]
    elif shutil.which("docker"):
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{policies}:/policies:ro",
            "openpolicyagent/opa:1.4.2",
            "test",
            "/policies",
            "-v",
        ]
    else:
        print("error: needs `opa` or `docker` on PATH", file=sys.stderr)
        return 2
    return subprocess.run(cmd, check=False).returncode  # noqa: S603


def cmd_doctor(a: argparse.Namespace) -> int:
    import httpx

    checks: dict[str, str] = {}
    try:
        cfg = _config()
        checks["config"] = "ok"
        r = httpx.get(cfg["api_url"].rstrip("/") + "/readyz", timeout=5)
        checks["api"] = "ok" if r.status_code == 200 else f"degraded: {r.json().get('checks')}"
        with _client() as c:
            c.list_agents()
        checks["auth"] = "ok"
    except SystemExit as exc:
        checks["config"] = str(exc)
    except httpx.HTTPError as exc:
        checks["api"] = f"unreachable: {type(exc).__name__}"
    except AegisError as exc:
        checks["auth"] = f"{exc.code}"
    _out(a, checks, "\n".join(f"{k:<8} {v}" for k, v in checks.items()))
    return 0 if all(v == "ok" for v in checks.values()) else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aegistrace", description="AegisTrace CLI")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("login", help="store API URL and token")
    s.add_argument("--api-url", required=True)
    s.add_argument("--token", help="access token (read from stdin if omitted)")
    s.set_defaults(fn=cmd_login)

    s = sub.add_parser("agents")
    s.set_defaults(fn=cmd_agents)
    asub = s.add_subparsers(dest="action", required=True)
    asub.add_parser("list")
    r = asub.add_parser("register")
    r.add_argument("--project", required=True)
    r.add_argument("--name", required=True)
    r.add_argument("--provider", default="mock")
    r.add_argument("--model", default="mock-deterministic-1")
    g = asub.add_parser("grant")
    g.add_argument("agent")
    g.add_argument("tool")
    g.add_argument("--max-class", type=int, required=True)
    g.add_argument("--host", action="append")

    s = sub.add_parser("runs")
    s.set_defaults(fn=cmd_runs)
    rsub = s.add_subparsers(dest="action", required=True)
    sm = rsub.add_parser("submit")
    sm.add_argument("--agent", required=True)
    sm.add_argument("--input", help="JSON file with run input")
    sm.add_argument("--idempotency-key")
    sm.add_argument("--wait", action="store_true")
    sm.add_argument("--timeout", type=float, default=60)
    for name in ("get", "events", "cancel", "replay"):
        rsub.add_parser(name).add_argument("run")
    ls = rsub.add_parser("list")
    ls.add_argument("--state")

    s = sub.add_parser("receipt", help="export a signed receipt bundle")
    s.add_argument("run")
    s.add_argument("-o", "--output")
    s.set_defaults(fn=cmd_receipt)

    s = sub.add_parser("verify", help="verify a receipt offline")
    s.add_argument("bundle")
    s.add_argument("--trust", required=True)
    s.add_argument("--tenant", required=True)
    s.add_argument("--run", required=True)
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("approvals")
    s.set_defaults(fn=cmd_approvals)
    psub = s.add_subparsers(dest="action", required=True)
    pl = psub.add_parser("list")
    pl.add_argument("--status", default="pending")
    psub.add_parser("approve").add_argument("approval")
    psub.add_parser("reject").add_argument("approval")

    s = sub.add_parser("policy", help="organization rules: show, export, apply a rules file, test Rego")
    s.set_defaults(fn=cmd_policy)
    psub2 = s.add_subparsers(dest="action", required=True)
    pt = psub2.add_parser("test")
    pt.add_argument("path", nargs="?", default="packages/aegisguard/policies")
    psub2.add_parser("show")
    pe = psub2.add_parser("export")
    pe.add_argument("-o", "--output")
    pa = psub2.add_parser("apply")
    pa.add_argument("file")
    pa.add_argument("--dry-run", action="store_true", help="show what would change without applying")

    s = sub.add_parser("insights", help="behavior report: verdict, agent scorecard, recommendations")
    s.add_argument("--range", choices=["24h", "7d", "30d"], default="7d")
    s.set_defaults(fn=cmd_insights)

    sub.add_parser("doctor", help="check configuration and connectivity").set_defaults(fn=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.fn(args))
    except (AuthenticationError, PermissionDeniedError) as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 3
    except NotFoundError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 4
    except ConflictError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 5
    except ServiceUnavailableError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 6
    except AegisError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
