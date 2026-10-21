/**
 * Meaning-based categorization: each category is described by a few example statements; a memory
 * the keyword rules leave as "other" takes the category whose examples it is most similar to, if the
 * similarity clears MIN_SIMILARITY. Embeddings come from the same on-device model as search.
 */
import type { Category } from "./analyze";
import { cosine, type Embedder } from "./vector";

export const MIN_SIMILARITY = 0.25;

const EXAMPLES: Record<Exclude<Category, "other">, string[]> = {
  identity: ["I am 34 years old.", "My name is Alex and I grew up in Ohio.", "I'm an introvert and a night owl."],
  preferences: ["I love Italian food.", "My favorite band is Radiohead.", "I prefer aisle seats.", "I enjoy hiking on weekends.", "I watched a great movie last night."],
  health: ["I'm allergic to peanuts.", "I take medication for my blood pressure.", "I've been going to physical therapy for my knee.", "I'm trying to sleep better."],
  work: ["I work as a software engineer.", "My manager asked me to lead the project.", "I have a presentation for a client tomorrow.", "I got promoted last month."],
  people: ["My sister lives in Lisbon.", "My son plays soccer.", "My best friend is getting married.", "I visited my grandparents."],
  places: ["I live in Denver.", "I moved to a new apartment.", "I grew up near the coast.", "I visited the local museum downtown."],
  plans: ["I'm planning a trip to Japan next spring.", "I want to run a marathon this year.", "I'm going to start a podcast.", "We're renovating the kitchen next month."],
  finance: ["My rent is 2,000 dollars.", "I'm saving for a house.", "I spent too much on shopping.", "I invest in index funds."],
  learning: ["I'm learning Spanish.", "I'm taking an online course in data science.", "I'm studying for my exam.", "I read a book about history."],
};

let protos: Promise<{ cat: Category; vec: number[] }[]> | null = null;

export function prototypes(embed: Embedder): Promise<{ cat: Category; vec: number[] }[]> {
  protos ??= (async () => {
    const entries = Object.entries(EXAMPLES).flatMap(([cat, xs]) => xs.map((x) => ({ cat: cat as Category, x })));
    const vecs = await embed(entries.map((e) => e.x));
    return entries.map((e, i) => ({ cat: e.cat, vec: vecs[i] }));
  })().catch((e) => {
    protos = null;
    throw e;
  });
  return protos;
}

export async function categorizeByMeaning(vec: number[], embed: Embedder): Promise<Category> {
  let best: Category = "other";
  let bestSim = MIN_SIMILARITY;
  for (const p of await prototypes(embed)) {
    const s = cosine(vec, p.vec);
    if (s > bestSim) {
      bestSim = s;
      best = p.cat;
    }
  }
  return best;
}
