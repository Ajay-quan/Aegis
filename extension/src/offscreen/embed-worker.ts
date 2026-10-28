/**
 * Embedding worker: runs the model off the library's thread so saving, capturing and searching are
 * never blocked by indexing. Queries ("high") always go before bulk indexing ("low"), and bulk work is
 * processed in small slices so a query waits at most one slice.
 */
import { createEmbedder, type Embedder } from "../core/embed";

type Job = { id: number; texts: string[]; priority: "high" | "low"; out: number[][] };
const SLICE = 16;
const high: Job[] = [];
const low: Job[] = [];
let busy = false;
let embedder: Promise<Embedder> | null = null;

function init(threads: number, modelRoot: string, wasmRoot: string): Promise<Embedder> {
  embedder ??= createEmbedder({ modelRoot, wasmRoot, threads });
  return embedder;
}

async function pump(): Promise<void> {
  if (busy) return;
  busy = true;
  try {
    const e = await embedder!;
    for (;;) {
      const job = high[0] ?? low[0];
      if (!job) break;
      const slice = job.texts.slice(job.out.length, job.out.length + SLICE);
      job.out.push(...(await e(slice)));
      if (job.out.length >= job.texts.length) {
        (job.priority === "high" ? high : low).shift();
        postMessage({ id: job.id, ok: true, vectors: job.out });
      }
    }
  } catch (err) {
    for (const j of [...high, ...low]) postMessage({ id: j.id, ok: false, error: (err as Error).message });
    high.length = low.length = 0;
    embedder = null;
  } finally {
    busy = false;
  }
}

self.onmessage = (ev: MessageEvent) => {
  const m = ev.data;
  if (m.type === "init") {
    init(m.threads, m.modelRoot, m.wasmRoot)
      .then((e) => e(["warm up"]))
      .then(() => postMessage({ id: m.id, ok: true }))
      .catch((err: Error) => {
        embedder = null;
        postMessage({ id: m.id, ok: false, error: err.message });
      });
    return;
  }
  (m.priority === "high" ? high : low).push({ id: m.id, texts: m.texts, priority: m.priority, out: [] });
  void pump();
};
