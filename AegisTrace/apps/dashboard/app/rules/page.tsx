// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, timeAgo, toast, useLive } from "@/lib/client";
import { Badge, InfoTip, PageHeader, Panel, Skeleton } from "@/components/ui";

interface Rules {
  approval_min_risk_class: number; restricted_data_requires_approval: boolean;
  blocked_tools: string[]; always_require_approval: string[]; approval_ttl_minutes: number;
}
interface RulesResp { rules: Rules; version: number; preset: string | null; presets: Record<string, { rules: Rules; description: string }> }
interface Tool { name: string; description: string; risk_class: number }
interface Hist { version: number; changed_by: string; source: string; note: string | null; created_at: string }

const LEVELS = [
  { v: 1, label: "Reads", hint: "e.g. search or read documents" },
  { v: 2, label: "Reversible changes", hint: "e.g. edit something that can be undone" },
  { v: 3, label: "Consequential changes", hint: "e.g. export data, change settings" },
  { v: 4, label: "Irreversible only", hint: "e.g. send email, make payments" },
];
const TTLS = [[15, "15 minutes"], [30, "30 minutes"], [60, "1 hour"], [240, "4 hours"], [1440, "1 day"]] as const;
const PRESET_LABEL: Record<string, string> = { strict: "Strict", balanced: "Balanced", permissive: "Permissive" };

function outcome(t: Tool, r: Rules): "blocked" | "approval" | "automatic" {
  if (r.blocked_tools.includes(t.name)) return "blocked";
  if (r.always_require_approval.includes(t.name) || t.risk_class >= r.approval_min_risk_class) return "approval";
  return "automatic";
}

function ToolPicker({ tools, selected, onToggle, tone }: {
  tools: Tool[]; selected: string[]; onToggle: (n: string) => void; tone: "bad" | "attn";
}) {
  const on = tone === "bad" ? { c: "var(--red)", bg: "var(--red-bg)", b: "rgba(242,92,92,.4)" } : { c: "var(--amber)", bg: "var(--amber-bg)", b: "rgba(229,162,58,.4)" };
  return (
    <div className="flex flex-wrap gap-2">
      {tools.map((t) => {
        const active = selected.includes(t.name);
        return (
          <button key={t.name} type="button" onClick={() => onToggle(t.name)} aria-pressed={active}
                  className="mono rounded-md border px-2.5 py-1 text-[13px] transition-colors"
                  style={active ? { color: on.c, background: on.bg, borderColor: on.b } : { color: "var(--text-2)", borderColor: "var(--border)" }}>
            {active ? "✓ " : ""}{t.name}
          </button>
        );
      })}
    </div>
  );
}

export default function RulesPage() {
  const live = useLive<RulesResp>("v1/rules", 30000);
  const tools = useLive<{ items: Tool[] }>("v1/tools", 60000);
  const hist = useLive<{ items: Hist[] }>("v1/rules/history", 30000);
  const [draft, setDraft] = useState<Rules | null>(null);
  const [saving, setSaving] = useState(false);
  const [plan, setPlan] = useState<{ text: string; changes: string[] } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (live.data && !draft) setDraft(live.data.rules); }, [live.data, draft]);
  const saved = live.data?.rules;
  const dirty = !!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved);
  const presetName = useMemo(() => {
    if (!draft || !live.data) return null;
    return Object.entries(live.data.presets).find(([, p]) => JSON.stringify(p.rules) === JSON.stringify(draft))?.[0] ?? null;
  }, [draft, live.data]);
  const toolList = tools.data?.items ?? [];

  const set = (patch: Partial<Rules>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const toggle = (key: "blocked_tools" | "always_require_approval", name: string) => {
    if (!draft) return;
    const other = key === "blocked_tools" ? "always_require_approval" : "blocked_tools";
    const list = draft[key].includes(name) ? draft[key].filter((x) => x !== name) : [...draft[key], name];
    set({ [key]: list.sort(), [other]: draft[other].filter((x) => x !== name) } as Partial<Rules>);
  };

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      const r = await api<{ version: number }>("v1/rules", { method: "PUT", json: { rules: draft, source: "dashboard" } });
      toast(`Rules saved — in effect immediately`, "ok");
      await live.reload(); await hist.reload();
    } catch (e) { toast(e instanceof Error ? e.message : "Save failed", "bad"); }
    finally { setSaving(false); }
  }

  async function previewFile(f: File) {
    const text = await f.text();
    try {
      const r = await api<{ changes: string[] }>("v1/rules/file?dry_run=true", { method: "POST", body: text, headers: { "Content-Type": "application/yaml" } });
      setPlan({ text, changes: r.changes });
    } catch (e) { toast(e instanceof ApiError ? e.message : "Could not read that file", "bad"); }
    if (fileRef.current) fileRef.current.value = "";
  }
  async function applyFile() {
    if (!plan) return;
    try {
      const r = await api<{ changes: string[] }>("v1/rules/file", { method: "POST", body: plan.text, headers: { "Content-Type": "application/yaml" } });
      toast(`Applied ${r.changes.length} change(s)`, "ok");
      setPlan(null); setDraft(null); await live.reload(); await hist.reload();
    } catch (e) { toast(e instanceof Error ? e.message : "Apply failed", "bad"); }
  }

  if (!draft || !live.data) return <><PageHeader title="Rules" /><Skeleton rows={8} /></>;
  const counts = { automatic: 0, approval: 0, blocked: 0 };
  toolList.forEach((t) => counts[outcome(t, draft)]++);

  return (
    <div className={dirty ? "pb-20" : ""}>
      <PageHeader title="Rules"
                  subtitle="Decide what agents may do on their own, what needs a person, and what is never allowed. These apply to every agent in your organization, on top of each agent's own permissions." />

      <section className="mb-5 grid gap-3 md:grid-cols-3" aria-label="Presets">
        {Object.entries(live.data.presets).map(([k, p]) => {
          const active = presetName === k;
          return (
            <button key={k} onClick={() => setDraft(p.rules)}
                    className="panel p-4 text-left transition-colors hover:border-[#3a3f47]"
                    style={active ? { borderColor: "rgba(62,207,142,.45)", background: "rgba(62,207,142,.04)" } : undefined}>
              <div className="flex items-center justify-between">
                <span className="text-[15px] font-medium">{PRESET_LABEL[k]}</span>
                {active ? <Badge value="ok" label="selected" /> : k === "balanced" ? <span className="text-[12px] muted">recommended</span> : null}
              </div>
              <p className="mt-1.5 text-[13.5px] muted leading-relaxed">{p.description}</p>
            </button>
          );
        })}
      </section>

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4 min-w-0">
          <Panel title={<span className="flex items-center gap-2">When should a person approve?<InfoTip text="Every tool has a risk level set by your platform team. Actions at or above the level you pick here pause until someone approves that exact action." /></span>}>
            <div className="p-4">
              <div className="grid gap-2 sm:grid-cols-4" role="radiogroup" aria-label="Approval threshold">
                {LEVELS.map((l) => {
                  const active = draft.approval_min_risk_class === l.v;
                  return (
                    <button key={l.v} role="radio" aria-checked={active} onClick={() => set({ approval_min_risk_class: l.v })}
                            className="rounded-lg border p-3 text-left transition-colors"
                            style={{ borderColor: active ? "#4a5059" : "var(--border)", background: active ? "var(--hover)" : "transparent" }}>
                      <div className="text-[13.5px] font-medium">{l.label}{l.v < 4 ? " and up" : ""}</div>
                      <div className="mt-0.5 text-[12.5px] muted">{l.hint}</div>
                    </button>
                  );
                })}
              </div>
              <label className="mt-4 flex cursor-pointer items-center justify-between gap-4 rounded-lg border px-3 py-2.5 hairline">
                <span><span className="text-[14px]">Always ask before touching restricted data</span>
                  <span className="block text-[12.5px] muted">Even low-risk tools wait for approval when the data is classified RESTRICTED.</span></span>
                <input type="checkbox" className="h-4 w-4 accent-[var(--green)]" checked={draft.restricted_data_requires_approval}
                       onChange={(e) => set({ restricted_data_requires_approval: e.target.checked })} />
              </label>
              <label className="mt-3 flex items-center justify-between gap-4 rounded-lg border px-3 py-2.5 hairline">
                <span><span className="text-[14px]">Approvals expire after</span>
                  <span className="block text-[12.5px] muted">If nobody answers in time, the request lapses and the run stops waiting.</span></span>
                <select className="input" value={draft.approval_ttl_minutes} onChange={(e) => set({ approval_ttl_minutes: Number(e.target.value) })}>
                  {TTLS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  {!TTLS.some(([v]) => v === draft.approval_ttl_minutes) ? <option value={draft.approval_ttl_minutes}>{draft.approval_ttl_minutes} minutes</option> : null}
                </select>
              </label>
            </div>
          </Panel>

          <Panel title={<span className="flex items-center gap-2">Never allowed<InfoTip text="Blocked for every agent, even if an agent was granted the tool or someone approved it." /></span>}>
            <div className="p-4">{tools.data ? <ToolPicker tools={toolList} selected={draft.blocked_tools} onToggle={(n) => toggle("blocked_tools", n)} tone="bad" /> : <Skeleton rows={1} />}</div>
          </Panel>
          <Panel title={<span className="flex items-center gap-2">Always ask a person first<InfoTip text="These tools always wait for approval, whatever their risk level." /></span>}>
            <div className="p-4">{tools.data ? <ToolPicker tools={toolList} selected={draft.always_require_approval} onToggle={(n) => toggle("always_require_approval", n)} tone="attn" /> : <Skeleton rows={1} />}</div>
          </Panel>

          <Panel title="What happens with these rules" actions={<span className="text-[12.5px] muted">for agents that have been granted the tool</span>}>
            <div className="flex flex-wrap gap-4 border-b px-4 py-3 text-[13.5px] hairline">
              <span><span className="tnum font-semibold" style={{ color: "var(--green)" }}>{counts.automatic}</span> <span className="muted">run automatically</span></span>
              <span><span className="tnum font-semibold" style={{ color: "var(--amber)" }}>{counts.approval}</span> <span className="muted">need approval</span></span>
              <span><span className="tnum font-semibold" style={{ color: "var(--red)" }}>{counts.blocked}</span> <span className="muted">never allowed</span></span>
            </div>
            <table className="tbl">
              <thead><tr><th>Tool</th><th>Risk level</th><th>Outcome</th></tr></thead>
              <tbody>
                {toolList.map((t) => {
                  const o = outcome(t, draft);
                  return (
                    <tr key={t.name}>
                      <td><span className="mono">{t.name}</span><span className="ml-2 text-[12.5px] muted">{t.description}</span></td>
                      <td className="muted">{t.risk_class}</td>
                      <td>{o === "blocked" ? <Badge value="deny" label="never allowed" /> : o === "approval" ? <Badge value="pending" label="needs approval" /> : <Badge value="allow" label="automatic" />}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Panel>
        </div>

        <aside className="space-y-4">
          <Panel title="Rules as a file">
            <div className="space-y-3 p-4 text-[13.5px]">
              <p className="muted leading-relaxed">Prefer version control? Download your rules and agent permissions as a short YAML file, edit it, and upload it here — or run <span className="mono text-2">aegistrace policy apply rules.yaml</span>.</p>
              <div className="flex gap-2">
                <a className="btn" href="/api/aegis/v1/rules/file" download="aegistrace-rules.yaml">Download</a>
                <button className="btn" onClick={() => fileRef.current?.click()}>Upload…</button>
                <input ref={fileRef} type="file" accept=".yaml,.yml,text/yaml" className="hidden" aria-label="Upload rules file"
                       onChange={(e) => e.target.files?.[0] && previewFile(e.target.files[0])} />
              </div>
              {plan ? (
                <div className="rounded-lg border p-3 fade-in hairline" style={{ background: "var(--bg)" }}>
                  <div className="text-[13.5px] font-medium">{plan.changes.length ? `${plan.changes.length} change(s) will be made` : "No changes — already up to date"}</div>
                  <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto text-[12.5px] muted">{plan.changes.map((c) => <li key={c}>• {c}</li>)}</ul>
                  <div className="mt-3 flex gap-2">
                    {plan.changes.length ? <button className="btn btn-green h-7" onClick={applyFile}>Apply</button> : null}
                    <button className="btn btn-ghost h-7" onClick={() => setPlan(null)}>Cancel</button>
                  </div>
                </div>
              ) : null}
            </div>
          </Panel>
          <Panel title="Change history">
            {!hist.data ? <Skeleton rows={3} /> : hist.data.items.length === 0 ? (
              <p className="px-4 py-5 text-[13.5px] muted">Using the default Balanced rules. Changes you save will be listed here.</p>
            ) : (
              <ol className="max-h-[360px] overflow-y-auto">
                {hist.data.items.map((h) => (
                  <li key={h.version} className="border-b px-4 py-2.5 last:border-0 hairline">
                    <div className="flex items-center justify-between text-[13.5px]"><span className="font-medium">Rules updated</span><span className="text-[12px] muted">{timeAgo(h.created_at)}</span></div>
                    <div className="text-[12.5px] muted"><span className="mono">{h.changed_by}</span> · via {h.source}{h.note ? ` · ${h.note}` : ""}</div>
                  </li>
                ))}
              </ol>
            )}
          </Panel>
        </aside>
      </div>

      {dirty ? (
        <div className="fixed inset-x-0 bottom-0 z-30 border-t px-5 py-3 slide-in md:left-[220px] hairline" style={{ background: "rgba(17,18,21,.92)", backdropFilter: "blur(8px)" }}>
          <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-3">
            <span className="text-[14px]">You have unsaved changes{presetName ? ` · ${PRESET_LABEL[presetName]} preset` : " · custom rules"}</span>
            <div className="flex gap-2">
              <button className="btn btn-ghost" onClick={() => setDraft(saved!)}>Discard</button>
              <button className="btn btn-green" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save rules"}</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
