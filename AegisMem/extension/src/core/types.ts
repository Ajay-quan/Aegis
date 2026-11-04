export type Platform = "chatgpt" | "claude" | "gemini" | "perplexity";
export type Role = "user" | "assistant";

export const PLATFORMS: Record<Platform, { label: string; url: (nativeId: string) => string; home: string }> = {
  chatgpt: { label: "ChatGPT", url: (id) => `https://chatgpt.com/c/${id}`, home: "https://chatgpt.com/" },
  claude: { label: "Claude", url: (id) => `https://claude.ai/chat/${id}`, home: "https://claude.ai/new" },
  gemini: { label: "Gemini", url: (id) => `https://gemini.google.com/app/${id}`, home: "https://gemini.google.com/app" },
  perplexity: { label: "Perplexity", url: (id) => `https://www.perplexity.ai/search/${id}`, home: "https://www.perplexity.ai/" },
};

export interface Message {
  role: Role;
  text: string;
  at?: string; // ISO time, when known
}

export interface Conversation {
  id: string; // `${platform}:${nativeId}`
  platform: Platform;
  nativeId: string;
  title: string;
  createdAt: string; // ISO
  updatedAt: string; // ISO
  messages: Message[];
  source: "import" | "capture";
}

export function convId(platform: Platform, nativeId: string): string {
  return `${platform}:${nativeId}`;
}
