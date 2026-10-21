/**
 * Service worker: the only place the vault is unlocked. Content scripts never see the key or the
 * full memory list; they only send captured text and receive a context block for one prompt.
 * The unlocked data key is kept in chrome.storage.session (memory only, never written to disk,
 * not readable by content scripts) so a restarted worker does not force a re-unlock.
 */
import { Vault } from "./core/vault";
import { b64, unb64 } from "./core/crypto";
import type { Request, Response, Settings } from "./messages";
import { ADAPTERS } from "./content/adapters";
import { allowed, isTrusted } from "./trust";

const vault = new Vault();

// On-device embeddings run in an offscreen document (WebAssembly ML is not reliable in a service worker).
let creating: Promise<void> | null = null;
async function ensureOffscreen(): Promise<void> {
  const url = chrome.runtime.getURL("offscreen.html");
  const existing = await chrome.runtime.getContexts?.({ contextTypes: ["OFFSCREEN_DOCUMENT" as chrome.runtime.ContextType], documentUrls: [url] });
  if (existing?.length) return;
  creating ??= chrome.offscreen
    .createDocument({ url, reasons: [chrome.offscreen.Reason.WORKERS], justification: "Run the on-device embedding model" })
    .finally(() => (creating = null));
  await creating;
}
vault.embedder = async (texts) => {
  await ensureOffscreen();
  const r = await chrome.runtime.sendMessage({ target: "offscreen", type: "embed", texts });
  if (!r?.ok) throw new Error(r?.error ?? "embedding failed");
  return r.vectors;
};
let modelStatus: "unknown" | "ready" | "unavailable" = "unknown";
let modelError = "";
async function warmModel(): Promise<void> {
  try {
    await vault.embedder!(["warm up"]);
    modelStatus = "ready";
    await vault.embedMissing();
  } catch (e) {
    modelStatus = "unavailable";
    modelError = (e as Error).message;
    console.error("AegisMem: embedding model unavailable:", modelError);
  }
}
const DEFAULT: Settings = {
  capture: Object.fromEntries(ADAPTERS.map((a) => [a.site, false])),
  autoLockMinutes: 30,
};

chrome.storage.session.setAccessLevel?.({ accessLevel: "TRUSTED_CONTEXTS" });
chrome.runtime.onInstalled.addListener((d) => {
  if (d.reason === "install") void chrome.tabs.create({ url: chrome.runtime.getURL("panel.html?welcome=1") });
});
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

async function settings(): Promise<Settings> {
  const { settings } = await chrome.storage.local.get("settings");
  return { ...DEFAULT, ...(settings ?? {}), capture: { ...DEFAULT.capture, ...(settings?.capture ?? {}) } };
}

async function ensureResumed(): Promise<void> {
  if (vault.unlocked) return;
  const { dek } = await chrome.storage.session.get("dek");
  if (dek) {
    await vault.resume(unb64(dek));
    void warmModel();
  }
}

async function remember(): Promise<void> {
  const k = vault.exportSessionKey();
  if (k) await chrome.storage.session.set({ dek: b64(k) });
}

async function lockNow(): Promise<void> {
  vault.lock();
  modelStatus = "unknown";
  await chrome.storage.session.remove(["dek", "lastActive"]);
}

// Auto-lock after inactivity. Activity = any request from the panel or a page. Alarms wake the worker.
chrome.alarms.create("autolock", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(async (a) => {
  if (a.name !== "autolock") return;
  const { autoLockMinutes } = await settings();
  const { lastActive, dek } = await chrome.storage.session.get(["lastActive", "dek"]);
  if (dek && autoLockMinutes > 0 && Date.now() - (lastActive ?? 0) > autoLockMinutes * 60_000) await lockNow();
});

async function handle(req: Request, sender: chrome.runtime.MessageSender): Promise<Response> {
  // Only the extension's own pages are trusted. Content scripts run inside web pages (their sender
  // URL is the page's), and may only capture and request context.
  if (!allowed(req.type, isTrusted(sender, chrome.runtime.id, chrome.runtime.getURL("")))) {
    return { ok: false, error: "not allowed from a web page" };
  }
  // Messages addressed to the offscreen document are not for us.
  if ((req as { target?: string }).target === "offscreen") return { ok: true };
  await ensureResumed();
  if (req.type !== "status") await chrome.storage.session.set({ lastActive: Date.now() });
  switch (req.type) {
    case "status":
      return { ok: true, status: { exists: await Vault.exists(), unlocked: vault.unlocked, settings: await settings(), search: modelStatus === "ready" ? "hybrid" : "keyword", model: modelStatus, modelError } };
    case "setup": {
      const recoveryKey = await vault.setup(req.passphrase);
      await remember();
      void warmModel();
      return { ok: true, recoveryKey };
    }
    case "unlock":
      await vault.unlock(req.passphrase);
      await remember();
      void warmModel();
      return { ok: true };
    case "recover":
      await vault.recover(req.recoveryKey, req.newPassphrase);
      await remember();
      void warmModel();
      return { ok: true };
    case "lock":
      await lockNow();
      return { ok: true };
    case "changePassphrase":
      await vault.changePassphrase(req.current, req.next);
      return { ok: true };
    case "capture": {
      if (!vault.unlocked) return { ok: false, error: "locked" };
      if (!(await settings()).capture[req.site]) return { ok: true, count: 0 };
      const created = await vault.ingestMessage(req.text, { site: req.site, kind: "user_message", url: req.url });
      if (created.length) chrome.runtime.sendMessage({ type: "changed" }).catch(() => {});
      return { ok: true, count: created.length };
    }
    case "context":
      if (!vault.unlocked) return { ok: false, error: "locked" };
      return { ok: true, context: await vault.context(req.query) };
    case "list":
      return { ok: true, memories: vault.list() };
    case "add":
      await vault.ingestMessage(req.text, { site: "manual", kind: "manual" });
      return { ok: true };
    case "approve":
      await vault.approve(req.id);
      return { ok: true };
    case "edit":
      await vault.edit(req.id, req.text);
      return { ok: true };
    case "category":
      await vault.setCategory(req.id, req.category);
      return { ok: true };
    case "forget":
      return { ok: true, receipt: await vault.forget(req.id) };
    case "forgetAll":
      return { ok: true, count: await vault.forgetAll() };
    case "export":
      return { ok: true, json: vault.exportJson() };
    case "settings": {
      const cur = await settings();
      if (req.set) {
        const next = { ...cur, ...req.set, capture: { ...cur.capture, ...(req.set.capture ?? {}) } };
        await chrome.storage.local.set({ settings: next });
        return { ok: true, settings: next };
      }
      return { ok: true, settings: cur };
    }
  }
}

chrome.runtime.onMessage.addListener((req: Request, sender, reply) => {
  if ((req as { target?: string }).target === "offscreen") return false;
  handle(req, sender)
    .then(reply)
    .catch((e: Error) => reply({ ok: false, error: e.message }));
  return true;
});
