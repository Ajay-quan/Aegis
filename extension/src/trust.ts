/** Requests a content script (running inside a web page) may make. Everything else is extension-only. */
export const PAGE_ALLOWED = new Set(["status", "capture", "context"]);

/** Trusted = sent by one of this extension's own pages (panel, offscreen), identified by URL origin. */
export function isTrusted(sender: { id?: string; url?: string }, extensionId: string, extensionOrigin: string): boolean {
  return sender.id === extensionId && !!sender.url && sender.url.startsWith(extensionOrigin);
}

export function allowed(type: string, trusted: boolean): boolean {
  return trusted || PAGE_ALLOWED.has(type);
}
