// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
"use client";
import { useState } from "react";
import { ApiError, api, timeAgo, toast, useLive } from "@/lib/client";
import { Empty, PageHeader, Panel, Skeleton } from "@/components/ui";

interface Row { calls: number; input_tokens: number; output_tokens: number; cost_usd: number | null; unpriced: number; estimated: number; provider?: string; model_id?: string; agent_id?: string }
interface Usage { totals: Row; by_model: Row[]; by_agent: Row[] }
interface Price { provider: string; model_id: string; input_usd_per_mtok: number; output_usd_per_mtok: number; updated_by: string; updated_at: string }

const RANGES = [["24h", "24 hours"], ["7d", "7 days"], ["30d", "30 days"]] as const;
const n = (x: number) => x.toLocaleString();
const usd = (x: number | null, unpriced: number) => (x === null ? (unpriced ? "no price set" : "–") : `$${x < 1 ? x.toFixed(4) : x.toFixed(2)}`);

function UsageTable({ rows, label }: { rows: Row[]; label: (r: Row) => React.ReactNode }) {
  if (rows.length === 0) return <Empty>No model calls in this period.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="tbl">
        <thead><tr><th /><th className="text-right">Calls</th><th className="text-right">Input tokens</th><th className="text-right">Output tokens</th><th className="text-right">Estimated cost</th><th>Counts</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{label(r)}</td>
              <td className="tnum text-right">{n(r.calls)}</td>
              <td className="tnum text-right">{n(r.input_tokens)}</td>
              <td className="tnum text-right">{n(r.output_tokens)}</td>
              <td className="tnum text-right">{usd(r.cost_usd, r.unpriced)}</td>
              <td className="muted text-[12.5px]">{r.estimated === r.calls ? "estimated" : r.estimated ? "partly estimated" : "reported"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function UsagePage() {
  const [range, setRange] = useState<(typeof RANGES)[number][0]>("7d");
  const usage = useLive<Usage>(`v1/usage?range=${range}`, 20000);
  const prices = useLive<{ items: Price[]; unpriced_models: { provider: string; model_id: string }[] }>("v1/model-prices", 30000);
  const [form, setForm] = useState({ provider: "", model_id: "", input: "", output: "" });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api("v1/model-prices", { method: "PUT", json: {
        provider: form.provider.trim(), model_id: form.model_id.trim(),
        input_usd_per_mtok: Number(form.input), output_usd_per_mtok: Number(form.output),
      } });
      toast("Price saved. It applies to model calls from now on.", "ok");
      setForm({ provider: "", model_id: "", input: "", output: "" });
      prices.reload();
    } catch (err) { toast(err instanceof ApiError ? err.message : "Could not save the price", "bad"); }
  }

  const t = usage.data?.totals;
  return (
    <>
      <PageHeader title="Usage" subtitle="Model tokens and estimated cost. Costs come from the prices you set below, not from your provider's bill."
                  actions={<div className="seg" role="group" aria-label="Time range">{RANGES.map(([v, l]) => <button key={v} data-active={range === v} onClick={() => setRange(v)}>{l}</button>)}</div>} />

      <section className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ["Model calls", t ? n(t.calls) : "–"],
          ["Input tokens", t ? n(t.input_tokens) : "–"],
          ["Output tokens", t ? n(t.output_tokens) : "–"],
          ["Estimated cost", t ? usd(t.cost_usd, t.unpriced) : "–"],
        ].map(([k, v]) => (
          <div key={k} className="panel px-4 py-3"><div className="text-[12.5px] muted">{k}</div><div className="mt-1.5 text-[19px] tnum">{v}</div></div>
        ))}
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="By model">{!usage.data ? <Skeleton rows={3} /> : <UsageTable rows={usage.data.by_model} label={(r) => <span className="mono text-[12.5px]">{r.provider}/{r.model_id}</span>} />}</Panel>
        <Panel title="By agent, most recently active">{!usage.data ? <Skeleton rows={3} /> : <UsageTable rows={usage.data.by_agent} label={(r) => <span className="mono text-[12.5px]">{r.agent_id}</span>} />}</Panel>
      </div>

      <Panel className="mt-4" title="Model prices">
        <div className="grid gap-6 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <form className="flex flex-col gap-3" onSubmit={save}>
            <p className="text-[13px] text-2">Set what each model costs you, per million tokens. Aegis ships no prices because providers change them.</p>
            {prices.data?.unpriced_models.length ? (
              <div className="text-[12.5px] muted">Used but not priced:{" "}
                {prices.data.unpriced_models.map((m) => (
                  <button key={`${m.provider}/${m.model_id}`} type="button" className="mono underline decoration-dotted underline-offset-4 hover:text-[var(--text)]"
                          onClick={() => setForm((f) => ({ ...f, provider: m.provider, model_id: m.model_id }))}>{m.provider}/{m.model_id} </button>
                ))}
              </div>
            ) : null}
            <div className="grid grid-cols-2 gap-3">
              <label className="flex flex-col gap-1 text-[12.5px] muted">Provider<input id="price-provider" className="input" required value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })} placeholder="openai-compatible" /></label>
              <label className="flex flex-col gap-1 text-[12.5px] muted">Model<input id="price-model" className="input" required value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })} placeholder="model name" /></label>
              <label className="flex flex-col gap-1 text-[12.5px] muted">Input, USD per 1M tokens<input id="price-in" className="input" required inputMode="decimal" value={form.input} onChange={(e) => setForm({ ...form, input: e.target.value })} /></label>
              <label className="flex flex-col gap-1 text-[12.5px] muted">Output, USD per 1M tokens<input id="price-out" className="input" required inputMode="decimal" value={form.output} onChange={(e) => setForm({ ...form, output: e.target.value })} /></label>
            </div>
            <button className="btn btn-green h-9 justify-center" type="submit">Save price</button>
          </form>
          {!prices.data ? <Skeleton rows={3} /> : prices.data.items.length === 0 ? <Empty>No prices set yet.</Empty> : (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead><tr><th>Model</th><th className="text-right">Input / 1M</th><th className="text-right">Output / 1M</th><th>Updated</th></tr></thead>
                <tbody>
                  {prices.data.items.map((p) => (
                    <tr key={`${p.provider}/${p.model_id}`}>
                      <td className="mono text-[12.5px]">{p.provider}/{p.model_id}</td>
                      <td className="tnum text-right">${p.input_usd_per_mtok}</td>
                      <td className="tnum text-right">${p.output_usd_per_mtok}</td>
                      <td className="muted">{timeAgo(p.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Panel>
    </>
  );
}
