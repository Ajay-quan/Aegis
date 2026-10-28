/** Accepts what users actually download: a .zip archive or individual .json files from any platform. */
import { unzipSync, strFromU8 } from "fflate";
import { looksLikeChatGPT, parseChatGPT } from "./chatgpt";
import { looksLikeClaude, parseClaude } from "./claude";
import type { ImportResult } from "./common";
import { looksLikeGemini, parseGemini } from "./gemini";

export interface InputFile {
  name: string;
  bytes: Uint8Array;
}

export interface Detected extends ImportResult {
  sources: string[]; // e.g. "ChatGPT: conversations.json"
}

const WANTED = /(^|\/)(conversations(-\d+)?\.json|MyActivity\.json)$/i;

function parseJsonFile(name: string, text: string, out: Detected): void {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    out.warnings.push(`${name}: not valid JSON, skipped`);
    return;
  }
  const r = looksLikeChatGPT(data) ? (out.sources.push(`ChatGPT: ${name}`), parseChatGPT(data))
    : looksLikeClaude(data) ? (out.sources.push(`Claude: ${name}`), parseClaude(data))
    : looksLikeGemini(data) ? (out.sources.push(`Gemini: ${name}`), parseGemini(data))
    : null;
  if (!r) {
    out.warnings.push(`${name}: not a recognised ChatGPT, Claude or Gemini export, skipped`);
    return;
  }
  out.conversations.push(...r.conversations);
  out.skipped += r.skipped;
  out.warnings.push(...r.warnings);
}

export function detectAndParse(files: InputFile[]): Detected {
  const out: Detected = { conversations: [], skipped: 0, warnings: [], sources: [] };
  for (const f of files) {
    if (/\.zip$/i.test(f.name) || (f.bytes[0] === 0x50 && f.bytes[1] === 0x4b)) {
      let entries: Record<string, Uint8Array>;
      try {
        entries = unzipSync(f.bytes, { filter: (e) => WANTED.test(e.name) });
      } catch (e) {
        out.warnings.push(`${f.name}: could not read zip (${(e as Error).message})`);
        continue;
      }
      const names = Object.keys(entries).sort();
      if (!names.length) out.warnings.push(`${f.name}: no conversations.json or MyActivity.json inside`);
      for (const n of names) parseJsonFile(`${f.name}/${n}`, strFromU8(entries[n]), out);
    } else {
      parseJsonFile(f.name, strFromU8(f.bytes), out);
    }
  }
  // The same conversation can appear in several split files or repeated imports: keep the newest.
  const byId = new Map(out.conversations.map((c) => [c.id, c]));
  for (const c of out.conversations) if (c.updatedAt > byId.get(c.id)!.updatedAt) byId.set(c.id, c);
  out.conversations = [...byId.values()];
  return out;
}
