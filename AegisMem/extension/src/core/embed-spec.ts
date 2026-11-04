/** Embedding model specs (no runtime deps, safe to import anywhere). */
export interface ModelSpec {
  name: string; // folder under modelRoot
  pooling: "mean" | "cls";
  queryPrefix: string; // prepended to search queries only
}

export const MINILM: ModelSpec = { name: "all-MiniLM-L6-v2", pooling: "mean", queryPrefix: "" };
export const ARCTIC_XS: ModelSpec = { name: "snowflake-arctic-embed-xs", pooling: "cls", queryPrefix: "Represent this sentence for searching relevant passages: " };
/** Shipped model. Chosen on the LongMemEval dev split (see README): same size as MiniLM, better retrieval. */
export const DEFAULT_SPEC = ARCTIC_XS;
export const MODEL = DEFAULT_SPEC.name;
