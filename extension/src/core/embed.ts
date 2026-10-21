/**
 * On-device sentence embeddings: all-MiniLM-L6-v2 (Apache-2.0, 384-d, int8 ONNX, ~23 MB), the same
 * model used in the main repo's benchmarks. Runs fully locally via transformers.js / ONNX Runtime Web.
 * No text ever leaves the device.
 */
import { env, pipeline, type FeatureExtractionPipeline } from "@huggingface/transformers";

import type { Embedder } from "./vector";
export type { Embedder };
export const MODEL = "all-MiniLM-L6-v2";
export const DIM = 384;

export async function createEmbedder(opts: { modelRoot: string; wasmRoot?: string; device?: "wasm" | "cpu" }): Promise<Embedder> {
  env.allowRemoteModels = false; // bundled files only
  env.allowLocalModels = true;
  env.localModelPath = opts.modelRoot;
  const wasm = env.backends.onnx.wasm;
  if (wasm && opts.wasmRoot) {
    wasm.wasmPaths = opts.wasmRoot;
    wasm.numThreads = 1; // extension pages are not cross-origin isolated
  }
  const extract: FeatureExtractionPipeline = await pipeline("feature-extraction", MODEL, { dtype: "q8", device: opts.device ?? "wasm" });
  return async (texts) => {
    if (!texts.length) return [];
    const out = await extract(texts, { pooling: "mean", normalize: true });
    const data = out.data as Float32Array;
    return texts.map((_, i) => Array.from(data.subarray(i * DIM, (i + 1) * DIM), (x) => Math.round(x * 1e4) / 1e4));
  };
}
