"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import Link from "next/link";
import { useMemo, useState } from "react";
import { timeAgo, useLive } from "@/lib/client";
import type { Decision } from "@/lib/types";
import { Badge, Empty, LiveIndicator, PageHeader, Panel, Skeleton, Stat } from "@/components/ui";

export default function Security() {
  const [filter, setFilter] = useState("deny");
  const live = useLive<{ items: Decision[] }>(`v1/policy-decisions?limit=300${filter === "all" ? "" : `&decision=${filter}`}`, 3000);
  const items = live.data?.items ?? [];
  const byReason = useMemo(() => {
    const m: Record<string, number> = {};
    for (const d of items) if (d.decision === "deny") m[d.reason] = (m[d.reason] ?? 0) + 1;
    return Object.entries(m).sort((a, b) => b[1] - a[1]);
  }, [items]);
  const max = byReason[0]?.[1] ?? 1;

  return (
    <>
      <PageHeader title="Security" subtitle="Every tool request your agents made and what the policy decided. Blocked actions never ran."
                  actions={<LiveIndicator updatedAt={live.updatedAt} error={live.error} />} />
      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <Stat label={filter === "all" ? "Decisions shown" : `${filter} decisions shown`} value={live.data ? items.length : "–"} tone={filter === "deny" && items.length ? "bad" : undefined} />
        <Panel className="lg:col-span-2" title="Denials by reason">
          {byReason.length === 0 ? <Empty>No denials in view.</Empty> : (
            <ul className="space-y-2 p-4">
              {byReason.map(([reason, n]) => (
                <li key={reason} className="grid grid-cols-[180px_1fr_40px] items-center gap-3 text-[13px]">
                  <span className="text-2 truncate">{reason.replaceAll("_", " ")}</span>
                  <span className="h-1.5 rounded-full" style={{ background: "var(--panel-2)" }}>
                    <span className="block h-full rounded-full transition-all duration-500" style={{ width: `${(n / max) * 100}%`, background: "var(--red)" }} />
                  </span>
                  <span className="tnum text-right muted">{n}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      <div className="mb-3 flex gap-2">
        {["deny", "require_approval", "allow", "all"].map((f) => (
          <button key={f} className="chip" data-active={filter === f} onClick={() => setFilter(f)}>{f.replaceAll("_", " ")}</button>
        ))}
      </div>
      <Panel>
        {!live.data ? <Skeleton rows={6} /> : items.length === 0 ? <Empty>No decisions.</Empty> : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>When</th><th>Decision</th><th>Tool</th><th>Reason</th><th>Agent</th><th>Run</th></tr></thead>
              <tbody>
                {items.map((d) => (
                  <tr key={d.decision_id}>
                    <td className="muted whitespace-nowrap">{timeAgo(d.created_at)}</td>
                    <td><Badge value={d.decision} /></td>
                    <td className="mono">{d.tool}</td>
                    <td className="text-2">{d.reason.replaceAll("_", " ")}</td>
                    <td className="mono muted">{d.principal.slice(0, 14)}…</td>
                    <td><Link href={`/runs/${d.run_id}`} className="mono muted hover:text-[var(--text)]">{d.run_id.slice(0, 14)}…</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}
