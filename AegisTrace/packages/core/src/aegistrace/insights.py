# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Behavior insights: an explainable report on how agents and tools behaved.

Every classification is a fixed, documented rule over recorded data, so each
verdict comes with the exact numbers that produced it. Nothing here is an AI
judgment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sqlalchemy import Connection, text

Status = Literal["healthy", "watch", "concern", "idle"]

# Thresholds (documented in docs/product/INSIGHTS.md).
MIN_REQUESTS = 5  # below this, rates are too noisy to judge
DENY_CONCERN = 0.25  # >=25% of an agent's tool requests blocked
DENY_WATCH = 0.05
FAIL_CONCERN = 0.20  # >=20% of an agent's finished runs failed
FAIL_WATCH = 0.05
TOOL_FAIL_FLAG = 0.10  # a tool failing >=10% of executions


@dataclass
class AgentReport:
    agent_id: str
    name: str
    runs: int
    succeeded: int
    failed: int
    requests: int
    allowed: int
    denied: int
    approvals_requested: int
    approvals_rejected: int
    needs_review: int
    status: Status = "healthy"
    reasons: list[str] = field(default_factory=list)

    @property
    def deny_rate(self) -> float:
        return self.denied / self.requests if self.requests else 0.0

    @property
    def failure_rate(self) -> float:
        done = self.succeeded + self.failed
        return self.failed / done if done else 0.0


def classify(a: AgentReport) -> AgentReport:
    reasons: list[tuple[Status, str]] = []
    if a.runs == 0 and a.requests == 0:
        a.status, a.reasons = "idle", ["No activity in this period."]
        return a
    if a.requests >= MIN_REQUESTS:
        pct = f"{a.deny_rate:.0%} of its {a.requests} tool requests were blocked"
        if a.deny_rate >= DENY_CONCERN:
            reasons.append(("concern", f"{pct} — it keeps trying things it isn't allowed to do."))
        elif a.deny_rate >= DENY_WATCH:
            reasons.append(("watch", f"{pct}."))
    done = a.succeeded + a.failed
    if done >= MIN_REQUESTS:
        pct = f"{a.failure_rate:.0%} of its {done} finished runs failed"
        if a.failure_rate >= FAIL_CONCERN:
            reasons.append(("concern", f"{pct}."))
        elif a.failure_rate >= FAIL_WATCH:
            reasons.append(("watch", f"{pct}."))
    if a.approvals_rejected >= 2:
        reasons.append(("concern", f"Humans rejected {a.approvals_rejected} of its approval requests."))
    elif a.approvals_rejected == 1:
        reasons.append(("watch", "Humans rejected 1 of its approval requests."))
    if a.needs_review:
        reasons.append(("concern", f"{a.needs_review} run(s) have an external action with an unknown outcome."))
    rank = {"healthy": 0, "watch": 1, "concern": 2}
    a.status = max((s for s, _ in reasons), key=lambda s: rank[s], default="healthy")
    a.reasons = [r for _, r in reasons] or ["Runs succeed and it stays within its permissions."]
    return a


@dataclass
class Recommendation:
    severity: Literal["high", "medium", "low"]
    title: str
    detail: str
    href: str


def build_report(conn: Connection, span: str) -> dict[str, Any]:
    p = {"span": span}
    agents = {r[0]: r for r in conn.execute(text("SELECT id, name FROM agents ORDER BY created_at"))}
    runs = {
        r[0]: r[1:]
        for r in conn.execute(
            text(
                "SELECT agent_id, count(*), count(*) FILTER (WHERE state='SUCCEEDED'), "
                "count(*) FILTER (WHERE state IN ('FAILED','TIMED_OUT')), "
                "count(*) FILTER (WHERE state='NEEDS_RECONCILIATION') "
                "FROM runs WHERE updated_at > now() - CAST(:span AS interval) GROUP BY agent_id"
            ),
            p,
        )
    }
    dec = {
        r[0]: r[1:]
        for r in conn.execute(
            text(
                "SELECT principal, count(*), count(*) FILTER (WHERE decision='allow'), "
                "count(*) FILTER (WHERE decision='deny') "
                "FROM policy_decisions WHERE created_at > now() - CAST(:span AS interval) GROUP BY principal"
            ),
            p,
        )
    }
    apr = {
        r[0]: r[1:]
        for r in conn.execute(
            text(
                "SELECT agent_id, count(*), count(*) FILTER (WHERE status='rejected') FROM approvals "
                "WHERE requested_at > now() - CAST(:span AS interval) GROUP BY agent_id"
            ),
            p,
        )
    }

    reports = []
    for aid, (_, name) in agents.items():
        r = runs.get(aid, (0, 0, 0, 0))
        d = dec.get(aid, (0, 0, 0))
        ap = apr.get(aid, (0, 0))
        reports.append(classify(AgentReport(aid, name, r[0], r[1], r[2], d[0], d[1], d[2], ap[0], ap[1], r[3])))

    tools = [
        dict(row)
        for row in conn.execute(
            text(
                """
        SELECT d.tool,
               count(*) AS requests,
               count(*) FILTER (WHERE d.decision='allow') AS allowed,
               count(*) FILTER (WHERE d.decision='deny') AS denied,
               count(*) FILTER (WHERE d.decision='require_approval') AS approval,
               COALESCE(max(x.failed), 0) AS failed,
               COALESCE(max(x.executed), 0) AS executed
        FROM policy_decisions d
        LEFT JOIN (
          SELECT record->'payload'->>'tool' AS tool,
                 count(*) FILTER (WHERE event_type='tool.execution_failed') AS failed,
                 count(*) AS executed
          FROM events WHERE event_type IN ('tool.execution_succeeded','tool.execution_failed')
            AND created_at > now() - CAST(:span AS interval) GROUP BY 1
        ) x ON x.tool = d.tool
        WHERE d.created_at > now() - CAST(:span AS interval)
        GROUP BY d.tool ORDER BY requests DESC
        """
            ),
            p,
        ).mappings()
    ]

    denied_pairs = conn.execute(
        text(
            "SELECT d.principal, d.tool, count(*) FROM policy_decisions d WHERE d.decision='deny' "
            "AND d.reason='no_matching_grant' AND d.created_at > now() - CAST(:span AS interval) "
            "GROUP BY 1, 2 HAVING count(*) >= 3 ORDER BY 3 DESC LIMIT 50"
        ),
        p,
    ).all()
    unused = conn.execute(
        text(
            "SELECT g.agent_id, g.tool FROM tool_grants g WHERE g.created_at < now() - CAST(:span AS interval) "
            "AND NOT EXISTS (SELECT 1 FROM policy_decisions d WHERE d.principal = g.agent_id AND d.tool = g.tool "
            "AND d.created_at > now() - CAST(:span AS interval)) LIMIT 10"
        ),
        p,
    ).all()
    expired = conn.execute(
        text("SELECT count(*) FROM approvals WHERE status='expired' AND expires_at > now() - CAST(:span AS interval)"),
        p,
    ).scalar_one()
    pending = conn.execute(
        text("SELECT count(*) FROM approvals WHERE status='pending' AND expires_at > now()")
    ).scalar_one()

    recs: list[Recommendation] = []
    names = {aid: n for aid, (_, n) in agents.items()}
    review = sum(a.needs_review for a in reports)
    if review:
        recs.append(
            Recommendation(
                "high",
                f"{review} run(s) need a decision",
                "An external action may or may not have happened. Confirm with the provider, then mark "
                "the run as succeeded or not executed.",
                "/runs?state=NEEDS_RECONCILIATION",
            )
        )
    grouped: dict[tuple[str, str], list[int]] = {}
    for agent_id, tool, n in denied_pairs:
        grouped.setdefault((names.get(agent_id, agent_id), tool), []).append(n)
    for (name, tool), counts in sorted(grouped.items(), key=lambda kv: -sum(kv[1])):
        total = sum(counts)
        across = f" across {len(counts)} agents with that name" if len(counts) > 1 else ""
        recs.append(
            Recommendation(
                "high" if total >= 10 else "medium",
                f"{name} tried {tool} {total:,} times without permission{across}",
                "If this is legitimate work, grant the tool. If not, investigate the agent's instructions and inputs — "
                "repeated attempts are a common sign of prompt injection.",
                "/agents",
            )
        )
    for t in tools:
        if t["executed"] >= MIN_REQUESTS and t["failed"] / t["executed"] >= TOOL_FAIL_FLAG:
            recs.append(
                Recommendation(
                    "medium",
                    f"{t['tool']} fails often",
                    f"{t['failed']} of {t['executed']} executions failed. Check the integration or its inputs.",
                    "/security",
                )
            )
    for a in reports:
        if a.approvals_rejected >= 2:
            recs.append(
                Recommendation(
                    "medium",
                    f"Approvers keep rejecting {a.name}",
                    f"{a.approvals_rejected} requests rejected. Consider narrowing what this agent "
                    "is allowed to ask for.",
                    "/agents",
                )
            )
    if expired:
        recs.append(
            Recommendation(
                "medium",
                f"{expired} approval(s) expired before anyone answered",
                "Runs waited and timed out. Consider a longer approval window in Rules, or route "
                "approvals to someone who can respond.",
                "/rules",
            )
        )
    if pending:
        recs.append(
            Recommendation("low", f"{pending} approval(s) waiting now", "Review them before they expire.", "/approvals")
        )
    for agent_id, tool in unused:
        recs.append(
            Recommendation(
                "low",
                f"{names.get(agent_id, agent_id)} never used {tool}",
                "Permission granted but unused in this period. Removing unused permissions limits "
                "the damage a compromised agent could do.",
                "/agents",
            )
        )

    t_runs = sum(a.runs for a in reports)
    t_ok = sum(a.succeeded for a in reports)
    t_fail = sum(a.failed for a in reports)
    t_req = sum(a.requests for a in reports)
    t_den = sum(a.denied for a in reports)
    concern = [a for a in reports if a.status == "concern"]
    watch = [a for a in reports if a.status == "watch"]
    verdict = (
        "concern" if concern or review else "watch" if watch or any(r.severity == "medium" for r in recs) else "healthy"
    )

    working: list[str] = []
    not_working: list[str] = []
    if t_ok + t_fail:
        rate = t_ok / (t_ok + t_fail)
        (working if rate >= 0.95 else not_working).append(
            f"{rate:.1%} of finished runs succeeded ({t_ok:,} of {t_ok + t_fail:,})."
        )
    if t_den:
        working.append(f"Policy blocked {t_den:,} unauthorized tool requests; none of them executed.")
    healthy = [a for a in reports if a.status == "healthy"]
    if healthy:
        working.append(f"{len(healthy)} agent(s) behaved as expected.")
    for a in concern[:5]:
        not_working.append(f"{a.name} ({a.agent_id[:12]}…): {a.reasons[0]}")
    if len(concern) > 5:
        not_working.append(f"…and {len(concern) - 5} more agent(s) of concern — see the scorecard.")
    if review:
        not_working.append(f"{review} run(s) stuck with an unknown external outcome.")
    if expired:
        not_working.append(f"{expired} approval(s) expired unanswered.")

    return {
        "verdict": verdict,
        "totals": {
            "runs": t_runs,
            "succeeded": t_ok,
            "failed": t_fail,
            "tool_requests": t_req,
            "blocked": t_den,
            "pending_approvals": pending,
            "expired_approvals": expired,
            "needs_review": review,
        },
        "working": working,
        "not_working": not_working,
        "agents": sorted(
            [{**asdict(a), "deny_rate": a.deny_rate, "failure_rate": a.failure_rate} for a in reports],
            key=lambda x: ({"concern": 0, "watch": 1, "healthy": 2, "idle": 3}[x["status"]], -x["runs"]),
        ),
        "tools": tools,
        "recommendations": [
            asdict(r) for r in sorted(recs, key=lambda r: {"high": 0, "medium": 1, "low": 2}[r.severity])
        ],
    }
