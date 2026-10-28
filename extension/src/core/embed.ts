/**
 * On-device sentence embeddings, run fully locally via transformers.js / ONNX Runtime Web.
 * Shipped: Snowflake arctic-embed-xs (Apache-2.0, 22M params, 384-d, int8 ONNX, ~23 MB).
 * No text ever leaves the device.
 */
import { env, pipeline, type FeatureExtractionPipeline } from "@huggingface/transformers";

import type { Embedder } from "./vector";
export type { Embedder };
import { ARCTIC_XS, DEFAULT_SPEC, MINILM, MODEL, type ModelSpec } from "./embed-spec";
export { ARCTIC_XS, DEFAULT_SPEC, MINILM, MODEL, type ModelSpec };
export const DIM = 384;

export async function createEmbedder(opts: { modelRoot: string; wasmRoot?: string; device?: "wasm" | "cpu"; threads?: number; spec?: ModelSpec; query?: boolean }): Promise<Embedder> {
  const spec = opts.spec ?? DEFAULT_SPEC;
  env.allowRemoteModels = false; // bundled files only
  env.allowLocalModels = true;
  env.localModelPath = opts.modelRoot;
  const wasm = env.backends.onnx.wasm;
  if (wasm && opts.wasmRoot) {
    wasm.wasmPaths = opts.wasmRoot;
    // Multi-threaded WASM needs SharedArrayBuffer, i.e. a cross-origin-isolated page.
    wasm.numThreads = opts.threads ?? 1;
  }
  const extract: FeatureExtractionPipeline = await pipeline("feature-extraction", spec.name, { dtype: "q8", device: opts.device ?? "wasm" });
  return async (texts, isQuery) => {
    if (!texts.length) return [];
    const input = (isQuery ?? opts.query) && spec.queryPrefix ? texts.map((t) => spec.queryPrefix + t) : texts;
    const out = await extract(input, { pooling: spec.pooling, normalize: true });
    const data = out.data as Float32Array;
    return texts.map((_, i) => Array.from(data.subarray(i * DIM, (i + 1) * DIM), (x) => Math.round(x * 1e4) / 1e4));
  };
}
