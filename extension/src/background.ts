/**
 * Service worker: router and gatekeeper. The library itself lives in the offscreen document.
 *   - extension pages (app, popup) may do anything
 *   - AI-site content scripts may only submit captures and collect a handoff meant for their own tab;
 *     they can never read history
 *   - passphrase-mode session key: kept in chrome.storage.session (memory only, never on disk, hidden
 *     from content scripts) so the library can resume if Chrome restarts the offscreen document
 */
import { allowed, isTrusted } from "./trust";
import { PLATFORMS, type Platform } from "./core/types";
import type { BgRequest, LibRequest, Request, Response, Settings } from "./protocol";

const DEFAULT: Settings = {
  capture: { chatgpt: true, claude: true, gemini: true, perplexity: true },
  autoLockMinutes: 30,
  onboarded: false,
};
const LIB_TYPES = new Set(["state", "setupDevice", "setupPassphrase", "unlock", "recover", "resume", "lock", "changePassphrase", "switchMode", "search", "get", "recent", "upsert", "embedMissing", "delete", "deleteAll", "exportAll", "wipeEverything"]);

chrome.storage.session.setAccessLevel?.({ accessLevel: "TRUSTED_CONTEXTS" });

chrome.runtime.onInstalled.addListener((d) => {
  if (d.reason === "install") void chrome.tabs.create({ url: chrome.runtime.getURL("app.html#welcome") });
});

async function settings(): Promise<Settings> {
  const { settings: s } = await chrome.storage.local.get("settings");
  return { ...DEFAULT, ...(s ?? {}), capture: { ...DEFAULT.capture, ...(s?.capture ?? {}) } };
}

// ---- library host ------------------------------------------------------------------------------
let creating: Promise<void> | null = null;
async function ensureOffscreen(): Promise<void> {
  const url = chrome.runtime.getURL("offscreen.html");
  const existing = await chrome.runtime.getContexts({ contextTypes: [chrome.runtime.ContextType.OFFSCREEN_DOCUMENT], documentUrls: [url] });
  if (existing.length) return;
  creating ??= chrome.offscreen
    .createDocument({ url, reasons: [chrome.offscreen.Reason.WORKERS], justification: "Hold the encrypted search index and run the on-device embedding model" })
    .finally(() => (creating = null));
  await creating;
}

async function lib(req: LibRequest, retry = true): Promise<Response> {
  await ensureOffscreen();
  const r: Response | undefined = await chrome.runtime.sendMessage({ target: "lib", req });
  if (!r) {
    if (retry) {
      await new Promise((res) => setTimeout(res, 300)); // host still starting
      return lib(req, false);
    }
    return { ok: false, error: "Library host did not respond" };
  }
  if (!r.ok && /locked/i.test(r.error) && retry) {
    const { dek } = await chrome.storage.session.get("dek");
    if (dek) {
      await lib({ type: "resume", raw: dek }, false);
      return lib(req, false);
    }
  }
  return r;
}

// ---- auto-lock (passphrase mode) ---------------------------------------------------------------
chrome.alarms.create("autolock", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(async (a) => {
  if (a.name !== "autolock") return;
  const { autoLockMinutes } = await settings();
  const { lastActive, dek } = await chrome.storage.session.get(["lastActive", "dek"]);
  if (dek && autoLockMinutes > 0 && Date.now() - (lastActive ?? 0) > autoLockMinutes * 60_000) {
    await chrome.storage.session.remove("dek");
    await lib({ type: "lock" }, false);
  }
});

// ---- handoff -----------------------------------------------------------------------------------
async function startHandoff(platform: Platform, text: string): Promise<Response> {
  // Record first (tab unknown yet), so a fast-loading page can't ask before the handoff exists.
  await chrome.storage.session.set({ handoff: { tabId: null, platform, text, at: Date.now() } });
  const tab = await chrome.tabs.create({ url: PLATFORMS[platform].home });
  const { handoff } = await chrome.storage.session.get("handoff");
  if (handoff && handoff.tabId === null) await chrome.storage.session.set({ handoff: { ...handoff, tabId: tab.id } });
  return { ok: true };
}

async function takeHandoff(sender: chrome.runtime.MessageSender): Promise<Response> {
  const { handoff } = await chrome.storage.session.get("handoff");
  // Only the tab we opened for this handoff, within 2 minutes, exactly once.
  if (!handoff || handoff.tabId !== sender.tab?.id || Date.now() - handoff.at > 120_000) return { ok: true }; // not (yet) for this tab
  await chrome.storage.session.remove("handoff");
  return { ok: true, text: handoff.text };
}

// ---- router ------------------------------------------------------------------------------------
async function handle(req: Request, sender: chrome.runtime.MessageSender): Promise<Response> {
  const trusted = isTrusted(sender, chrome.runtime.id, chrome.runtime.getURL(""));
  if (!allowed(req.type, trusted)) return { ok: false, error: "not allowed from a web page" };
  if (trusted && req.type !== "state") await chrome.storage.session.set({ lastActive: Date.now() });

  if (LIB_TYPES.has(req.type)) {
    const r = await lib(req as LibRequest);
    if (r.ok && r.sessionKey !== undefined) await chrome.storage.session.set({ dek: r.sessionKey });
    if (r.ok && (req.type === "lock" || (req.type === "switchMode" && !r.sessionKey))) await chrome.storage.session.remove("dek");
    if (r.ok) delete r.sessionKey; // never hand the key to a page
    return r;
  }
  const b = req as BgRequest;
  switch (b.type) {
    case "settings": {
      const cur = await settings();
      if (!b.set) return { ok: true, settings: cur };
      const next = { ...cur, ...b.set, capture: { ...cur.capture, ...(b.set.capture ?? {}) } };
      await chrome.storage.local.set({ settings: next });
      return { ok: true, settings: next };
    }
    case "captureConv": {
      const c = b.conversation;
      if (!c || !PLATFORMS[c.platform] || !(await settings()).capture[c.platform]) return { ok: true };
      if (!Array.isArray(c.messages) || !c.messages.length || c.messages.length > 5000) return { ok: true };
      const clean = {
        ...c,
        id: `${c.platform}:${c.nativeId}`,
        source: "capture" as const,
        title: String(c.title).slice(0, 300),
        messages: c.messages.map((m) => ({ role: m.role === "user" ? "user" as const : "assistant" as const, text: String(m.text).slice(0, 200_000), at: m.at })),
      };
      const r = await lib({ type: "upsert", conversations: [clean] });
      return r.ok ? { ok: true } : r; // content scripts learn nothing about the library
    }
    case "handoff":
      return startHandoff(b.platform, b.text);
    case "takeHandoff":
      return takeHandoff(sender);
  }
}

chrome.runtime.onMessage.addListener((req: Request & { target?: string }, sender, reply) => {
  if (req?.target === "lib") return false; // addressed to the library host
  handle(req, sender)
    .then(reply)
    .catch((e: Error) => reply({ ok: false, error: e.message }));
  return true;
});

chrome.commands?.onCommand.addListener((cmd) => {
  if (cmd === "open-app") void chrome.tabs.create({ url: chrome.runtime.getURL("app.html") });
});
