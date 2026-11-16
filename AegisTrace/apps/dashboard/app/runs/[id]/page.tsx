"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import Link from "next/link";
import { use, useState } from "react";
import { api, timeAgo, toast, useLive } from "@/lib/client";
import type { EventRec, Run } from "@/lib/types";
import { Badge, Empty, Hash, JsonView, LiveIndicator, Panel, Skeleton } from "@/components/ui";

interface Verification {
  status: string; event_count: number; trusted_through_sequence: number; trusted_key_ids: string[];
  findings: { code: string; detail: string; sequence: number | null }[]; warnings: string[];
  checkpoint: { last_sequence: number; final_event_hash: string; key_id: string; created_at: string };
}
interface Replay {
  reconstructed_state: { state: string; attempts: number; tool_calls: unknown[]; denials: unknown[]; model_steps: number };
  projection_state: string; state_matches_projection: boolean;
  decision_replay: { status: string; steps_compared: number; detail?: string; divergence?: unknown };
}

const ACTIVE = new Set(["QUEUED", "RUNNING", "RETRY_SCHEDULED", "RECOVERING", "VALIDATING", "CREATED"]);
const CAT: Record<string, string> = {
  "run.created": "run", "run.state_changed": "run", "model.invoked": "model", "model.failed": "model",
  "tool.authorization": "policy", "tool.denied": "policy", "tool.execution_started": "tool",
  "tool.execution_succeeded": "tool", "tool.execution_failed": "tool", "approval.requested": "approval",
  "approval.decided": "approval",
};

function summarize(e: EventRec): { text: string; tone: "good" | "bad" | "neutral" } {
  const p = (e.payload ?? {}) as Record<string, any>;
  switch (e.event_type) {
    case "run.created": return { text: `Run created by ${e.actor_id}`, tone: "neutral" };
    case "run.state_changed":
      return { text: `${String(p.from).toLowerCase()} → ${String(p.to).toLowerCase()}${p.reason ? ` · ${String(p.reason).replaceAll("_", " ")}` : ""}`,
               tone: p.to === "SUCCEEDED" ? "good" : ["FAILED", "TIMED_OUT", "NEEDS_RECONCILIATION"].includes(p.to) ? "bad" : "neutral" };
    case "model.invoked":
      return { text: p.response?.tool_call ? `Model proposed ${p.response.tool_call.tool}` : `Model answered: “${p.response?.text ?? ""}”`, tone: "neutral" };
    case "model.failed": return { text: `Model error: ${p.error}`, tone: "bad" };
    case "tool.authorization":
      return { text: `${p.tool} — ${p.decision === "allow" ? "allowed" : p.decision === "deny" ? "denied" : "needs approval"} (${String(p.reason).replaceAll("_", " ")})`,
               tone: p.decision === "allow" ? "good" : p.decision === "deny" ? "bad" : "neutral" };
    case "tool.denied": return { text: `${p.tool} — rejected (${String(p.reason).replaceAll("_", " ")})`, tone: "bad" };
    case "tool.execution_started": return { text: `${p.tool} executing${p.retry_safe ? "" : " · not retry-safe"}`, tone: "neutral" };
    case "tool.execution_succeeded": return { text: `${p.tool} succeeded`, tone: "good" };
    case "tool.execution_failed": return { text: `${p.tool} failed (${p.error})`, tone: "bad" };
    case "approval.requested": return { text: `Approval requested for ${p.tool}`, tone: "neutral" };
    case "approval.decided": return { text: `Approval ${p.decision} by ${e.actor_id}`, tone: p.decision === "approved" ? "good" : "bad" };
    default: return { text: e.payload === undefined ? "payload withheld (digest only)" : e.event_type, tone: "neutral" };
  }
}

function Timeline({ events }: { events: EventRec[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const [cat, setCat] = useState("all");
  const shown = events.filter((e) => cat === "all" || CAT[e.event_type] === cat);
  return (
    <>
      <div className="flex flex-wrap gap-2 border-b hairline px-4 py-3">
        {["all", "model", "policy", "tool", "approval", "run"].map((c) => (
          <button key={c} className="chip" data-active={cat === c} onClick={() => setCat(c)}>{c}</button>
        ))}
      </div>
      <ol className="relative px-4 py-3">
        {shown.map((e, i) => {
          const s = summarize(e);
          const color = s.tone === "good" ? "var(--green)" : s.tone === "bad" ? "var(--red)" : "#5b616b";
          const isOpen = open === e.event_id;
          return (
            <li key={e.event_id} className="relative pl-7 fade-in">
              {i < shown.length - 1 ? <span className="absolute left-[7px] top-5 bottom-0 w-px" style={{ background: "var(--border)" }} /> : null}
              <span className="absolute left-[3px] top-[9px] h-[9px] w-[9px] rounded-full" style={{ background: color, boxShadow: `0 0 0 3px var(--panel)` }} />
              <button onClick={() => setOpen(isOpen ? null : e.event_id)} aria-expanded={isOpen}
                      className="w-full rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[var(--hover)]">
                <div className="flex items-baseline gap-3">
                  <span className="mono text-[12px] tnum" style={{ color: "var(--faint)" }}>#{e.sequence_number}</span>
                  <span className="flex-1 text-[14px]" style={{ color: s.tone === "neutral" ? "var(--text)" : color }}>{s.text}</span>
                  <span className="hidden sm:inline text-[12px] uppercase tracking-wider" style={{ color: "var(--faint)" }}>{CAT[e.event_type] ?? "other"}</span>
                  <span className="text-[12.5px] muted whitespace-nowrap">{new Date(e.timestamp).toLocaleTimeString()}</span>
                </div>
              </button>
              {isOpen ? (
                <div className="mb-3 ml-2 mt-1 space-y-2 fade-in">
                  <div className="grid grid-cols-[110px_1fr] gap-y-1 text-[12.5px]">
                    <span className="muted">type</span><span className="mono">{e.event_type}</span>
                    <span className="muted">actor</span><span className="mono">{e.actor_id}</span>
                    <span className="muted">hash</span><span className="mono break-all text-2">{e.current_event_hash}</span>
                    <span className="muted">previous</span><span className="mono break-all muted">{e.previous_event_hash}</span>
                    <span className="muted">payload digest</span><span className="mono break-all muted">{e.payload_digest}</span>
                  </div>
                  {e.payload !== undefined ? <JsonView value={e.payload} /> : <p className="text-[13px] muted">Payload withheld for your token (digest-only view).</p>}
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
    </>
  );
}

function Evidence({ v, events }: { v: Verification | null; events: EventRec[] }) {
  if (!v) return <Skeleton />;
  const ok = v.status === "VALID";
  return (
    <div className="p-4 space-y-5">
      <div className="flex flex-wrap items-center gap-4">
        <div className="grid h-12 w-12 place-items-center rounded-xl" style={{ background: ok ? "var(--green-bg)" : "var(--red-bg)" }}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={ok ? "var(--green)" : "var(--red)"} strokeWidth="2">
            <path d={ok ? "M5 13l4 4L19 7" : "M6 18L18 6M6 6l12 12"} />
          </svg>
        </div>
        <div>
          <div className="text-[16px] font-medium" style={{ color: ok ? "var(--green)" : "var(--red)" }}>{ok ? "Chain intact and signed" : v.status.replaceAll("_", " ")}</div>
          <div className="text-[13px] muted">Trusted through #{v.trusted_through_sequence} of {v.event_count} · signer <span className="mono">{v.checkpoint?.key_id}</span></div>
        </div>
      </div>
      <p className="rounded-md px-3 py-2 text-[13px]" style={{ background: "var(--neutral-bg)", color: "var(--text-2)" }}>
        Server-side check against this deployment’s key. For independent proof, download the receipt and run
        <span className="mono"> aegistrace verify</span> with a trust store you obtained out of band.
      </p>
      {v.findings.length > 0 ? (
        <ul className="space-y-1">{v.findings.map((f, i) => (
          <li key={i} className="text-[13.5px]" style={{ color: "var(--red)" }}><span className="mono">{f.code}</span>{f.sequence ? ` at #${f.sequence}` : ""} — {f.detail}</li>))}</ul>
      ) : null}
      <div>
        <div className="mb-2 text-[13px] muted">Hash chain</div>
        <div className="flex gap-1.5 overflow-x-auto pb-2">
          {events.map((e) => {
            const trusted = e.sequence_number <= v.trusted_through_sequence;
            return (
              <div key={e.event_id} title={`#${e.sequence_number} ${e.event_type}\n${e.current_event_hash}`}
                   className="shrink-0 rounded-md border px-2 py-1.5 text-center"
                   style={{ borderColor: trusted ? "rgba(62,207,142,.35)" : "rgba(242,92,92,.4)", background: trusted ? "var(--green-bg)" : "var(--red-bg)" }}>
                <div className="mono text-[10px] muted">#{e.sequence_number}</div>
                <div className="mono text-[11.5px]" style={{ color: trusted ? "var(--green)" : "var(--red)" }}>{e.current_event_hash.replace("sha256:", "").slice(0, 6)}</div>
              </div>
            );
          })}
          <div className="shrink-0 rounded-md border px-2 py-1.5 text-center hairline" title="Signed checkpoint">
            <div className="mono text-[10px] muted">checkpoint</div>
            <div className="mono text-[11.5px] text-2">ed25519</div>
          </div>
        </div>
      </div>
      {v.warnings.length ? <ul className="space-y-1">{v.warnings.map((w, i) => <li key={i} className="text-[12.5px] muted">• {w}</li>)}</ul> : null}
    </div>
  );
}

function ReplayTab({ r }: { r: Replay | null | undefined }) {
  if (r === undefined) return <Skeleton />;
  if (r === null) return <Empty>Your token lacks the replay:read scope.</Empty>;
  const rs = r.reconstructed_state;
  return (
    <div className="grid gap-3 p-4 sm:grid-cols-2">
      <div className="rounded-lg border hairline p-4">
        <div className="text-[13px] muted">State reconstruction</div>
        <div className="mt-2 flex items-center gap-2"><Badge value={r.state_matches_projection ? "ok" : "DIVERGED"} label={r.state_matches_projection ? "matches database" : "differs from database"} /></div>
        <div className="mt-3 grid grid-cols-2 gap-y-1 text-[13px]">
          <span className="muted">replayed state</span><span className="mono">{rs.state}</span>
          <span className="muted">stored state</span><span className="mono">{r.projection_state}</span>
          <span className="muted">attempts</span><span className="tnum">{rs.attempts}</span>
          <span className="muted">model steps</span><span className="tnum">{rs.model_steps}</span>
          <span className="muted">tool calls</span><span className="tnum">{rs.tool_calls.length}</span>
          <span className="muted">denials</span><span className="tnum">{rs.denials.length}</span>
        </div>
      </div>
      <div className="rounded-lg border hairline p-4">
        <div className="text-[13px] muted">Decision replay</div>
        <div className="mt-2"><Badge value={r.decision_replay.status} /></div>
        <p className="mt-3 text-[13px] text-2">
          Re-drove the agent loop with recorded model responses and tool outcomes. {r.decision_replay.steps_compared} steps compared.
          No model, tool, network or database was contacted.
        </p>
        {r.decision_replay.detail ? <p className="mt-2 text-[13px] muted">{r.decision_replay.detail}</p> : null}
      </div>
    </div>
  );
}

export default function RunDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const run = useLive<Run>(`v1/runs/${id}`, 2000);
  const active = run.data ? ACTIVE.has(run.data.state) : true;
  const events = useLive<{ items: EventRec[]; payloads_included: boolean }>(`v1/runs/${id}/events`, active ? 2000 : 15000);
  const verification = useLive<Verification>(`v1/runs/${id}/verification`, active ? 4000 : 30000);
  const replay = useLive<Replay>(`v1/runs/${id}/replay`, active ? 4000 : 30000);
  const [tab, setTab] = useState<"timeline" | "evidence" | "replay">("timeline");
  const [busy, setBusy] = useState(false);

  async function act(path: string, json: unknown, msg: string) {
    setBusy(true);
    try { await api(path, { method: "POST", json }); toast(msg, "ok"); run.reload(); events.reload(); }
    catch (e) { toast(e instanceof Error ? e.message : "Action failed", "bad"); }
    finally { setBusy(false); }
  }

  if (run.error && !run.data) return <Empty>Run not found.</Empty>;
  const r = run.data;
  const result = r?.result as { text?: string; error?: string } | null | undefined;
  return (
    <>
      <div className="mb-1 text-[13px] muted"><Link href="/runs" className="hover:text-[var(--text)]">Runs</Link> / <span className="mono">{id}</span></div>
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="mono text-[17px] font-semibold">{id}</h1>
          {r ? <Badge value={r.state} /> : null}
          <LiveIndicator updatedAt={run.updatedAt} error={run.error} />
        </div>
        <div className="flex flex-wrap gap-2">
          {r?.state === "NEEDS_RECONCILIATION" ? (
            <>
              <button className="btn btn-green" disabled={busy} onClick={() => act(`v1/runs/${id}/reconcile`, { outcome: "SUCCEEDED", note: "confirmed with provider via dashboard" }, "Marked succeeded")}>Confirm succeeded</button>
              <button className="btn btn-red" disabled={busy} onClick={() => act(`v1/runs/${id}/reconcile`, { outcome: "FAILED", note: "confirmed not executed via dashboard" }, "Marked failed")}>Confirm not executed</button>
            </>
          ) : null}
          {r && (active || r.state === "WAITING_FOR_APPROVAL") ? (
            <button className="btn btn-red" disabled={busy} onClick={() => act(`v1/runs/${id}/cancel`, undefined, "Run cancelled")}>Cancel run</button>
          ) : null}
          <a className="btn" href={`/api/aegis/v1/runs/${id}/receipt`} download={`${id}.receipt.zip`}>Download receipt</a>
        </div>
      </header>

      <section className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ["Agent", <span key="a" className="mono text-[13px]">{r?.agent_id.slice(0, 18)}…</span>],
          ["Events", <span key="e" className="tnum">{r?.last_sequence ?? "–"}</span>],
          ["Attempts", <span key="t" className="tnum">{r?.attempt ?? "–"}</span>],
          ["Head hash", <Hash key="h" value={r?.head_hash} n={14} />],
        ].map(([k, v], i) => (
          <div key={i} className="panel px-4 py-3"><div className="text-[12.5px] muted">{k}</div><div className="mt-1.5 text-[15px]">{v}</div></div>
        ))}
      </section>

      {result ? (
        <div className="mb-4 rounded-lg border px-4 py-3 text-[14px]" style={{ borderColor: result.error ? "rgba(242,92,92,.35)" : "rgba(62,207,142,.3)", background: result.error ? "var(--red-bg)" : "var(--green-bg)" }}>
          <span className="muted mr-2">Result</span>{result.text ?? result.error}
        </div>
      ) : null}

      <Panel>
        <div className="flex gap-1 border-b hairline px-3 pt-2" role="tablist">
          {(["timeline", "evidence", "replay"] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                    className="relative px-3 pb-2.5 pt-1 text-[14px] capitalize transition-colors"
                    style={{ color: tab === t ? "var(--text)" : "var(--muted)" }}>
              {t}
              {t === "evidence" && verification.data ? (
                <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle" style={{ background: verification.data.status === "VALID" ? "var(--green)" : "var(--red)" }} />
              ) : null}
              {tab === t ? <span className="absolute inset-x-2 -bottom-px h-px" style={{ background: "var(--text)" }} /> : null}
            </button>
          ))}
          <span className="ml-auto self-center pb-2 text-[12.5px] muted">{r ? `updated ${timeAgo(r.updated_at)}` : ""}</span>
        </div>
        {tab === "timeline" ? (events.data ? <Timeline events={events.data.items} /> : <Skeleton rows={8} />) : null}
        {tab === "evidence" ? <Evidence v={verification.data} events={events.data?.items ?? []} /> : null}
        {tab === "replay" ? <ReplayTab r={replay.error ? null : replay.data ?? undefined} /> : null}
      </Panel>
    </>
  );
}
