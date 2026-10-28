/**
 * Builds the text a user carries into another AI: "Continue this conversation" and "Ask my history".
 * Extractive and deterministic (no model): the goal (first user message), the latest turns verbatim,
 * and older turns compressed to their opening sentences, all within a character budget.
 */
import { PLATFORMS, type Conversation, type Message } from "./types";

export const HANDOFF_BUDGET = 12000;

function firstSentences(text: string, n: number, max: number): string {
  const parts = text.replace(/\s+/g, " ").trim().split(/(?<=[.!?])\s+/);
  const s = parts.slice(0, n).join(" ");
  return s.length > max ? `${s.slice(0, max - 1)}…` : s + (parts.length > n ? " …" : "");
}

function clip(text: string, max: number): string {
  const t = text.trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

const who = (m: Message) => (m.role === "user" ? "Me" : "AI");

export function buildContinuation(c: Conversation, budget = HANDOFF_BUDGET): string {
  const date = c.updatedAt.slice(0, 10);
  const head = `I'm continuing a conversation I had with ${PLATFORMS[c.platform].label} (${date}), titled "${c.title}". Here is the context. Please read it, then continue helping me from where we left off.\n`;
  const tail = "\n--- End of context. My next message follows. ---\n\n";
  const msgs = c.messages;
  const firstUser = msgs.findIndex((m) => m.role === "user");
  const recentN = Math.min(4, msgs.length);
  const recentStart = msgs.length - recentN;
  const parts: string[] = [];
  if (firstUser >= 0 && firstUser < recentStart) parts.push(`## Original request\n${clip(msgs[firstUser].text, 1500)}`);
  const recent = msgs.slice(recentStart).map((m) => `${who(m)}: ${clip(m.text, 2500)}`);
  let used = head.length + tail.length + parts.join("\n").length + recent.join("\n\n").length + 60;
  const middle: string[] = [];
  for (let i = recentStart - 1; i >= 0; i--) {
    if (i === firstUser) continue;
    const line = `${who(msgs[i])}: ${firstSentences(msgs[i].text, 2, 300)}`;
    if (used + line.length + 1 > budget) {
      middle.unshift(`(${i + 1} earlier message${i ? "s" : ""} omitted)`);
      break;
    }
    middle.unshift(line);
    used += line.length + 1;
  }
  if (middle.length) parts.push(`## Earlier (summarised)\n${middle.join("\n")}`);
  parts.push(`## Most recent messages\n${recent.join("\n\n")}`);
  return clip(head + "\n" + parts.join("\n\n") + tail, budget);
}

export interface Excerpt {
  platform: Conversation["platform"];
  title: string;
  date: string;
  text: string;
}

export function buildAsk(question: string, excerpts: Excerpt[], budget = HANDOFF_BUDGET): string {
  const head = "Here are excerpts from my past AI conversations. Using them (and saying which excerpt you rely on), answer my question. If they don't contain the answer, say so.\n";
  const q = `\n## My question\n${question.trim()}\n`;
  const out: string[] = [];
  let used = head.length + q.length;
  excerpts.forEach((e, i) => {
    const block = `[${i + 1}] ${PLATFORMS[e.platform].label} · ${e.date} · "${e.title}"\n${clip(e.text, 1800)}`;
    if (used + block.length + 2 > budget) return;
    out.push(block);
    used += block.length + 2;
  });
  return `${head}\n## Excerpts\n${out.join("\n\n")}\n${q}`;
}

export function toMarkdown(c: Conversation): string {
  const lines = [`# ${c.title}`, "", `_${PLATFORMS[c.platform].label} · ${c.createdAt.slice(0, 10)} → ${c.updatedAt.slice(0, 10)} · ${PLATFORMS[c.platform].url(c.nativeId)}_`, ""];
  for (const m of c.messages) lines.push(`**${m.role === "user" ? "You" : PLATFORMS[c.platform].label}:**`, "", m.text, "");
  return lines.join("\n");
}
