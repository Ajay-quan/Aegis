// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useLive } from "@/lib/client";
import { Badge, Empty, InfoTip, LiveIndicator, PageHeader, Panel, Skeleton } from "@/components/ui";

type Range = "24h" | "7d" | "30d";
const RANGE_LABEL: Record<Range, string> = { "24h": "last 24 hours", "7d": "last 7 days", "30d": "last 30 days" };

interface AgentRow {
  agent_id: string; name: string; runs: number; succeeded: number; failed: number; requests: number; allowed: number;
  denied: number; approvals_requested: number; approvals_rejected: number; needs_review: number;
  status: "healthy" | "watch" | "concern" | "idle"; reasons: string[]; deny_rate: number; failure_rate: number;
}
interface ToolRow { tool: string; requests: number; allowed: number; denied: number; approval: number; failed: number; executed: number }
interface Rec { severity: "high" | "medium" | "low"; title: string; detail: string; href: string }
interface Report {
  range: Range; verdict: "healthy" | "watch" | "concern";
  totals: { runs: number; succeeded: number; failed: number; tool_requests: number; blocked: number;
            pending_approvals: number; expired_approvals: number; needs_review: number };
  working: string[]; not_working: string[]; agents: AgentRow[]; tools: ToolRow[]; recommendations: Rec[];
}

const VERDICT = {
  healthy: { title: "Healthy", text: "Agents are behaving as expected and staying within their permissions.", color: "var(--green)", bg: "var(--green-bg)" },
  watch: { title: "Worth a look", text: "Mostly fine, with a few things to keep an eye on.", color: "var(--amber)", bg: "var(--amber-bg)" },
  concern: { title: "Needs attention", text: "Some agents or workflows are not behaving as they should.", color: "var(--red)", bg: "var(--red-bg)" },
};
const STATUS_LABEL = { healthy: "healthy", watch: "watch", concern: "concern", idle: "idle" };
const SEV = { high: { c: "var(--red)", l: "High" }, medium: { c: "var(--amber)", l: "Medium" }, low: { c: "var(--muted)", l: "Low" } };

function statusBadge(s: AgentRow["status"]) {
  const v = s === "healthy" ? "ok" : s === "concern" ? "FAILED" : s === "watch" ? "pending" : "CANCELLED";
  return <Badge value={v} label={STATUS_LABEL[s]} />;
}

function toMarkdown(r: Report): string {
  const pct = (x: number) => `${(x * 100).toFixed(0)}%`;
  const lines = [
    `# AegisTrace report — ${RANGE_LABEL[r.range]}`, "",
    `**Verdict: ${VERDICT[r.verdict].title}.** ${VERDICT[r.verdict].text}`, "",
    `- Runs: ${r.totals.runs} (${r.totals.succeeded} succeeded, ${r.totals.failed} failed)`,
    `- Tool requests: ${r.totals.tool_requests} (${r.totals.blocked} blocked)`,
    `- Waiting for approval: ${r.totals.pending_approvals} · expired unanswered: ${r.totals.expired_approvals} · needing review: ${r.totals.needs_review}`, "",
    "## What's working", ...r.working.map((w) => `- ${w}`), "",
    "## Needs attention", ...(r.not_working.length ? r.not_working.map((w) => `- ${w}`) : ["- Nothing."]), "",
    "## Recommendations", ...(r.recommendations.length ? r.recommendations.map((x) => `- **[${x.severity}] ${x.title}** — ${x.detail}`) : ["- None."]), "",
    "## Agent scorecard", "", "| Status | Agent | Runs | Success | Blocked requests | Rejected approvals | Why |", "|---|---|---|---|---|---|---|",
    ...r.agents.filter((a) => a.status !== "idle").map((a) =>
      `| ${a.status} | ${a.name} (${a.agent_id}) | ${a.runs} | ${a.succeeded + a.failed ? pct(1 - a.failure_rate) : "—"} | ${a.denied} of ${a.requests} | ${a.approvals_rejected} | ${a.reasons[0]} |`), "",
    "## Tools", "", "| Tool | Requests | Allowed | Needed approval | Blocked | Failed executions |", "|---|---|---|---|---|---|",
    ...r.tools.map((t) => `| ${t.tool} | ${t.requests} | ${t.allowed} | ${t.approval} | ${t.denied} | ${t.failed} of ${t.executed} |`), "",
    `_Generated ${new Date().toISOString()} from recorded AegisTrace data. Verdicts follow fixed, documented thresholds._`,
  ];
  return lines.join("\n");
}

function MiniStack({ t }: { t: ToolRow }) {
  const total = Math.max(1, t.requests);
  const parts = [["allowed", t.allowed, "var(--series-good)"], ["approval", t.approval, "var(--series-info)"], ["denied", t.denied, "var(--series-bad)"]] as const;
  return (
    <div className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full" style={{ background: "var(--panel-2)" }}
         title={`${t.allowed} allowed · ${t.approval} needed approval · ${t.denied} blocked`}>
      {parts.filter(([, v]) => v > 0).map(([k, v, c]) => <div key={k} style={{ width: `${(v / total) * 100}%`, background: c }} />)}
    </div>
  );
}

export default function Insights() {
  const [range, setRange] = useState<Range>("7d");
  const [filter, setFilter] = useState<"all" | AgentRow["status"]>("all");
  const live = useLive<Report>(`v1/insights?range=${range}`, 15000);
  const r = live.data && live.data.range === range ? live.data : null;
  const agents = useMemo(() => (r?.agents ?? []).filter((a) => (filter === "all" ? a.status !== "idle" : a.status === filter)), [r, filter]);
  const counts = useMemo(() => {
    const c = { healthy: 0, watch: 0, concern: 0, idle: 0 };
    (r?.agents ?? []).forEach((a) => c[a.status]++);
    return c;
  }, [r]);

  function download() {
    if (!r) return;
    const blob = new Blob([toMarkdown(r)], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `aegistrace-report-${range}-${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const v = r ? VERDICT[r.verdict] : null;
  return (
    <>
      <PageHeader title="Insights" subtitle="A plain-language report on how your agents behaved, what's working, and what to change."
                  actions={<>
                    <LiveIndicator updatedAt={live.updatedAt} error={live.error} />
                    <div className="seg" role="group" aria-label="Report period">
                      {(["24h", "7d", "30d"] as Range[]).map((x) => <button key={x} data-active={range === x} onClick={() => setRange(x)}>{x}</button>)}
                    </div>
                    <button className="btn" onClick={download} disabled={!r}>Download report</button>
                  </>} />

      {!r || !v ? <Skeleton rows={8} /> : (
        <div className="space-y-4 fade-in">
          <section className="panel flex flex-wrap items-center gap-5 p-5">
            <div className="grid h-14 w-14 place-items-center rounded-2xl" style={{ background: v.bg }}>
              <span className="h-3 w-3 rounded-full" style={{ background: v.color }} />
            </div>
            <div className="min-w-[220px] flex-1">
              <div className="text-[20px] font-semibold tracking-tight" style={{ color: v.color }}>{v.title}</div>
              <p className="mt-0.5 text-[14px] text-2">{v.text}</p>
            </div>
            <dl className="grid grid-cols-2 gap-x-8 gap-y-1 text-[13.5px] sm:grid-cols-4">
              {[["Runs", r.totals.runs], ["Success", r.totals.succeeded + r.totals.failed ? `${((r.totals.succeeded / (r.totals.succeeded + r.totals.failed)) * 100).toFixed(1)}%` : "—"],
                ["Blocked", r.totals.blocked], ["Waiting on you", r.totals.pending_approvals + r.totals.needs_review]].map(([k, val]) => (
                <div key={String(k)}><dt className="muted">{k}</dt><dd className="text-[17px] font-semibold tnum">{typeof val === "number" ? val.toLocaleString() : val}</dd></div>
              ))}
            </dl>
          </section>

          <div className="grid gap-4 md:grid-cols-2">
            <Panel title={<span className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--green)" }} />What's working</span>}>
              <ul className="space-y-2 p-4 text-[14px]">
                {r.working.length ? r.working.map((w) => <li key={w} className="flex gap-2"><span style={{ color: "var(--green)" }}>✓</span><span className="text-2">{w}</span></li>)
                  : <li className="muted">Not enough activity yet.</li>}
              </ul>
            </Panel>
            <Panel title={<span className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--red)" }} />Needs attention</span>}>
              <ul className="space-y-2 p-4 text-[14px]">
                {r.not_working.length ? r.not_working.map((w) => <li key={w} className="flex gap-2"><span style={{ color: "var(--red)" }}>!</span><span className="text-2">{w}</span></li>)
                  : <li className="text-2">Nothing — all agents and workflows are in good shape.</li>}
              </ul>
            </Panel>
          </div>

          <Panel title={<span className="flex items-center gap-2">Recommended actions<InfoTip text="Generated from fixed rules over your recorded data — not AI guesses. Each one links to where you can act on it." /></span>}
                 actions={<span className="text-[12.5px] muted">{r.recommendations.length} item(s)</span>}>
            {r.recommendations.length === 0 ? <Empty>No changes recommended for the {RANGE_LABEL[range]}.</Empty> : (
              <ul>
                {r.recommendations.slice(0, 12).map((x, i) => (
                  <li key={i} className="flex items-start gap-3 border-b px-4 py-3 last:border-0 hairline">
                    <span className="mt-0.5 w-14 shrink-0 text-[12px] font-semibold uppercase tracking-wider" style={{ color: SEV[x.severity].c }}>{SEV[x.severity].l}</span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[14px] font-medium">{x.title}</div>
                      <p className="mt-0.5 text-[13px] muted leading-relaxed">{x.detail}</p>
                    </div>
                    <Link href={x.href} className="btn h-7 shrink-0">Open →</Link>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title={<span className="flex items-center gap-2">Agent scorecard<InfoTip text="Concern: 25%+ of tool requests blocked, 20%+ of runs failed, repeated approval rejections, or an unresolved outcome. Watch: smaller versions of the same. Needs at least 5 requests or runs before judging." /></span>}>
            <div className="flex flex-wrap gap-2 border-b px-4 py-3 hairline">
              {(["all", "concern", "watch", "healthy", "idle"] as const).map((f) => (
                <button key={f} className="chip" data-active={filter === f} onClick={() => setFilter(f)}>
                  {f === "all" ? "Active" : STATUS_LABEL[f]}{f !== "all" ? <span className="ml-1.5 tnum muted">{counts[f]}</span> : null}
                </button>
              ))}
            </div>
            {agents.length === 0 ? <Empty>No agents in this group.</Empty> : (
              <div className="overflow-x-auto">
                <table className="tbl">
                  <thead><tr><th>Status</th><th>Agent</th><th className="text-right">Runs</th><th style={{ minWidth: 120 }}>Success</th>
                    <th className="text-right">Blocked</th><th className="text-right">Rejected</th><th>Why</th></tr></thead>
                  <tbody>
                    {agents.map((a) => {
                      const done = a.succeeded + a.failed;
                      const sr = done ? 1 - a.failure_rate : null;
                      return (
                        <tr key={a.agent_id}>
                          <td>{statusBadge(a.status)}</td>
                          <td><div className="text-[14px]">{a.name}</div><div className="mono text-[12px] muted">{a.agent_id.slice(0, 18)}…</div></td>
                          <td className="text-right tnum">{a.runs.toLocaleString()}</td>
                          <td>{sr === null ? <span className="muted">—</span> : (
                            <div className="flex items-center gap-2">
                              <div className="h-1.5 flex-1 rounded-full" style={{ background: "var(--panel-2)" }}>
                                <div className="h-full rounded-full" style={{ width: `${sr * 100}%`, background: sr >= 0.95 ? "var(--series-good)" : "var(--series-bad)" }} />
                              </div>
                              <span className="w-11 text-right tnum text-[13px]">{(sr * 100).toFixed(0)}%</span>
                            </div>)}</td>
                          <td className="text-right tnum">{a.requests ? <>{a.denied.toLocaleString()} <span className="muted">/ {a.requests.toLocaleString()}</span></> : "—"}</td>
                          <td className="text-right tnum">{a.approvals_rejected || "—"}</td>
                          <td className="max-w-[340px] text-[13px] text-2">{a.reasons[0]}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel title="Tools" actions={<span className="flex items-center gap-3 text-[12.5px] text-2">
            {[["Allowed", "var(--series-good)"], ["Needed approval", "var(--series-info)"], ["Blocked", "var(--series-bad)"]].map(([l, c]) => (
              <span key={l} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-[2px]" style={{ background: c }} />{l}</span>))}</span>}>
            {r.tools.length === 0 ? <Empty>No tool activity in the {RANGE_LABEL[range]}.</Empty> : (
              <table className="tbl">
                <thead><tr><th>Tool</th><th className="text-right">Requests</th><th style={{ width: "40%" }}>Decisions</th><th className="text-right">Failed runs of the tool</th></tr></thead>
                <tbody>{r.tools.map((t) => (
                  <tr key={t.tool}>
                    <td className="mono">{t.tool}</td>
                    <td className="text-right tnum">{t.requests.toLocaleString()}</td>
                    <td><MiniStack t={t} /></td>
                    <td className="text-right tnum">{t.executed ? <span style={{ color: t.failed / t.executed >= 0.1 ? "var(--red)" : undefined }}>{t.failed} <span className="muted">/ {t.executed}</span></span> : <span className="muted">—</span>}</td>
                  </tr>))}</tbody>
              </table>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}
