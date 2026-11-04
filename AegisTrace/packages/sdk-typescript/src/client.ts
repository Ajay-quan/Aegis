// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 AegisTrace contributors
import { randomUUID } from "node:crypto";
import { AegisError, errorFromResponse } from "./errors.js";
import type { Agent, Approval, ExecutionEvent, Page, ReplayReport, Run, RunState } from "./types.js";

export interface ClientOptions {
  baseUrl: string;
  token: string;
  timeoutMs?: number;
  maxRetries?: number;
  backoffMs?: number;
  fetch?: typeof fetch;
}

const RETRY_STATUS = new Set([429, 502, 503, 504]);
const TERMINAL: ReadonlySet<RunState> = new Set([
  "SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT", "WAITING_FOR_APPROVAL", "NEEDS_RECONCILIATION",
]);

/** Same semantics as the Python SDK: retries only idempotent requests. */
export class AegisClient {
  readonly #token: string;
  readonly #fetch: typeof fetch;
  readonly baseUrl: string;
  readonly timeoutMs: number;
  readonly maxRetries: number;
  readonly backoffMs: number;

  constructor(opts: ClientOptions) {
    const url = opts.baseUrl.replace(/\/+$/, "");
    if (!url.startsWith("https://") && !/^http:\/\/(127\.0\.0\.1|localhost)(:|\/|$)/.test(url)) {
      throw new Error("baseUrl must use https (plain http is only allowed for localhost)");
    }
    this.baseUrl = url;
    this.#token = opts.token;
    this.#fetch = opts.fetch ?? fetch;
    this.timeoutMs = opts.timeoutMs ?? 30_000;
    this.maxRetries = opts.maxRetries ?? 3;
    this.backoffMs = opts.backoffMs ?? 500;
  }

  toJSON(): Record<string, string> {
    return { baseUrl: this.baseUrl }; // never serialize the token
  }

  async #request<T>(method: string, path: string, opts: {
    body?: unknown; query?: Record<string, string | number | undefined>; headers?: Record<string, string>;
    retrySafe: boolean; binary?: boolean;
  }): Promise<T> {
    const url = new URL(this.baseUrl + path);
    for (const [k, v] of Object.entries(opts.query ?? {})) if (v !== undefined) url.searchParams.set(k, String(v));
    for (let attempt = 0; ; attempt++) {
      let resp: Response | undefined;
      try {
        const init: RequestInit = {
          method,
          headers: {
            Authorization: `Bearer ${this.#token}`,
            "User-Agent": "aegistrace-sdk-typescript/0.1.0",
            ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}),
            ...opts.headers,
          },
          signal: AbortSignal.timeout(this.timeoutMs),
        };
        if (opts.body !== undefined) init.body = JSON.stringify(opts.body);
        resp = await this.#fetch(url, init);
      } catch (err) {
        if (!opts.retrySafe || attempt >= this.maxRetries) throw err;
      }
      if (resp && (!RETRY_STATUS.has(resp.status) || !opts.retrySafe || attempt >= this.maxRetries)) {
        if (resp.status >= 400) {
          let body: unknown = {};
          try { body = await resp.json(); } catch { /* non-JSON error body */ }
          throw errorFromResponse(resp.status, body);
        }
        if (opts.binary) return new Uint8Array(await resp.arrayBuffer()) as T;
        return (await resp.json()) as T;
      }
      const retryAfter = Number(resp?.headers.get("retry-after"));
      const delay = Number.isFinite(retryAfter) && retryAfter > 0
        ? Math.min(retryAfter * 1000, 30_000) : Math.random() * this.backoffMs * 2 ** attempt;
      await new Promise((r) => setTimeout(r, delay));
    }
  }

  listAgents(): Promise<Agent[]> {
    return this.#request<Page<Agent>>("GET", "/v1/agents", { retrySafe: true }).then((p) => p.items);
  }
  createProject(name: string): Promise<{ id: string; name: string }> {
    return this.#request("POST", "/v1/projects", { body: { name }, retrySafe: false });
  }
  registerAgent(projectId: string, name: string, modelProvider = "mock", modelId = "mock-deterministic-1"): Promise<Agent> {
    return this.#request("POST", "/v1/agents", {
      body: { project_id: projectId, name, model_provider: modelProvider, model_id: modelId }, retrySafe: false,
    });
  }
  grantTool(agentId: string, tool: string, maxRiskClass: number, allowedHosts: string[] = []): Promise<unknown> {
    return this.#request("PUT", `/v1/agents/${encodeURIComponent(agentId)}/grants`, {
      body: { tool, max_risk_class: maxRiskClass, allowed_hosts: allowedHosts }, retrySafe: true,
    });
  }
  submitRun(agentId: string, input: Record<string, unknown>, idempotencyKey?: string): Promise<{ id: string; created: boolean }> {
    return this.#request("POST", "/v1/runs", {
      body: { agent_id: agentId, input }, retrySafe: true,
      headers: { "Idempotency-Key": idempotencyKey ?? `sdk-${randomUUID()}` },
    });
  }
  getRun(runId: string): Promise<Run> {
    return this.#request("GET", `/v1/runs/${encodeURIComponent(runId)}`, { retrySafe: true });
  }
  listRuns(opts: { state?: RunState; limit?: number; cursor?: string } = {}): Promise<Page<Run>> {
    return this.#request("GET", "/v1/runs", { query: { state: opts.state, limit: opts.limit, cursor: opts.cursor }, retrySafe: true });
  }
  async *iterRuns(state?: RunState): AsyncGenerator<Run> {
    let cursor: string | undefined;
    do {
      const page: Page<Run> = await this.listRuns({ ...(state ? { state } : {}), ...(cursor ? { cursor } : {}) });
      yield* page.items;
      cursor = page.next_cursor ?? undefined;
    } while (cursor);
  }
  async waitForRun(runId: string, timeoutMs = 60_000, pollMs = 500): Promise<Run> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const run = await this.getRun(runId);
      if (TERMINAL.has(run.state) || Date.now() > deadline) return run;
      await new Promise((r) => setTimeout(r, pollMs));
    }
  }
  events(runId: string): Promise<ExecutionEvent[]> {
    return this.#request<Page<ExecutionEvent>>("GET", `/v1/runs/${encodeURIComponent(runId)}/events`, { retrySafe: true })
      .then((p) => p.items);
  }
  cancelRun(runId: string): Promise<unknown> {
    return this.#request("POST", `/v1/runs/${encodeURIComponent(runId)}/cancel`, { retrySafe: false });
  }
  exportReceipt(runId: string): Promise<Uint8Array> {
    return this.#request("GET", `/v1/runs/${encodeURIComponent(runId)}/receipt`, { retrySafe: true, binary: true });
  }
  replay(runId: string): Promise<ReplayReport> {
    return this.#request("GET", `/v1/runs/${encodeURIComponent(runId)}/replay`, { retrySafe: true });
  }
  listApprovals(status: Approval["status"] = "pending"): Promise<Approval[]> {
    return this.#request<Page<Approval>>("GET", "/v1/approvals", { query: { status }, retrySafe: true }).then((p) => p.items);
  }
  decideApproval(approvalId: string, approve: boolean): Promise<{ id: string; status: string }> {
    return this.#request("POST", `/v1/approvals/${encodeURIComponent(approvalId)}/decision`, { body: { approve }, retrySafe: false });
  }
}

export { AegisError };
