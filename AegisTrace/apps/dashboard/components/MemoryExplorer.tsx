"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Memory Explorer: what is stored about one subject, searchable, reviewable and correctable.
// Every call goes through the AegisTrace API; the browser never reaches AegisMem.
import Link from "next/link";
import { useState } from "react";
import { ApiError, api, timeAgo, toast, useLive } from "@/lib/client";
import { Badge, Empty, Panel, Skeleton } from "@/components/ui";

interface Stored {
  memory_id: string; content: string; status: string; created_at: string; run_id: string | null; version: number;
  memory_type: string | null; source_type: string | null; importance: number | null; contradiction_status: string | null;
}
interface Hit { memory_id: string; content: string; score_bp: number; semantic_bp: number; rank: number | null }
interface Contra { report_id: string; a: { memory_id: string; content: string }; b: { memory_id: string; content: string }; description: string; confidence_bp: number }

type Tab = "memories" | "search" | "contradictions" | "review" | "correct";
const TABS: [Tab, string][] = [["memories", "Memories"], ["search", "Search"], ["contradictions", "Contradictions"], ["review", "Review"], ["correct", "Correct"]];

async function act<T>(path: string, json: unknown, ok: string): Promise<T | null> {
  try { const r = await api<T>(path, { method: "POST", json }); toast(ok, "ok"); return r; }
  catch (err) { toast(err instanceof ApiError ? err.message : "That did not work", "bad"); return null; }
}

export function MemoryExplorer({ subject, onClose }: { subject: string; onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("memories");
  const stored = useLive<{ items: Stored[] }>(`v1/memory/${subject}`, 8000);
  const items = stored.data?.items ?? [];
  const pending = items.filter((m) => m.status === "pending");

  return (
    <Panel className="mb-4" title={<span>Memory about <span className="mono">{subject}</span></span>}
           actions={<button className="chip" onClick={onClose}>Close</button>}>
      <div className="flex flex-wrap gap-2 border-b hairline px-4 py-2.5" role="tablist">
        {TABS.map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} className="chip" data-active={tab === t} onClick={() => setTab(t)}>
            {label}{t === "review" && pending.length ? ` (${pending.length})` : ""}
          </button>
        ))}
      </div>
      {stored.error && tab !== "correct" ? (
        <Empty>Could not load memories ({stored.error}). Memory content needs the payloads:read permission.</Empty>
      ) : tab === "memories" ? <Memories subject={subject} items={stored.data ? items : null} reload={stored.reload} />
        : tab === "search" ? <Search subject={subject} />
        : tab === "contradictions" ? <Contradictions subject={subject} />
        : tab === "review" ? <Review subject={subject} items={pending} reload={stored.reload} />
        : <Correct subject={subject} reload={stored.reload} />}
    </Panel>
  );
}

function Memories({ subject, items, reload }: { subject: string; items: Stored[] | null; reload: () => void }) {
  const [picked, setPicked] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  if (!items) return <Skeleton rows={3} />;
  if (items.length === 0) return <Empty>Nothing is stored about {subject}.</Empty>;
  return (
    <>
      <ul className="divide-y hairline">
        {items.map((m) => (
          <li key={m.memory_id} className="flex flex-wrap items-start gap-3 px-4 py-3 text-[13.5px]">
            <input type="checkbox" aria-label={`Select ${m.memory_id}`} className="mt-1 h-4 w-4 accent-[var(--red)]" checked={picked.includes(m.memory_id)}
                   onChange={(e) => setPicked((p) => (e.target.checked ? [...p, m.memory_id] : p.filter((x) => x !== m.memory_id)))} />
            <div className="min-w-[240px] flex-1">
              <p>{m.content}</p>
              <p className="mt-1 text-[12px] muted">
                version {m.version}{m.memory_type ? ` · ${m.memory_type}` : ""}{m.importance != null ? ` · importance ${m.importance.toFixed(2)}` : ""}
                {m.contradiction_status && m.contradiction_status !== "none" ? ` · ${m.contradiction_status}` : ""} · {timeAgo(m.created_at)}
              </p>
            </div>
            {m.status === "pending" ? <span title="Held back as untrusted; agents cannot recall it until reviewed"><Badge value="quarantined" /></span> : <Badge value={m.status} />}
            {m.run_id ? <Link href={`/runs/${m.run_id}`} className="mono muted hover:text-[var(--text)]" title="The signed run that wrote this memory">from {m.run_id.slice(0, 12)}…</Link>
              : <span className="muted text-[12.5px]">not written by an agent run</span>}
          </li>
        ))}
      </ul>
      {picked.length ? (
        <form className="flex flex-wrap items-center gap-2 border-t hairline px-4 py-3" onSubmit={async (e) => {
          e.preventDefault();
          const r = await act<{ body: { receipt_id: string } }>(`v1/memory/${subject}/forget`, { memory_ids: picked, reason }, "Erased. A signed receipt was issued.");
          if (r) { setPicked([]); setReason(""); reload(); }
        }}>
          <span className="text-[13px]">Erase {picked.length} {picked.length === 1 ? "memory" : "memories"} permanently</span>
          <input id="forget-reason" className="input min-w-[220px] flex-1" required minLength={3} placeholder="Reason, for the audit log" value={reason} onChange={(e) => setReason(e.target.value)} />
          <button className="btn btn-red" type="submit">Erase</button>
        </form>
      ) : null}
    </>
  );
}

function Search({ subject }: { subject: string }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  return (
    <div className="p-4">
      <form className="flex gap-2" onSubmit={async (e) => {
        e.preventDefault();
        const r = await act<{ items: Hit[] }>(`v1/memory/${subject}/search`, { query: q }, "Searched");
        setHits(r?.items ?? []);
      }}>
        <input id="memory-query" className="input flex-1" required placeholder="Ask what is remembered, e.g. invoice currency" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn btn-green" type="submit">Search</button>
      </form>
      {hits === null ? <p className="mt-3 text-[12.5px] muted">Results are ranked by meaning, recency and importance, the way an agent would recall them.</p>
        : hits.length === 0 ? <Empty>Nothing matches.</Empty> : (
        <ol className="mt-3 divide-y hairline">
          {hits.map((h) => (
            <li key={h.memory_id} className="flex items-start justify-between gap-4 py-2.5 text-[13.5px]">
              <span>{h.content}</span>
              <span className="mono whitespace-nowrap text-[12px] muted" title="Relevance score (higher is closer)">{(h.score_bp / 100).toFixed(1)}%</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function Contradictions({ subject }: { subject: string }) {
  const live = useLive<{ items: Contra[] }>(`v1/memory/${subject}/contradictions`, 20000);
  if (!live.data) return <Skeleton rows={2} />;
  if (live.data.items.length === 0) return <Empty>No contradictions found between memories about {subject}.</Empty>;
  return (
    <ul className="divide-y hairline">
      {live.data.items.map((c) => (
        <li key={c.report_id} className="px-4 py-3 text-[13.5px]">
          <p className="text-2">{c.description} <span className="muted">· confidence {(c.confidence_bp / 100).toFixed(0)}%</span></p>
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            {[c.a, c.b].map((m) => <p key={m.memory_id} className="rounded-md px-3 py-2" style={{ background: "var(--panel-2)" }}>{m.content}</p>)}
          </div>
        </li>
      ))}
    </ul>
  );
}

function Review({ subject, items, reload }: { subject: string; items: Stored[]; reload: () => void }) {
  if (items.length === 0) return <Empty>Nothing is waiting for review. Memories AegisMem considers untrusted appear here before any agent can recall them.</Empty>;
  return (
    <ul className="divide-y hairline">
      {items.map((m) => (
        <li key={m.memory_id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-[13.5px]">
          <span className="min-w-[240px] flex-1">{m.content}</span>
          <button className="btn btn-green" type="button" onClick={async () => { if (await act(`v1/memory/${subject}/review/${m.memory_id}`, { release: true }, "Released: agents can recall it now")) reload(); }}>Release</button>
          <button className="btn btn-red" type="button" onClick={async () => { if (await act(`v1/memory/${subject}/review/${m.memory_id}`, { release: false }, "Rejected")) reload(); }}>Reject</button>
        </li>
      ))}
    </ul>
  );
}

function Correct({ subject, reload }: { subject: string; reload: () => void }) {
  const [text, setText] = useState("");
  return (
    <form className="flex flex-col gap-3 p-4" onSubmit={async (e) => {
      e.preventDefault();
      if (await act(`v1/memory/${subject}/corrections`, { text }, "Saved. It supersedes any memory it corrects.")) { setText(""); reload(); }
    }}>
      <label className="flex flex-col gap-1.5 text-[13px]">
        <span className="muted">What is true now. AegisMem keeps the earlier version and marks it superseded.</span>
        <textarea id="memory-correction" className="input" rows={3} required maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <button className="btn btn-green self-start" type="submit">Save correction</button>
    </form>
  );
}
