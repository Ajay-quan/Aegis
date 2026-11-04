import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AegisMem | Persistent memory for AI agents",
  description:
    "AegisMem gives AI agents persistent memory. Write preferences, decisions, and project context once — retrieve the right context in any future session through one fast REST API.",
  openGraph: {
    title: "AegisMem | Agents forget. Yours won't.",
    description:
      "A persistent memory layer for AI agents: semantic retrieval, metadata filtering, and storage that survives the session boundary.",
    siteName: "AegisMem",
    type: "website"
  }
};

export default function RootLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
