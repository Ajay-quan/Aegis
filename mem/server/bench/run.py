"""aegis-bench runner.

    python -m bench.run                      # all suites, gate against thresholds.json
    python -m bench.run --suites revocation erasure --out bench-results

Writes <out>/latest.json and <out>/latest.md. Exit code 1 if any gate fails.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.suites import SUITES

THRESHOLDS = Path(__file__).parent / "thresholds.json"


def check(metrics: dict[str, Any], gates: dict[str, Any]) -> list[str]:
    failures = []
    for key, rule in gates.items():
        if key.startswith("_"):
            continue
        val = metrics.get(key)
        if val is None:
            failures.append(f"{key}: missing")
        elif "min" in rule and val < rule["min"]:
            failures.append(f"{key}={val} < min {rule['min']}")
        elif "max" in rule and val > rule["max"]:
            failures.append(f"{key}={val} > max {rule['max']}")
        elif "equals" in rule and val != rule["equals"]:
            failures.append(f"{key}={val} != {rule['equals']}")
    return failures


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


async def run(suites: list[str]) -> dict[str, Any]:
    gates = json.loads(THRESHOLDS.read_text())
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(), "python": platform.python_version(), "suites": {},
    }
    for name in suites:
        t = time.perf_counter()
        metrics = await SUITES[name]()
        failures = check(metrics, gates.get(name, {}))
        report["suites"][name] = {
            "metrics": metrics, "failures": failures, "passed": not failures,
            "seconds": round(time.perf_counter() - t, 2),
        }
    report["passed"] = all(s["passed"] for s in report["suites"].values())
    return report


def to_markdown(report: dict[str, Any]) -> str:
    lines = [f"# aegis-bench `{report['git_sha']}` - {'PASS' if report['passed'] else 'FAIL'}", ""]
    for name, s in report["suites"].items():
        lines.append(f"## {name} - {'pass' if s['passed'] else 'FAIL'} ({s['seconds']}s)")
        for k, v in s["metrics"].items():
            lines.append(f"- `{k}`: {v}")
        for f in s["failures"]:
            lines.append(f"- **GATE FAILED**: {f}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="aegis-bench")
    ap.add_argument("--suites", nargs="*", default=list(SUITES), choices=list(SUITES))
    ap.add_argument("--out", default="bench-results")
    args = ap.parse_args(argv)
    logging.disable(logging.WARNING)
    report = asyncio.run(run(args.suites))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_text(json.dumps(report, indent=2))
    (out / "latest.md").write_text(to_markdown(report))
    print(to_markdown(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
