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

interface Stored { memory_id: string; content: string; status: string; created_at: string; run_id: string | null }

function SubjectPanel({ subject, onClose }: { subject: string; onClose: () => void }) {
  const live = useLive<{ items: Stored[] }>(`v1/memory/${subject}`, 5000);
  const items = live.data?.items ?? [];
  return (
    <Panel className="mb-4" title={`Stored about ${subject}`} actions={<button className="chip" onClick={onClose}>Close</button>}>
      {live.error ? <Empty>Could not load memories ({live.error}). Viewing memory content needs the payloads:read permission.</Empty>
        : !live.data ? <Skeleton rows={3} />
        : items.length === 0 ? <Empty>Nothing is stored about {subject}.</Empty> : (
        <ul className="divide-y hairline">
          {items.map((m) => (
            <li key={m.memory_id} className="flex flex-wrap items-start gap-3 px-4 py-3 text-[13.5px]">
              <span className="flex-1 min-w-[240px]">{m.content}</span>
              {m.status === "pending" ? <span title="AegisMem held this back as untrusted; agents cannot recall it until reviewed"><Badge value="quarantined" /></span> : <Badge value={m.status} />}
              <span className="muted whitespace-nowrap">{timeAgo(m.created_at)}</span>
              {m.run_id
                ? <Link href={`/runs/${m.run_id}`} className="mono muted hover:text-[var(--text)]" title="The signed run that wrote this memory">from {m.run_id.slice(0, 12)}…</Link>
                : <span className="muted">not written through AegisTrace</span>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export default function Memory() {
  const [tool, setTool] = useState("all");
  const [subject, setSubject] = useState<string | null>(null);
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
      {subject && <SubjectPanel subject={subject} onClose={() => setSubject(null)} />}
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
                    <td>{subjectOf(d) === "–" ? <span className="muted">–</span> : (
                      <button className="mono underline decoration-dotted underline-offset-4 hover:text-[var(--text)]" onClick={() => setSubject(subjectOf(d))} title="See what is stored">{subjectOf(d)}</button>
                    )}</td>
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
