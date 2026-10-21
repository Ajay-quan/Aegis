/**
 * Per-site DOM adapters. Sites change their markup without notice: when capture or insertion stops
 * working on a site, these selectors are the only thing that should need updating.
 *
 * Capture uses two independent paths so one broken selector doesn't silently stop it:
 *   1. rendered user messages (userMessage selector)
 *   2. the draft text at the moment the user presses Enter in the editor (input selector)
 * "verified" = checked against the live site's markup; beta adapters are best-effort.
 */
export interface Adapter {
  site: string;
  label: string;
  userMessage: string;
  input: string;
  verified: boolean;
}

export const ADAPTERS: Adapter[] = [
  { site: "chatgpt.com", label: "ChatGPT", userMessage: '[data-message-author-role="user"]', input: "#prompt-textarea", verified: true },
  { site: "claude.ai", label: "Claude", userMessage: '[data-testid="user-message"]', input: 'div.ProseMirror[contenteditable="true"]', verified: true },
  { site: "gemini.google.com", label: "Gemini (beta)", userMessage: "user-query .query-text", input: 'rich-textarea div[contenteditable="true"]', verified: false },
  { site: "www.perplexity.ai", label: "Perplexity (beta)", userMessage: '[class*="group/query"]', input: 'textarea, div[contenteditable="true"]#ask-input', verified: false },
];

export function adapterFor(host: string): Adapter | undefined {
  return ADAPTERS.find((a) => host === a.site || host.endsWith(`.${a.site}`));
}
