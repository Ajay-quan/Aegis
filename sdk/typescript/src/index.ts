/**
 * Official TypeScript client for AegisMem.
 *
 *   const mem = new AegisMem({ baseUrl: "https://aegismem.internal", apiKey: process.env.AEGISMEM_API_KEY });
 *   const w = await mem.ingest({ text: "User prefers aisle seats", userId: "u1" });
 *   const r = await mem.retrieve({ query: "seat preference", userId: "u1" });
 *   await mem.feedback({ retrievalId: r.retrieval_id, userId: "u1", used: [r.results[0]!.memory_id] });
 *
 * Retry policy matches the Python SDK: reads are retried on network errors, 429 and 5xx with
 * backoff; state-creating writes carry a stable auto-generated Idempotency-Key so the server
 * executes them at most once, which makes them safe to retry too.
 */

export type SourceType =
  | "user_message" | "agent_observation" | "tool_output" | "ingestion" | "reflection" | "system";

export interface WriteResult {
  memory_id: string;
  user_id: string;
  memory_type: string;
  importance_score: number;
  content_preview: string;
  created_at: string;
  status: "active" | "pending" | string;
  quarantine_reason: string | null;
  trust: number | null;
}

export interface Memory {
  memory_id: string;
  content: string;
  memory_type: string;
  importance_score: number;
  semantic_score: number;
  composite_score: number;
  rank: number;
  created_at: string;
}

export interface RetrieveResult {
  retrieval_id: string;
  query: string;
  results: Memory[];
  total_found: number;
  latency_ms: number;
  context_window: string;
  guard_report: Array<Record<string, unknown>>;
}

export interface FeedbackResult {
  accepted: number;
  used: number;
  learning_active: boolean;
  weights: Record<string, number>;
}

export interface HandoffPacket {
  user_id: string;
  token_budget: number;
  tokens_used: number;
  sections: Record<string, Array<Record<string, unknown>>>;
  omitted: Record<string, number>;
  markdown: string;
}

export interface ErasureReceipt {
  body: { receipt_id: string; verified: boolean; erased: Array<{ memory_id: string; relation: string }> } & Record<string, unknown>;
  signature: string;
  alg: string;
}

export interface CorrectionResult {
  corrected_memory_id: string;
  replacement_memory_id: string | null;
  kind: string;
  source_trust_after: number | null;
  flagged_derived: string[];
  receipt_id: string | null;
}

export interface QuarantineItem {
  memory_id: string;
  content: string;
  reason: string;
  trust: number;
  source: string;
  created_at: string;
}

export class AegisMemError extends Error {
  readonly status?: number;
  readonly body?: unknown;
  readonly requestId?: string;

  constructor(message: string, status?: number, body?: unknown, requestId?: string) {
    super(message);
    this.name = new.target.name;
    this.status = status;
    this.body = body;
    this.requestId = requestId;
  }
}
export class AuthenticationError extends AegisMemError {}
export class PermissionDeniedError extends AegisMemError {}
export class NotFoundError extends AegisMemError {}
export class ValidationError extends AegisMemError {}
export class RateLimitedError extends AegisMemError {}
export class ServerError extends AegisMemError {}

function errorFor(status: number, message: string, body: unknown, requestId?: string): AegisMemError {
  const cls =
    status === 401 ? AuthenticationError :
    status === 403 ? PermissionDeniedError :
    status === 404 ? NotFoundError :
    status === 409 || status === 422 ? ValidationError :
    status === 429 ? RateLimitedError :
    status >= 500 ? ServerError : AegisMemError;
  return new cls(message, status, body, requestId);
}

export interface AegisMemOptions {
  baseUrl?: string;
  apiKey?: string;
  maxRetries?: number;
  timeoutMs?: number;
  fetch?: typeof fetch;
}

interface RequestOptions {
  body?: unknown;
  query?: Record<string, string>;
  idempotent: boolean;
  idempotencyKey?: string;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export class AegisMem {
  private readonly base: string;
  private readonly apiKey?: string;
  private readonly maxRetries: number;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: AegisMemOptions = {}) {
    const env = typeof process !== "undefined" ? process.env : {};
    this.base = (opts.baseUrl ?? env.AEGISMEM_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "") + "/api/v1";
    this.apiKey = opts.apiKey ?? env.AEGISMEM_API_KEY;
    this.maxRetries = opts.maxRetries ?? 3;
    this.timeoutMs = opts.timeoutMs ?? 10_000;
    this.fetchImpl = opts.fetch ?? globalThis.fetch;
  }

  private async request<T>(method: string, path: string, o: RequestOptions): Promise<T> {
    const url = new URL(this.base + path);
    for (const [k, v] of Object.entries(o.query ?? {})) url.searchParams.set(k, v);
    const headers: Record<string, string> = { "user-agent": "aegismem-ts/0.1.0" };
    if (this.apiKey) headers.authorization = `Bearer ${this.apiKey}`;
    if (o.body !== undefined) headers["content-type"] = "application/json";
    if (o.idempotencyKey) headers["idempotency-key"] = o.idempotencyKey;
    const retryable = o.idempotent || o.idempotencyKey !== undefined;

    for (let attempt = 0; ; attempt++) {
      let resp: Response;
      try {
        resp = await this.fetchImpl(url, {
          method, headers,
          body: o.body === undefined ? undefined : JSON.stringify(o.body),
          signal: AbortSignal.timeout(this.timeoutMs),
        });
      } catch (e) {
        // fetch does not tell us whether the request reached the server; only retry when safe.
        if (!retryable || attempt >= this.maxRetries) throw new AegisMemError(`network error: ${String(e)}`);
        await sleep(this.backoff(attempt));
        continue;
      }
      if (resp.ok) return (resp.status === 204 ? undefined : await resp.json()) as T;

      const requestId = resp.headers.get("x-request-id") ?? undefined;
      let body: unknown = await resp.text();
      try { body = JSON.parse(body as string); } catch { /* keep text */ }
      const inFlight = resp.status === 409 && o.idempotencyKey !== undefined;
      const transient = resp.status === 429 || resp.status >= 500 || inFlight;
      if (transient && retryable && attempt < this.maxRetries) {
        const ra = Number(resp.headers.get("retry-after"));
        await sleep(Number.isFinite(ra) && ra > 0 ? Math.min(ra * 1000, 30_000) : this.backoff(attempt));
        continue;
      }
      const detail = typeof body === "object" && body && "detail" in body ? (body as { detail: unknown }).detail : body;
      throw errorFor(resp.status, `${resp.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`, body, requestId);
    }
  }

  private backoff(attempt: number): number {
    return Math.min(8000, 250 * 2 ** attempt) * (0.5 + Math.random());
  }

  // -- memory ------------------------------------------------------------

  ingest(p: { text: string; userId: string; sessionId?: string; agentId?: string; memoryType?: string;
              sourceType?: SourceType; origin?: string; metadata?: Record<string, unknown>;
              idempotencyKey?: string; eventTime?: string }): Promise<WriteResult> {
    const metadata = { ...(p.metadata ?? {}), ...(p.origin ? { origin: p.origin } : {}) };
    return this.request("POST", "/ingest", {
      idempotent: false, idempotencyKey: p.idempotencyKey ?? `sdk-${crypto.randomUUID()}`,
      body: { text: p.text, user_id: p.userId, session_id: p.sessionId ?? "", agent_id: p.agentId ?? "",
              memory_type: p.memoryType ?? "observation", source_type: p.sourceType ?? "user_message", metadata,
              event_time: p.eventTime ?? null },
    });
  }

  retrieve(p: { query: string; userId: string; topK?: number; namespace?: string; memoryTypes?: string[];
                minImportance?: number }): Promise<RetrieveResult> {
    return this.request("POST", "/retrieve", {
      idempotent: true,
      body: { query: p.query, user_id: p.userId, top_k: p.topK ?? 5, namespace: p.namespace ?? "",
              memory_types: p.memoryTypes ?? [], min_importance: p.minImportance ?? 0 },
    });
  }

  feedback(p: { retrievalId: string; userId: string; used: string[] }): Promise<FeedbackResult> {
    return this.request("POST", "/feedback", {
      idempotent: true, body: { retrieval_id: p.retrievalId, user_id: p.userId, used_memory_ids: p.used },
    });
  }

  handoff(p: { userId: string; task?: string; since?: string; tokenBudget?: number; namespace?: string }): Promise<HandoffPacket> {
    return this.request("POST", "/handoff", {
      idempotent: true,
      body: { user_id: p.userId, task: p.task ?? "", since: p.since ?? null,
              token_budget: p.tokenBudget ?? 1500, namespace: p.namespace ?? "" },
    });
  }

  // -- outcomes (continual learning) ---------------------------------------

  correct(p: { memoryId: string; userId: string; kind: "wrong" | "outdated" | "malicious";
               correctedText?: string; note?: string }): Promise<CorrectionResult> {
    return this.request("POST", "/corrections", {
      idempotent: false, idempotencyKey: `sdk-${crypto.randomUUID()}`,
      body: { memory_id: p.memoryId, user_id: p.userId, kind: p.kind,
              corrected_text: p.correctedText ?? "", note: p.note ?? "" },
    });
  }

  confirm(p: { memoryId: string; userId: string }): Promise<Record<string, unknown>> {
    return this.request("POST", `/memories/${encodeURIComponent(p.memoryId)}/confirm`,
      { idempotent: false, query: { user_id: p.userId } });
  }

  // -- review --------------------------------------------------------------

  async quarantine(userId: string): Promise<QuarantineItem[]> {
    const r = await this.request<{ items: QuarantineItem[] }>("GET", `/quarantine/${encodeURIComponent(userId)}`, { idempotent: true });
    return r.items;
  }

  release(p: { memoryId: string; userId: string }): Promise<Record<string, unknown>> {
    return this.request("POST", `/quarantine/${encodeURIComponent(p.memoryId)}/release`,
      { idempotent: false, query: { user_id: p.userId } });
  }

  reject(p: { memoryId: string; userId: string }): Promise<Record<string, unknown>> {
    return this.request("POST", `/quarantine/${encodeURIComponent(p.memoryId)}/reject`,
      { idempotent: false, query: { user_id: p.userId } });
  }

  // -- privacy ---------------------------------------------------------------

  forget(p: { userId: string; memoryIds?: string[]; allForUser?: boolean; reason?: string }): Promise<ErasureReceipt> {
    return this.request("POST", "/forget", {
      idempotent: false, idempotencyKey: `sdk-${crypto.randomUUID()}`,
      body: { user_id: p.userId, memory_ids: p.memoryIds ?? [], all_for_user: p.allForUser ?? false, reason: p.reason ?? "" },
    });
  }

  getReceipt(receiptId: string): Promise<ErasureReceipt> {
    return this.request("GET", `/receipts/${encodeURIComponent(receiptId)}`, { idempotent: true });
  }

  async verifyReceipt(receipt: ErasureReceipt): Promise<boolean> {
    return (await this.request<{ valid: boolean }>("POST", "/receipts/verify", { idempotent: true, body: receipt })).valid;
  }

  async trustSources(): Promise<Array<Record<string, unknown>>> {
    return (await this.request<{ sources: Array<Record<string, unknown>> }>("GET", "/trust/sources", { idempotent: true })).sources;
  }
}
