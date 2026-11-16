"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { useEffect, useState } from "react";
import { api, toast, useLive } from "@/lib/client";
import { RISK, type Agent } from "@/lib/types";
import { Badge, Empty, PageHeader, Panel, Skeleton } from "@/components/ui";

interface Grant { tool: string; max_risk_class: number; allowed_hosts: string[]; granted_by: string; created_at: string }
interface Tool { name: string; description: string; risk_class: number }
interface Sim { result: string; reason: string; policy_revision: string | null; risk_class?: number }

const EXAMPLES: Record<string, unknown> = {
  "calc.add": { a: 1, b: 2 }, "docs.search": { query: "revenue" }, "docs.read": { doc_id: "q3" },
  "data.export": { dataset: "customers", destination: "s3.partner", classification: "CONFIDENTIAL" },
  "email.send": { to: "someone@example.com", subject: "hi", body: "hello" },
  "http.fetch": { url: "https://docs.example.com/page" },
};

export default function Agents() {
  const agents = useLive<{ items: Agent[] }>("v1/agents", 10000);
  const tools = useLive<{ items: Tool[] }>("v1/tools", 60000);
  const [sel, setSel] = useState<string | null>(null);
  const agentId = sel ?? agents.data?.items[0]?.id ?? null;
  const grants = useLive<{ items: Grant[] }>(agentId ? `v1/agents/${agentId}/grants` : null, 5000);

  const [tool, setTool] = useState("calc.add");
  const [cls, setCls] = useState(1);
  const [hosts, setHosts] = useState("");
  const [simTool, setSimTool] = useState("email.send");
  const [simArgs, setSimArgs] = useState(JSON.stringify(EXAMPLES["email.send"], null, 2));
  const [sim, setSim] = useState<Sim | null>(null);
  const [simBusy, setSimBusy] = useState(false);

  useEffect(() => {
    const t = tools.data?.items.find((x) => x.name === tool);
    if (t) setCls(t.risk_class);
  }, [tool, tools.data]);

  async function grant() {
    if (!agentId) return;
    try {
      await api(`v1/agents/${agentId}/grants`, { method: "PUT", json: {
        tool, max_risk_class: cls, allowed_hosts: hosts.split(",").map((h) => h.trim()).filter(Boolean) } });
      toast(`Granted ${tool}`, "ok"); grants.reload(); setSim(null);
    } catch (e) { toast(e instanceof Error ? e.message : "Grant failed", "bad"); }
  }
  async function revoke(t: string) {
    if (!agentId) return;
    try { await api(`v1/agents/${agentId}/grants/${t}`, { method: "DELETE" }); toast(`Revoked ${t}`, "bad"); grants.reload(); setSim(null); }
    catch (e) { toast(e instanceof Error ? e.message : "Revoke failed", "bad"); }
  }
  async function simulate() {
    if (!agentId) return;
    let args: unknown;
    try { args = JSON.parse(simArgs); } catch { toast("Arguments are not valid JSON", "bad"); return; }
    setSimBusy(true);
    try { setSim(await api<Sim>("v1/policy/simulate", { method: "POST", json: { agent_id: agentId, tool: simTool, arguments: args } })); }
    catch (e) { toast(e instanceof Error ? e.message : "Simulation failed", "bad"); }
    finally { setSimBusy(false); }
  }

  const simTone = sim?.result === "allow" ? "var(--green)" : sim?.result === "deny" ? "var(--red)" : "var(--text)";
  return (
    <>
      <PageHeader title="Agents & permissions" subtitle="Choose which tools each agent may use. Anything not listed here is blocked automatically." />
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <Panel title="Agents">
          {!agents.data ? <Skeleton /> : agents.data.items.length === 0 ? <Empty>No agents.</Empty> : (
            <ul className="p-1.5">
              {agents.data.items.map((a) => (
                <li key={a.id}>
                  <button onClick={() => { setSel(a.id); setSim(null); }}
                          className="w-full rounded-md px-3 py-2 text-left transition-colors hover:bg-[var(--hover)]"
                          style={{ background: a.id === agentId ? "var(--hover)" : undefined }}>
                    <div className="text-[14px]">{a.name}</div>
                    <div className="mono text-[12px] muted">{a.id.slice(0, 20)}… · {a.model_provider}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="space-y-4 min-w-0">
          <Panel title="Tool grants" actions={<span className="text-[12.5px] muted">default deny — anything not listed is blocked</span>}>
            {!grants.data ? <Skeleton rows={3} /> : (
              <table className="tbl">
                <thead><tr><th>Tool</th><th>Max class</th><th>Hosts</th><th>Granted by</th><th /></tr></thead>
                <tbody>
                  {grants.data.items.length === 0 ? <tr><td colSpan={5} className="muted">No grants — this agent can call nothing.</td></tr> : grants.data.items.map((g) => (
                    <tr key={g.tool}>
                      <td className="mono">{g.tool}</td>
                      <td className="text-2">{g.max_risk_class} · <span className="muted">{RISK[g.max_risk_class]}</span></td>
                      <td className="mono muted">{g.allowed_hosts.length ? g.allowed_hosts.join(", ") : "—"}</td>
                      <td className="mono muted">{g.granted_by}</td>
                      <td className="text-right"><button className="btn btn-ghost" style={{ color: "var(--red)" }} onClick={() => revoke(g.tool)}>Revoke</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="flex flex-wrap items-end gap-2 border-t hairline p-4">
              <label className="flex flex-col gap-1"><span className="text-[12.5px] muted">Tool</span>
                <select className="input" value={tool} onChange={(e) => setTool(e.target.value)}>
                  {(tools.data?.items ?? []).map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1"><span className="text-[12.5px] muted">Max risk class</span>
                <select className="input" value={cls} onChange={(e) => setCls(Number(e.target.value))}>
                  {RISK.map((r, i) => <option key={i} value={i}>{i} · {r}</option>)}
                </select>
              </label>
              <label className="flex flex-1 min-w-[160px] flex-col gap-1"><span className="text-[12.5px] muted">Allowed hosts (network tools)</span>
                <input className="input" placeholder="docs.example.com" value={hosts} onChange={(e) => setHosts(e.target.value)} />
              </label>
              <button className="btn btn-green" onClick={grant} disabled={!agentId}>Grant</button>
            </div>
          </Panel>

          <Panel title="Policy simulator" actions={<span className="text-[12.5px] muted">dry run · records nothing · executes nothing</span>}>
            <div className="grid gap-4 p-4 md:grid-cols-2">
              <div className="flex flex-col gap-3">
                <label className="flex flex-col gap-1"><span className="text-[12.5px] muted">Tool the agent proposes</span>
                  <select className="input" value={simTool} onChange={(e) => { setSimTool(e.target.value); setSimArgs(JSON.stringify(EXAMPLES[e.target.value] ?? {}, null, 2)); setSim(null); }}>
                    {(tools.data?.items ?? []).map((t) => <option key={t.name} value={t.name}>{t.name} (class {t.risk_class})</option>)}
                  </select>
                </label>
                <label className="flex flex-col gap-1"><span className="text-[12.5px] muted">Arguments</span>
                  <textarea className="input mono text-[12.5px]" rows={6} value={simArgs} onChange={(e) => setSimArgs(e.target.value)} spellCheck={false} />
                </label>
                <button className="btn self-start" onClick={simulate} disabled={simBusy || !agentId}>{simBusy ? "Evaluating…" : "Evaluate"}</button>
              </div>
              <div className="grid place-items-center rounded-lg border hairline p-6 text-center" style={{ background: "var(--bg)" }}>
                {sim ? (
                  <div className="fade-in">
                    <div className="text-[28px] font-semibold tracking-tight" style={{ color: simTone }}>
                      {sim.result === "require_approval" ? "Needs approval" : sim.result === "allow" ? "Allowed" : "Denied"}
                    </div>
                    <div className="mt-2"><Badge value={sim.result} label={sim.reason.replaceAll("_", " ")} /></div>
                  </div>
                ) : <span className="text-[13.5px] muted">Pick a tool and evaluate to see what the gateway would decide right now.</span>}
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
