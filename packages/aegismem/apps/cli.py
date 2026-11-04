"""AegisMem CLI: talk to a running AegisMem service from the terminal.

Uses the official SDK (``aegismem_client``); configure with AEGISMEM_BASE_URL / AEGISMEM_API_KEY.

    python -m apps.cli health
    python -m apps.cli ingest "Alice prefers Python and FAISS." --user alice --type fact
    python -m apps.cli recall "what does alice like?" --user alice
    python -m apps.cli feedback <retrieval_id> --user alice --used <memory_id> [<memory_id> ...]
    python -m apps.cli correct <memory_id> --user alice --kind outdated --text "Alice now prefers Rust"
    python -m apps.cli forget <memory_id> --user alice
    python -m apps.cli stats --user alice
    python -m apps.cli handoff --user alice --task "plan a trip"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sdk", "python"))

from aegismem_client import AegisMemError, AegisMemSync  # noqa: E402


def _print(obj: Any) -> None:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    print(json.dumps(obj, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="aegismem", description="AegisMem command-line client")
    ap.add_argument("--url", default=None, help="service base URL (default: $AEGISMEM_BASE_URL)")
    ap.add_argument("--api-key", default=None, help="API key (default: $AEGISMEM_API_KEY)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    sp = sub.add_parser("ingest")
    sp.add_argument("text")
    sp.add_argument("--user", required=True)
    sp.add_argument("--type", default="observation")
    sp.add_argument("--source", default="user_message")
    sp.add_argument("--origin")
    sp = sub.add_parser("recall")
    sp.add_argument("query")
    sp.add_argument("--user", required=True)
    sp.add_argument("--top-k", type=int, default=5)
    sp = sub.add_parser("feedback")
    sp.add_argument("retrieval_id")
    sp.add_argument("--user", required=True)
    sp.add_argument("--used", nargs="*", default=[])
    sp = sub.add_parser("correct")
    sp.add_argument("memory_id")
    sp.add_argument("--user", required=True)
    sp.add_argument("--kind", choices=["outdated", "wrong", "malicious"], required=True)
    sp.add_argument("--text", default="")
    sp = sub.add_parser("forget")
    sp.add_argument("memory_ids", nargs="+")
    sp.add_argument("--user", required=True)
    sp.add_argument("--reason", default="cli")
    sp = sub.add_parser("stats")
    sp.add_argument("--user", required=True)
    sp = sub.add_parser("handoff")
    sp.add_argument("--user", required=True)
    sp.add_argument("--task", default="")
    sp.add_argument("--budget", type=int, default=1200)
    return ap


def run(args: argparse.Namespace, client: AegisMemSync) -> Any:
    if args.cmd == "health":
        return client.health()
    if args.cmd == "ingest":
        return client.ingest(args.text, args.user, memory_type=args.type, source_type=args.source,
                             origin=args.origin)
    if args.cmd == "recall":
        return client.retrieve(args.query, args.user, top_k=args.top_k)
    if args.cmd == "feedback":
        return client.feedback(args.retrieval_id, args.user, args.used)
    if args.cmd == "correct":
        return client.correct(args.memory_id, args.user, args.kind, corrected_text=args.text)
    if args.cmd == "forget":
        return client.forget(args.user, memory_ids=args.memory_ids, reason=args.reason)
    if args.cmd == "stats":
        return client.stats(args.user)
    if args.cmd == "handoff":
        return client.handoff(args.user, task=args.task, token_budget=args.budget).markdown
    raise SystemExit(f"unknown command {args.cmd}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with AegisMemSync(args.url, args.api_key) as client:
        try:
            result = run(args, client)
        except AegisMemError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    print(result) if isinstance(result, str) else _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
