import type { KeyMode } from "./core/keys";
import type { Progress, Result, UpsertReport } from "./core/library";
import type { SearchOptions } from "./core/index";
import type { Conversation, Platform } from "./core/types";

/** Requests served by the library host (offscreen document). */
export type LibRequest =
  | { type: "state" }
  | { type: "setupDevice" }
  | { type: "setupPassphrase"; passphrase: string }
  | { type: "unlock"; passphrase: string }
  | { type: "recover"; recoveryKey: string; newPassphrase: string }
  | { type: "resume"; raw: string }
  | { type: "lock" }
  | { type: "changePassphrase"; current: string; next: string }
  | { type: "switchMode"; to: KeyMode; passphrase?: string }
  | { type: "search"; query: string; opts?: SearchOptions }
  | { type: "get"; id: string }
  | { type: "recent"; limit?: number; platform?: Platform }
  | { type: "upsert"; conversations: Conversation[] }
  | { type: "embedMissing" }
  | { type: "delete"; id: string }
  | { type: "deleteAll" }
  | { type: "exportAll" }
  | { type: "wipeEverything" };

/** Requests served by the service worker itself. */
export type BgRequest =
  | { type: "settings"; set?: Partial<Settings> }
  | { type: "captureConv"; conversation: Conversation } // from content scripts
  | { type: "handoff"; platform: Platform; text: string } // opens the target AI with text ready
  | { type: "takeHandoff" }; // from the content script in the tab opened for a handoff

export type Request = LibRequest | BgRequest;

export interface Settings {
  capture: Record<Platform, boolean>;
  autoLockMinutes: number;
  onboarded: boolean;
}

export interface LibState {
  exists: boolean;
  mode: KeyMode | null;
  unlocked: boolean;
  search: "hybrid" | "keyword";
  model: "loading" | "ready" | "unavailable";
  modelError?: string;
  stats?: { conversations: number; messages: number; chunks: number; embedded: number; byPlatform: Record<string, number> };
}

export type Response =
  | {
      ok: true;
      state?: LibState;
      results?: Result[];
      conversation?: Conversation;
      conversations?: Conversation[];
      report?: UpsertReport;
      recoveryKey?: string;
      sessionKey?: string;
      settings?: Settings;
      text?: string;
      removed?: boolean;
      count?: number;
      progress?: Progress;
    }
  | { ok: false; error: string };

export function send(req: Request): Promise<Response> {
  return chrome.runtime.sendMessage(req);
}
