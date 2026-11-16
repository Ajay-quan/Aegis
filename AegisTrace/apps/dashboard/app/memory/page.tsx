"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import Link from "next/link";
import { useMemo, useState } from "react";
import { timeAgo, useLive } from "@/lib/client";
import type { Decision } from "@/lib/types";
import { Badge, Empty, LiveIndicator, PageHeader, Panel, Skeleton, Stat } from "@/components/ui";

const ACTIONS: Record<string, string> = {
  "memory.recall": "Recalled",
  "memory.remember": "Remembered",
  "memory.forget": "Erased",
};

function subjectOf(d: Decision): string {
  try {
    const r = typeof d.resource === "string" ? JSON.parse(d.resource) : d.resource;
    return typeof r?.subject === "string" ? r.subject : "–";
  } catch {
    return "–";
  }
}

export default function Memory() {
  const [tool, setTool] = useState("all");
  const live = useLive<{ items: Decision[] }>("v1/policy-decisions?limit=300&tool_prefix=memory.", 3000);
  const all = live.data?.items ?? [];
  const items = tool === "all" ? all : all.filter((d) => d.tool === tool);
  const counts = useMemo(() => {
    const c = { reads: 0, writes: 0, blocked: 0, waiting: 0 };
    for (const d of all) {
      if (d.decision === "deny") c.blocked++;
      else if (d.decision === "require_approval") c.waiting++;
      else if (d.tool === "memory.recall") c.reads++;
      else c.writes++;
    }
    return c;
  }, [all]);

  return (
    <>
      <PageHeader title="Memory" subtitle="What your agents remembered, recalled and erased through AegisMem. Every access was checked against your rules and is in the signed log."
                  actions={<LiveIndicator updatedAt={live.updatedAt} error={live.error} />} />
      <div className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Recalls allowed" value={live.data ? counts.reads : "–"} />
        <Stat label="Writes and erasures allowed" value={live.data ? counts.writes : "–"} />
        <Stat label="Blocked" value={live.data ? counts.blocked : "–"} tone={counts.blocked ? "bad" : undefined} />
        <Stat label="Sent for approval" value={live.data ? counts.waiting : "–"} />
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        {["all", ...Object.keys(ACTIONS)].map((t) => (
          <button key={t} className="chip" data-active={tool === t} onClick={() => setTool(t)}>{t === "all" ? "all" : ACTIONS[t].toLowerCase()}</button>
        ))}
      </div>
      <Panel>
        {!live.data ? <Skeleton rows={6} /> : items.length === 0 ? (
          <Empty>No memory activity yet. Grant an agent <span className="mono">memory.recall</span> or <span className="mono">memory.remember</span> under Agents &amp; permissions, and set <span className="mono">AEGIS_MEMORY_URL</span> on the worker.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>When</th><th>Action</th><th>About</th><th>Decision</th><th>Reason</th><th>Run</th></tr></thead>
              <tbody>
                {items.map((d) => (
                  <tr key={d.decision_id}>
                    <td className="muted whitespace-nowrap">{timeAgo(d.created_at)}</td>
                    <td>{ACTIONS[d.tool] ?? d.tool}</td>
                    <td className="mono">{subjectOf(d)}</td>
                    <td><Badge value={d.decision} /></td>
                    <td className="text-2">{d.reason.replaceAll("_", " ")}</td>
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
