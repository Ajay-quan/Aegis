/** BM25 (Robertson & Zaragoza) over decrypted memories, held only in memory while unlocked. */

const STOP = new Set(
  "a an and are as at be but by do does for from had has have how i i'm in is it its me my of on or our so that the their them they this to was we what when where which who why will with you your".split(" "),
);

export function tokens(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/)
    .filter((t) => t.length > 1 && !STOP.has(t));
}

export class BM25 {
  private docs: { id: string; tf: Map<string, number>; len: number }[] = [];
  private df = new Map<string, number>();
  private avg = 0;

  constructor(items: { id: string; text: string }[], private k1 = 1.5, private b = 0.75) {
    for (const { id, text } of items) {
      const tf = new Map<string, number>();
      const ts = tokens(text);
      for (const t of ts) tf.set(t, (tf.get(t) ?? 0) + 1);
      for (const t of tf.keys()) this.df.set(t, (this.df.get(t) ?? 0) + 1);
      this.docs.push({ id, tf, len: ts.length });
    }
    this.avg = this.docs.reduce((s, d) => s + d.len, 0) / Math.max(this.docs.length, 1);
  }

  search(query: string, topK = 10): { id: string; score: number }[] {
    const q = [...new Set(tokens(query))];
    const n = this.docs.length;
    const out: { id: string; score: number }[] = [];
    for (const d of this.docs) {
      let s = 0;
      for (const t of q) {
        const f = d.tf.get(t);
        if (!f) continue;
        const df = this.df.get(t)!;
        const idf = Math.log(1 + (n - df + 0.5) / (df + 0.5));
        s += (idf * f * (this.k1 + 1)) / (f + this.k1 * (1 - this.b + (this.b * d.len) / (this.avg || 1)));
      }
      if (s > 0) out.push({ id: d.id, score: s });
    }
    return out.sort((a, b) => b.score - a.score).slice(0, topK);
  }
}

export function jaccard(a: string, b: string): number {
  const A = new Set(tokens(a));
  const B = new Set(tokens(b));
  if (!A.size || !B.size) return 0;
  let i = 0;
  for (const t of A) if (B.has(t)) i++;
  return i / (A.size + B.size - i);
}
