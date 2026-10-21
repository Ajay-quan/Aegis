/**
 * Service worker: the only place the vault is unlocked. Content scripts never see the key or the
 * full memory list; they only send captured text and receive a context block for one prompt.
 * The unlocked data key is kept in chrome.storage.session (memory only, never written to disk,
 * not readable by content scripts) so a restarted worker does not force a re-unlock.
 */
import { Vault } from "./core/vault";
import { b64, unb64 } from "./core/crypto";
import type { Request, Response, Settings } from "./messages";

const vault = new Vault();
const DEFAULT: Settings = { capture: { "chatgpt.com": false, "claude.ai": false } };
const PANEL_ONLY = new Set(["setup", "unlock", "recover", "lock", "list", "add", "approve", "edit", "category", "forget", "forgetAll", "export", "settings"]);

chrome.storage.session.setAccessLevel?.({ accessLevel: "TRUSTED_CONTEXTS" });
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

async function settings(): Promise<Settings> {
  const { settings } = await chrome.storage.local.get("settings");
  return { ...DEFAULT, ...(settings ?? {}), capture: { ...DEFAULT.capture, ...(settings?.capture ?? {}) } };
}

async function ensureResumed(): Promise<void> {
  if (vault.unlocked) return;
  const { dek } = await chrome.storage.session.get("dek");
  if (dek) await vault.resume(unb64(dek));
}

async function remember(): Promise<void> {
  const k = vault.exportSessionKey();
  if (k) await chrome.storage.session.set({ dek: b64(k) });
}

async function handle(req: Request, sender: chrome.runtime.MessageSender): Promise<Response> {
  // Only the extension's own pages are trusted. Content scripts run inside web pages (their sender
  // URL is the page's), and may only capture and request context.
  const fromPage = !(sender.id === chrome.runtime.id && sender.url?.startsWith(chrome.runtime.getURL("")));
  if (fromPage && PANEL_ONLY.has(req.type)) return { ok: false, error: "not allowed from a web page" };
  await ensureResumed();
  switch (req.type) {
    case "status":
      return { ok: true, status: { exists: await Vault.exists(), unlocked: vault.unlocked, settings: await settings() } };
    case "setup": {
      const recoveryKey = await vault.setup(req.passphrase);
      await remember();
      return { ok: true, recoveryKey };
    }
    case "unlock":
      await vault.unlock(req.passphrase);
      await remember();
      return { ok: true };
    case "recover":
      await vault.recover(req.recoveryKey, req.newPassphrase);
      await remember();
      return { ok: true };
    case "lock":
      vault.lock();
      await chrome.storage.session.remove("dek");
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
      return { ok: true, context: vault.context(req.query) };
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
  handle(req, sender)
    .then(reply)
    .catch((e: Error) => reply({ ok: false, error: e.message }));
  return true;
});
