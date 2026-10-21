export type Embedder = (texts: string[]) => Promise<number[][]>;

/** Dot product of L2-normalized vectors = cosine similarity. */
export function cosine(a: number[], b: number[]): number {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * b[i];
  return s;
}
