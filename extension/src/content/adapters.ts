/**
 * Per-site DOM adapters. Sites change their markup without notice: when capture or insertion stops
 * working on a site, these selectors are the only thing that should need updating.
 */
export interface Adapter {
  site: string;
  userMessage: string; // elements containing a message the user sent
  input: string; // the prompt editor
}

export const ADAPTERS: Adapter[] = [
  { site: "chatgpt.com", userMessage: '[data-message-author-role="user"]', input: "#prompt-textarea" },
  { site: "claude.ai", userMessage: '[data-testid="user-message"]', input: 'div.ProseMirror[contenteditable="true"]' },
];

export function adapterFor(host: string): Adapter | undefined {
  return ADAPTERS.find((a) => host === a.site || host.endsWith(`.${a.site}`));
}
