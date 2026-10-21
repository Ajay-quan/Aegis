import type { Category } from "./core/analyze";
import type { Memory, Receipt } from "./core/vault";

export interface Settings {
  capture: Record<string, boolean>; // per site, off until the user turns it on
  autoLockMinutes: number; // 0 = never
}

export type Request =
  | { type: "status" }
  | { type: "setup"; passphrase: string }
  | { type: "unlock"; passphrase: string }
  | { type: "recover"; recoveryKey: string; newPassphrase: string }
  | { type: "lock" }
  | { type: "changePassphrase"; current: string; next: string }
  | { type: "capture"; text: string; site: string; url: string }
  | { type: "context"; query: string }
  | { type: "list" }
  | { type: "add"; text: string }
  | { type: "approve"; id: string }
  | { type: "edit"; id: string; text: string }
  | { type: "category"; id: string; category: Category }
  | { type: "forget"; id: string }
  | { type: "forgetAll" }
  | { type: "export" }
  | { type: "settings"; set?: Partial<Settings> };

export interface Status {
  exists: boolean;
  unlocked: boolean;
  settings: Settings;
  search: "hybrid" | "keyword";
  model: "unknown" | "ready" | "unavailable";
  modelError?: string;
}

export type Response =
  | { ok: true; status?: Status; recoveryKey?: string; memories?: Memory[]; context?: string; receipt?: Receipt; json?: string; count?: number; settings?: Settings }
  | { ok: false; error: string };

export function send(req: Request): Promise<Response> {
  return chrome.runtime.sendMessage(req);
}
