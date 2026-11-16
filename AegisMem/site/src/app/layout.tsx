import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Aegis | Trust for AI agents",
  description:
    "Aegis checks what AI agents do, governs what they remember, and keeps a signed record anyone can verify. AegisTrace + AegisMem.",
  openGraph: {
    title: "Aegis | Agents you can trust",
    description:
      "Default-deny permissions, human approvals, a signed audit log, and governed agent memory.",
    siteName: "Aegis",
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
