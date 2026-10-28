/**
 * Per-site DOM adapters. Sites change their markup without notice: when capture or insertion stops
 * working on a site, these selectors are the only thing that should need updating.
 * Exports (Import page) never depend on these, so a broken adapter never loses history.
 * "verified" = selectors checked against the live site; others are best-effort (beta).
 */
import type { Platform } from "../core/types";

export interface Adapter {
  platform: Platform;
  hosts: string[];
  idFromPath: RegExp; // capture group 1 = native conversation id
  user: string;
  assistant: string;
  input: string;
  streaming: string; // present while a reply is still being generated
  title: () => string;
  verified: boolean;
}

const cleanTitle = (suffix: RegExp) => () => document.title.replace(suffix, "").trim();

export const ADAPTERS: Adapter[] = [
  {
    platform: "chatgpt",
    hosts: ["chatgpt.com", "chat.openai.com"],
    idFromPath: /\/c\/([0-9a-f-]{8,})/i,
    user: '[data-message-author-role="user"]',
    assistant: '[data-message-author-role="assistant"]',
    input: "#prompt-textarea",
    streaming: '[data-testid="stop-button"], .result-streaming',
    title: cleanTitle(/\s*[-|]\s*ChatGPT$|^ChatGPT$/),
    verified: true,
  },
  {
    platform: "claude",
    hosts: ["claude.ai"],
    idFromPath: /\/chat\/([0-9a-f-]{8,})/i,
    user: '[data-testid="user-message"]',
    assistant: ".font-claude-response, .font-claude-message",
    input: 'div.ProseMirror[contenteditable="true"]',
    streaming: '[data-is-streaming="true"]',
    title: cleanTitle(/\s*[-|]\s*Claude$|^Claude$/),
    verified: false,
  },
  {
    platform: "gemini",
    hosts: ["gemini.google.com"],
    idFromPath: /\/app\/([A-Za-z0-9_-]{6,})/,
    user: "user-query .query-text",
    assistant: "model-response message-content",
    input: 'rich-textarea div[contenteditable="true"]',
    streaming: ".pending-response, model-response[is-processing]",
    title: cleanTitle(/\s*[-|]\s*Gemini$|^Gemini$|^Google Gemini$/),
    verified: false,
  },
  {
    platform: "perplexity",
    hosts: ["www.perplexity.ai", "perplexity.ai"],
    idFromPath: /\/search\/([A-Za-z0-9._-]{6,})/,
    user: 'h1[class*="query"], [class*="group/query"] h1, [data-testid="user-query"]',
    assistant: '[id^="markdown-content"], .prose',
    input: "textarea, div#ask-input[contenteditable]",
    streaming: '[data-testid="stop-generating-response-button"]',
    title: cleanTitle(/\s*[-|]\s*Perplexity$|^Perplexity$/),
    verified: false,
  },
];

export function adapterFor(host: string): Adapter | undefined {
  return ADAPTERS.find((a) => a.hosts.some((h) => host === h || host.endsWith(`.${h}`)));
}
