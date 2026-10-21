/** Offscreen document: hosts the embedding model (service workers can't run it reliably). */
import { createEmbedder, type Embedder } from "../core/embed";

let ready: Promise<Embedder> | null = null;
function embedder(): Promise<Embedder> {
  ready ??= createEmbedder({ modelRoot: chrome.runtime.getURL("models/"), wasmRoot: chrome.runtime.getURL("ort/") });
  return ready;
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg?.target !== "offscreen" || msg.type !== "embed") return;
  embedder()
    .then((e) => e(msg.texts))
    .then((vectors) => reply({ ok: true, vectors }))
    .catch((e: Error) => {
      ready = null;
      reply({ ok: false, error: e.message });
    });
  return true;
});
