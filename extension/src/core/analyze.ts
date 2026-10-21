/**
 * Text analysis that runs on-device before anything is stored: PII redaction, injection screening,
 * categorization and "is this worth remembering". Ported from the Python product
 * (domain/privacy/redaction.py, domain/integrity/provenance.py).
 *
 * Categorization and memorability are keyword heuristics in this version. They are deliberately
 * simple and will be replaced by on-device models (Chrome built-in AI / WebLLM), with accuracy measured
 * on real data before any quality claim is made.
 */

const EMAIL = /\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b/g;
const SSN = /\b\d{3}-\d{2}-\d{4}\b/g;
const SECRET = /\b(?:sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,})\b/g;
const PHONE = /(?<!\d)(?:\+?\d{1,3}[\s.\-]?)?(?:\(?\d{3}\)?[\s.\-]?)\d{3}[\s.\-]?\d{4}(?!\d)/g;
const CARD = /\b(?:\d[ -]?){13,16}\b/g;
const PASSWORD = /\b(password|passcode|pin)\s*(is|:|=)\s*\S+/gi;

function luhn(digits: string): boolean {
  let sum = 0;
  let dbl = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let d = digits.charCodeAt(i) - 48;
    if (dbl) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
    dbl = !dbl;
  }
  return sum % 10 === 0;
}

export interface Redaction {
  text: string;
  kinds: string[];
}

export function redact(input: string): Redaction {
  const kinds = new Set<string>();
  let text = input.replace(SECRET, () => (kinds.add("secret"), "[SECRET]"));
  text = text.replace(PASSWORD, (_m, w) => (kinds.add("password"), `${w} [REDACTED]`));
  text = text.replace(CARD, (m) => {
    const d = m.replace(/\D/g, "");
    if (d.length >= 13 && d.length <= 16 && luhn(d)) {
      kinds.add("card");
      return "[CARD]";
    }
    return m;
  });
  text = text.replace(SSN, () => (kinds.add("ssn"), "[SSN]"));
  text = text.replace(EMAIL, () => (kinds.add("email"), "[EMAIL]"));
  text = text.replace(PHONE, () => (kinds.add("phone"), "[PHONE]"));
  return { text, kinds: [...kinds] };
}

const INJECTION = new RegExp(
  [
    String.raw`\bignore (all |any )?(previous|prior|above) (instructions|rules|messages)\b`,
    String.raw`\bdisregard (the |all )?(previous|prior|system)\b`,
    String.raw`\byou (must|should) (now )?(always|never)\b`,
    String.raw`\b(from now on|going forward),? (you|the assistant|the agent)\b`,
    String.raw`\b(system prompt|developer message|jailbreak)\b`,
    String.raw`\b(send|forward|email|post|upload) .{0,40}\b(password|api key|token|credentials|secret)s?\b`,
    String.raw`\bwhen (asked|the user asks) .{0,60}\b(reply|respond|say|answer)\b`,
    String.raw`<\s*/?\s*(system|instructions?)\s*>`,
    String.raw`\bremember (that )?(the user|i) (wants?|prefers?) to (share|send|give)\b`,
  ].join("|"),
  "i",
);

/** Returns matched phrases; non-empty means the text is held for the user's review, never auto-stored. */
export function screen(text: string): string[] {
  const g = new RegExp(INJECTION.source, "gi");
  return [...text.matchAll(g)].map((m) => m[0]);
}

export const CATEGORIES = [
  "identity", "preferences", "health", "work", "people", "places", "plans", "finance", "learning", "other",
] as const;
export type Category = (typeof CATEGORIES)[number];

const CATEGORY_CUES: Record<Exclude<Category, "other">, RegExp> = {
  identity: /\b(my name is|i am a|i'm a|i am \d+|years old|i was born|my pronouns)\b/i,
  preferences: /\b(i (really )?(like|love|prefer|enjoy|hate|dislike|can't stand)|my favou?rite|i'm (a )?(vegetarian|vegan)|i don't eat)\b/i,
  health: /\b(allerg|diagnos|medication|doctor|therapy|diabet|asthma|injur|pregnan|blood pressure|my (health|diet)\b)/i,
  work: /\b(my (job|boss|manager|team|company|startup|project|client)|i work|at work|deadline|promotion|interview)\b/i,
  people: /\b(my (wife|husband|partner|son|daughter|kids?|mom|mother|dad|father|sister|brother|friend|colleague))\b/i,
  places: /\b(i live|i moved|moving to|my (home|apartment|house|city)|i'm (from|based in))\b/i,
  plans: /\b(i('m| am) (planning|going) to|next (week|month|year)|my (trip|wedding|goal)|i want to|i will)\b/i,
  finance: /\b(my (budget|salary|rent|mortgage|loan|savings|investments?)|i (earn|spend|pay|saved))\b/i,
  learning: /\b(i('m| am) (learning|studying)|my (course|class|exam|degree|thesis))\b/i,
};

/**
 * Single-valued facts about the user: a new statement for the same slot replaces the old value
 * (e.g. "I live in Austin" -> "I moved to Denver"). Detected by cue phrases, not word overlap.
 */
const SLOTS: Record<string, RegExp> = {
  residence: /\b(i live|i('m| am) living|i moved|i('m| am) moving|i relocated|i('m| am) based in|my (home|apartment|house) is)\b/i,
  employer: /\b(i work (at|for)|i('m| am) working (at|for)|i joined|i got a job|my (job|employer|company) is|i quit)\b/i,
  diet: /\b(i('m| am) (now )?(a )?(vegetarian|vegan|pescatarian|on a .{0,20}diet)|i (don't|no longer) eat|i eat meat)\b/i,
  relationship: /\b(i('m| am) (single|married|engaged|divorced|dating)|my (girlfriend|boyfriend|fianc[eé]e?|wife|husband) and i)\b/i,
};

export function slotOf(text: string): string | undefined {
  for (const [slot, re] of Object.entries(SLOTS)) if (re.test(text)) return slot;
  return undefined;
}

export function categorize(text: string): Category {
  for (const [cat, re] of Object.entries(CATEGORY_CUES)) if (re.test(text)) return cat as Category;
  return "other";
}

/** First-person statements about the user are worth remembering; questions and boilerplate are not. */
export function isMemorable(text: string): boolean {
  const t = text.trim();
  if (t.length < 12 || t.length > 2000) return false;
  if (!/\b(i|i'm|i've|i'd|i'll|my|me|we|our)\b/i.test(t)) return false;
  return categorize(t) !== "other" || /\b(i (have|had|got|use|own|need)|my )\b/i.test(t);
}

/** Split a message into sentence-sized candidate facts. */
export function sentences(text: string): string[] {
  return text
    .split(/(?<=[.!?])\s+|\n+/)
    .map((s) => s.trim())
    .filter(Boolean);
}
