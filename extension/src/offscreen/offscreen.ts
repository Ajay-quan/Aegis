/**
 * Library host. Lives in the offscreen document because the MV3 service worker is killed when idle,
 * which would force decrypting and re-indexing the whole history on every wake. Holds the decrypted
 * index in memory and runs the on-device embedding model.
 * Only accepts requests forwarded by this extension's service worker.
 */
import { b64, unb64 } from "../core/crypto";
import { Library } from "../core/library";
import { db } from "../core/db";
import type { LibRequest, LibState, Response } from "../protocol";

const lib = new Library();
let model: LibState["model"] = "loading";
let modelError = "";

// The model runs in a dedicated worker (see embed-worker.ts). Cross-origin isolation (manifest)
// enables SharedArrayBuffer, hence multi-threaded WASM: about 4x faster indexing measured in Chrome.
const threads = self.crossOriginIsolated ? Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 1)) : 1;
const worker = new Worker(chrome.runtime.getURL("embed-worker.js"), { type: "module" });
let seq = 0;
const pending = new Map<number, { resolve: (v: number[][]) => void; reject: (e: Error) => void }>();
worker.onmessage = (ev) => {
  const p = pending.get(ev.data.id);
  if (!p) return;
  pending.delete(ev.data.id);
  if (ev.data.ok) p.resolve(ev.data.vectors);
  else p.reject(new Error(ev.data.error));
};
function ask(msg: Record<string, unknown>): Promise<number[][]> {
  const id = ++seq;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    worker.postMessage({ ...msg, id });
  });
}
const embedderReady = ask({ type: "init", threads, modelRoot: chrome.runtime.getURL("models/"), wasmRoot: chrome.runtime.getURL("ort/") })
  .then(() => {
    lib.embedder = (texts) => ask({ type: "embed", texts, priority: "low" });
    lib.queryEmbedder = (texts) => ask({ type: "embed", texts, priority: "high" });
    model = "ready";
    void backgroundEmbed();
  })
  .catch((e: Error) => {
    model = "unavailable";
    modelError = e.message;
    console.error("AegisMem: embedding model unavailable:", e);
  });

const initDone = lib.init().catch((e) => console.error("AegisMem: init failed", e));

// Background indexing: conversations are keyword-searchable as soon as they're saved; meaning vectors
// are added here, a few conversations at a time, so searches and captures are never blocked for long.
let embedding = false;
async function backgroundEmbed(): Promise<void> {
  if (embedding) return;
  embedding = true;
  try {
    await embedderReady;
    while (lib.unlocked && lib.embedder && lib.pendingEmbeddings() > 0) {
      const n = await lib.embedMissing(undefined, 8);
      if (!n) break; // model failing: stop, retry on the next trigger
      await new Promise((r) => setTimeout(r, 0));
    }
  } catch (e) {
    console.error("AegisMem: background indexing stopped", e);
  } finally {
    embedding = false;
  }
}

async function state(): Promise<LibState> {
  await initDone;
  if (lib.unlocked && lib.pendingEmbeddings() > 0) void backgroundEmbed(); // e.g. device-mode library opened at start
  return {
    exists: lib.mode !== null,
    mode: lib.mode,
    unlocked: lib.unlocked,
    search: model === "ready" ? "hybrid" : "keyword",
    model,
    modelError: modelError || undefined,
    stats: lib.unlocked ? lib.stats() : undefined,
    indexing: lib.unlocked && lib.embedder ? lib.pendingEmbeddings() : 0,
  };
}

async function handle(req: LibRequest): Promise<Response> {
  await initDone;
  switch (req.type) {
    case "state":
      return { ok: true, state: await state() };
    case "setupDevice":
      await lib.setupDevice();
      void backgroundEmbed();
      return { ok: true, state: await state() };
    case "setupPassphrase": {
      const recoveryKey = await lib.setupPassphrase(req.passphrase);
      return { ok: true, recoveryKey, sessionKey: b64(lib.sessionKey()!) };
    }
    case "unlock":
      await lib.unlock(req.passphrase);
      void backgroundEmbed();
      return { ok: true, sessionKey: b64(lib.sessionKey()!) };
    case "recover":
      await lib.recover(req.recoveryKey, req.newPassphrase);
      return { ok: true, sessionKey: b64(lib.sessionKey()!) };
    case "resume":
      if (!lib.unlocked) await lib.resume(unb64(req.raw));
      void backgroundEmbed();
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
    case "upsert": {
      const report = await lib.upsert(req.conversations, undefined, { embed: false });
      void backgroundEmbed();
      return { ok: true, report };
    }
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
