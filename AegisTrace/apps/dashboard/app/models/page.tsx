// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
"use client";
import { useState } from "react";
import { ApiError, api, timeAgo, toast, useLive } from "@/lib/client";
import { Badge, Empty, PageHeader, Panel, Skeleton } from "@/components/ui";

interface Model {
  id: string; name: string; provider: string; base_url: string | null; model_id: string; has_key: boolean;
  allow_private_network: boolean; status: string; last_check_at: string | null; last_check_detail: string | null;
  agents: number; runnable: boolean;
}

const PROVIDERS: [string, string, string][] = [
  ["openai-compatible", "OpenAI-compatible", "OpenAI, vLLM, llama.cpp server, and other /v1 chat APIs. Base URL ends in /v1."],
  ["ollama", "Ollama", "Local models. Default address http://host.docker.internal:11434 (enable private network)."],
  ["anthropic", "Anthropic", "Connection test only. Running agents on Anthropic needs an adapter that is not built yet."],
  ["mock", "Demo model", "Deterministic, for trying Aegis without a provider."],
];

export default function ModelHub() {
  const models = useLive<{ items: Model[] }>("v1/models", 20000);
  const [f, setF] = useState({ name: "", provider: "openai-compatible", model_id: "", base_url: "", api_key: "", allow_private_network: false });
  const [busy, setBusy] = useState<string | null>(null);
  const hint = PROVIDERS.find(([v]) => v === f.provider)?.[2];

  async function register(e: React.FormEvent) {
    e.preventDefault();
    setBusy("register");
    try {
      await api("v1/models", { method: "POST", json: { ...f, base_url: f.base_url.trim() || null, api_key: f.api_key || null } });
      toast("Model registered. Test the connection next.", "ok");
      setF({ ...f, name: "", model_id: "", api_key: "" });
      models.reload();
    } catch (err) { toast(err instanceof ApiError ? err.message : "Could not register the model", "bad"); }
    finally { setBusy(null); }
  }

  async function test(id: string) {
    setBusy(id);
    try {
      const r = await api<{ status: string; detail: string }>(`v1/models/${id}/test`, { method: "POST" });
      toast(r.detail, r.status === "connected" ? "ok" : "bad");
      models.reload();
    } catch (err) { toast(err instanceof ApiError ? err.message : "Test failed", "bad"); }
    finally { setBusy(null); }
  }

  async function remove(id: string) {
    try { await api(`v1/models/${id}`, { method: "DELETE" }); toast("Model removed", "ok"); models.reload(); }
    catch (err) { toast(err instanceof ApiError ? err.message : "Could not remove the model", "bad"); }
  }

  return (
    <>
      <PageHeader title="Model Hub" subtitle="The models your agents can use. Provider keys are stored encrypted and never shown again. A model counts as connected only after a successful test." />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Panel title="Registered models">
          {!models.data ? <Skeleton rows={3} /> : models.data.items.length === 0 ? <Empty>No models yet. Register one on the right.</Empty> : (
            <ul className="divide-y hairline">
              {models.data.items.map((m) => (
                <li key={m.id} className="flex flex-wrap items-start gap-3 px-4 py-3">
                  <div className="min-w-[220px] flex-1">
                    <p className="text-[14px] font-medium">{m.name}</p>
                    <p className="mono text-[12px] muted">{m.provider} · {m.model_id}{m.base_url ? ` · ${m.base_url}` : ""}</p>
                    <p className="mt-1 text-[12.5px] text-2">
                      {m.last_check_detail ?? "Not tested yet."}{m.last_check_at ? <span className="muted"> · {timeAgo(m.last_check_at)}</span> : null}
                    </p>
                    <p className="mt-1 text-[12px] muted">
                      {m.has_key ? "key stored" : "no key"} · {m.runnable ? "agents can run on it" : "connection test only"} · used by {m.agents} agent{m.agents === 1 ? "" : "s"}
                    </p>
                  </div>
                  <Badge value={m.status === "connected" ? "active" : m.status === "failed" ? "rejected" : "pending"} label={m.status} />
                  <button className="btn" type="button" disabled={busy === m.id} onClick={() => test(m.id)}>{busy === m.id ? "Testing" : "Test connection"}</button>
                  <button className="btn btn-ghost" type="button" disabled={m.agents > 0} title={m.agents ? "Switch its agents to another model first" : undefined} onClick={() => remove(m.id)}>Remove</button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Register a model">
          <form className="flex flex-col gap-3 p-4" onSubmit={register}>
            <label className="flex flex-col gap-1 text-[12.5px] muted">Provider
              <select id="model-provider" className="input" value={f.provider} onChange={(e) => setF({ ...f, provider: e.target.value })}>
                {PROVIDERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            {hint ? <p className="text-[12.5px] text-2">{hint}</p> : null}
            <label className="flex flex-col gap-1 text-[12.5px] muted">Name<input id="model-name" className="input" required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. production-chat" /></label>
            <label className="flex flex-col gap-1 text-[12.5px] muted">Model ID<input id="model-id" className="input mono" required value={f.model_id} onChange={(e) => setF({ ...f, model_id: e.target.value })} placeholder="as the provider names it" /></label>
            {f.provider !== "mock" ? (
              <>
                <label className="flex flex-col gap-1 text-[12.5px] muted">Base URL<input id="model-url" className="input mono" value={f.base_url} onChange={(e) => setF({ ...f, base_url: e.target.value })} placeholder={f.provider === "openai-compatible" ? "https://…/v1" : "default"} /></label>
                <label className="flex flex-col gap-1 text-[12.5px] muted">API key<input id="model-key" className="input mono" type="password" autoComplete="off" value={f.api_key} onChange={(e) => setF({ ...f, api_key: e.target.value })} placeholder="stored encrypted" /></label>
                <label className="flex items-center gap-2 text-[13px]"><input id="model-private" type="checkbox" className="h-4 w-4 accent-[var(--green)]" checked={f.allow_private_network} onChange={(e) => setF({ ...f, allow_private_network: e.target.checked })} />Allow a private network address (local or internal servers)</label>
              </>
            ) : null}
            <button className="btn btn-green h-9 justify-center" type="submit" disabled={busy === "register"}>Register</button>
          </form>
        </Panel>
      </div>
    </>
  );
}
