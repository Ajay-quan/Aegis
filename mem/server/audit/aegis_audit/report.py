"""Markdown and JSON reports."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aegis_audit import __version__
from aegis_audit.checks import CheckResult

ICON = {"pass": "PASS", "fail": "FAIL", "skip": "SKIP", "error": "ERROR"}


def summarize(target: str, results: list[CheckResult]) -> dict[str, Any]:
    counts = {k: sum(r.verdict == k for r in results) for k in ICON}
    scored = [r for r in results if r.verdict in ("pass", "fail")]
    return {
        "tool": f"aegis-audit {__version__}",
        "target": target,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "score": f"{counts['pass']}/{len(scored)}" if scored else "n/a",
        "counts": counts,
        "critical_failures": [r.id for r in results if r.verdict == "fail" and r.severity == "critical"],
        "results": [r.to_dict() for r in results],
    }


def to_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# Memory integrity audit: `{summary['target']}`",
        "",
        f"Score **{summary['score']}**. Critical failures: "
        f"{', '.join(summary['critical_failures']) or 'none'}. ({summary['tool']}, {summary['generated_at']})",
        "",
        "| Check | Category | Severity | Verdict | Evidence |",
        "|---|---|---|---|---|",
    ]
    for r in summary["results"]:
        lines.append(f"| {r['id']} {r['title']} | {r['category']} | {r['severity']} | "
                     f"**{ICON[r['verdict']]}** | {r['evidence']} |")
    lines += ["", "Checks run with isolated, run-scoped user ids and clean up after themselves.",
              "A SKIP means the target does not support the operation; it is never counted as a pass."]
    return "\n".join(lines)
