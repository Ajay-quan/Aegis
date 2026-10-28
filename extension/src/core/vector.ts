/** isQuery: the text is a search query (some models need a query-only prefix). */
export type Embedder = (texts: string[], isQuery?: boolean) => Promise<number[][]>;

/** Dot product of L2-normalized vectors = cosine similarity. */
export function cosine(a: number[], b: number[]): number {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
}
