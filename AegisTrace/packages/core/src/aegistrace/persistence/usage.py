# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Model token usage and estimated cost (Studio: Overview, run timeline, Settings → Usage).

Cost = tokens × the organization's own price for that model. With no price set
the cost stays unknown (NULL); it is never guessed. Costs are estimates from
the price list, not provider billing.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

MTOK = 1_000_000


def cost_micro_usd(conn: Connection, provider: str, model_id: str, usage: dict[str, Any]) -> int | None:
    row = conn.execute(
        text(
            "SELECT input_micro_usd_per_mtok, output_micro_usd_per_mtok FROM model_prices "
            "WHERE provider = :p AND model_id = :m"
        ),
        {"p": provider, "m": model_id},
    ).one_or_none()
    if row is None:
        return None
    # Round up to the next micro-dollar: an estimate should not under-report.
    return int(-(-(int(usage["input_tokens"]) * int(row[0]) + int(usage["output_tokens"]) * int(row[1])) // MTOK))


def record(
    conn: Connection,
    tenant_id: str,
    run_id: str,
    agent_id: str,
    step: int,
    provider: str,
    model_id: str,
    usage: dict[str, Any],
    latency_ms: int | None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO model_usage (tenant_id, run_id, agent_id, step, provider, model_id, input_tokens, "
            "output_tokens, source, cost_micro_usd, latency_ms) VALUES (:t, :r, :a, :s, :p, :m, :i, :o, :src, :c, :l) "
            "ON CONFLICT (run_id, step) DO NOTHING"
        ),
        {
            "t": tenant_id,
            "r": run_id,
            "a": agent_id,
            "s": step,
            "p": provider,
            "m": model_id,
            "i": usage["input_tokens"],
            "o": usage["output_tokens"],
            "src": usage["source"],
            "c": cost_micro_usd(conn, provider, model_id, usage),
            "l": latency_ms,
        },
    )


def summary(conn: Connection, since_interval: str) -> dict[str, Any]:
    """Totals, per model and per agent, for the caller's organization over the given interval."""
    q = (
        "SELECT {g} count(*) calls, coalesce(sum(input_tokens),0) inp, coalesce(sum(output_tokens),0) outp, "
        "sum(cost_micro_usd) cost, count(*) FILTER (WHERE cost_micro_usd IS NULL) unpriced, "
        "count(*) FILTER (WHERE source = 'estimate') estimated "
        "FROM model_usage WHERE created_at > now() - CAST(:span AS interval) {gb}"
    )
    p = {"span": since_interval}
    tot = conn.execute(text(q.format(g="", gb="")), p).mappings().one()
    by_model = (
        conn.execute(text(q.format(g="provider, model_id,", gb="GROUP BY provider, model_id ORDER BY calls DESC")), p)
        .mappings()
        .all()
    )
    by_agent = (
        conn.execute(text(q.format(g="agent_id,", gb="GROUP BY agent_id ORDER BY max(created_at) DESC LIMIT 50")), p)
        .mappings()
        .all()
    )

    def shape(r: Any) -> dict[str, Any]:
        d = dict(r)
        return {
            **{k: v for k, v in d.items() if k not in ("inp", "outp", "cost")},
            "input_tokens": int(d["inp"]),
            "output_tokens": int(d["outp"]),
            "cost_usd": None if d["cost"] is None else int(d["cost"]) / MTOK,
        }

    return {"totals": shape(tot), "by_model": [shape(r) for r in by_model], "by_agent": [shape(r) for r in by_agent]}
