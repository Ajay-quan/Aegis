"""CLI:

    python -m aegis_audit --target naive
    python -m aegis_audit --target aegismem --url http://localhost:8000 --api-key aem_...
    python -m aegis_audit --target mem0 --url http://localhost:8888 --out report

Exit code 1 when any check fails (use in CI with --fail-on fail|critical|never).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from aegis_audit.checks import CHECKS, run_checks
from aegis_audit.report import summarize, to_markdown
from aegis_audit.targets import AegisMemTarget, Mem0LibraryTarget, Mem0Target, NaiveVectorTarget


def build_target(args: argparse.Namespace):
    if args.target == "naive":
        return NaiveVectorTarget()
    if args.target == "mem0-lib":
        if not args.mem0_config:
            raise SystemExit("--mem0-config <file.json> is required for mem0-lib")
        return Mem0LibraryTarget(json.loads(Path(args.mem0_config).read_text()))
    if not args.url:
        raise SystemExit("--url is required for this target")
    cls = {"aegismem": AegisMemTarget, "mem0": Mem0Target}[args.target]
    return cls(args.url, args.api_key)


async def main_async(args: argparse.Namespace) -> int:
    target = build_target(args)
    try:
        results = await run_checks(target, uuid.uuid4().hex[:8], set(args.checks) if args.checks else None)
    finally:
        await target.close()
    summary = summarize(target.name, results)
    md = to_markdown(summary)
    print(md)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "audit.json").write_text(json.dumps(summary, indent=2))
        (out / "audit.md").write_text(md)
    if args.fail_on == "never":
        return 0
    if args.fail_on == "critical":
        return 1 if summary["critical_failures"] else 0
    return 1 if summary["counts"]["fail"] or summary["counts"]["error"] else 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="aegis-audit", description="Integrity audit for agent memory")
    ap.add_argument("--target", required=True, choices=["aegismem", "mem0", "mem0-lib", "naive"])
    ap.add_argument("--mem0-config", help="Mem0 config JSON (vector_store, embedder, llm) for mem0-lib")
    ap.add_argument("--url")
    ap.add_argument("--api-key")
    ap.add_argument("--checks", nargs="*", choices=[c[0] for c in CHECKS])
    ap.add_argument("--out")
    ap.add_argument("--fail-on", choices=["fail", "critical", "never"], default="fail")
    sys.exit(asyncio.run(main_async(ap.parse_args())))


if __name__ == "__main__":
    main()
