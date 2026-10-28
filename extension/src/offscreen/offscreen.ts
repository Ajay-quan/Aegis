/**
 * Library host. Lives in the offscreen document because the MV3 service worker is killed when idle,
 * which would force decrypting and re-indexing the whole history on every wake. Holds the decrypted
 * index in memory and runs the on-device embedding model.
 * Only accepts requests forwarded by this extension's service worker.
 */
import { b64, unb64 } from "../core/crypto";
import { createEmbedder } from "../core/embed";
import { Library } from "../core/library";
import { db } from "../core/db";
import type { LibRequest, LibState, Response } from "../protocol";

const lib = new Library();
let model: LibState["model"] = "loading";
let modelError = "";

const embedderReady = createEmbedder({ modelRoot: chrome.runtime.getURL("models/"), wasmRoot: chrome.runtime.getURL("ort/") })
  .then(async (e) => {
    await e(["warm up"]);
    lib.embedder = e;
    model = "ready";
    if (lib.unlocked) void lib.embedMissing();
  })
  .catch((e: Error) => {
    model = "unavailable";
    modelError = e.message;
    console.error("AegisMem: embedding model unavailable:", e);
  });

const initDone = lib.init().catch((e) => console.error("AegisMem: init failed", e));

async function state(): Promise<LibState> {
  await initDone;
  return {
    exists: lib.mode !== null,
    mode: lib.mode,
    unlocked: lib.unlocked,
    search: model === "ready" ? "hybrid" : "keyword",
    model,
    modelError: modelError || undefined,
    stats: lib.unlocked ? lib.stats() : undefined,
  };
}

async function handle(req: LibRequest): Promise<Response> {
  await initDone;
  switch (req.type) {
    case "state":
      return { ok: true, state: await state() };
    case "setupDevice":
      await lib.setupDevice();
      return { ok: true, state: await state() };
    case "setupPassphrase": {
      const recoveryKey = await lib.setupPassphrase(req.passphrase);
      return { ok: true, recoveryKey, sessionKey: b64(lib.sessionKey()!) };
    }
    case "unlock":
      await lib.unlock(req.passphrase);
      void embedderReady.then(() => lib.embedMissing());
      return { ok: true, sessionKey: b64(lib.sessionKey()!) };
    case "recover":
      await lib.recover(req.recoveryKey, req.newPassphrase);
      return { ok: true, sessionKey: b64(lib.sessionKey()!) };
    case "resume":
      if (!lib.unlocked) await lib.resume(unb64(req.raw));
      return { ok: true };
    case "lock":
      lib.lock();
      return { ok: true };
    case "changePassphrase":
      await lib.changePassphrase(req.current, req.next);
      return { ok: true };
    case "switchMode": {
      const recoveryKey = await lib.switchMode(req.to, req.passphrase);
      const sk = lib.sessionKey();
      return { ok: true, recoveryKey, sessionKey: sk ? b64(sk) : undefined, state: await state() };
    }
    case "search":
      return { ok: true, results: await lib.search(req.query, req.opts) };
    case "get":
      return { ok: true, conversation: lib.get(req.id) };
    case "recent":
      return { ok: true, conversations: lib.recent(req.limit, req.platform) };
    case "upsert":
      await embedderReady.catch(() => {});
      return { ok: true, report: await lib.upsert(req.conversations) };
    case "embedMissing":
      return { ok: true, count: await lib.embedMissing() };
    case "delete":
      return { ok: true, removed: await lib.remove(req.id) };
    case "deleteAll":
      return { ok: true, count: await lib.removeAll() };
    case "exportAll":
      return { ok: true, conversations: lib.allConversations() };
    case "wipeEverything":
      await db.wipe();
      setTimeout(() => location.reload(), 50); // fresh, empty library (after replying)
      return { ok: true };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg?.target !== "lib") return false;
  // Only our service worker may talk to the library host.
  if (sender.id !== chrome.runtime.id || !sender.url?.endsWith("/background.js")) return false;
  handle(msg.req as LibRequest)
    .then(reply)
    .catch((e: Error) => reply({ ok: false, error: e.message }));
  return true;
});
