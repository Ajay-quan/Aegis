# AegisMem Privacy Policy

_Last updated: 2026-10-28 · Applies to AegisMem 1.x for Chrome_

AegisMem keeps a private, searchable copy of your conversations with AI assistants (ChatGPT, Claude,
Gemini, Perplexity) on your own device.

## What we collect

**Nothing.** AegisMem has no servers, no accounts, no analytics and no telemetry. We never receive
your conversations, search queries, settings or any usage data. The extension's own pages are
technically blocked (by their Content Security Policy) from connecting to the internet.

## What the extension stores, on your device only

| Data | When | How it's stored |
|---|---|---|
| Your conversations (your messages and the AI's replies, titles, dates) | When you import an export file, or automatically after each reply on sites where saving is on (you choose these at setup and in Settings) | Encrypted with AES-256-GCM in your browser's IndexedDB |
| An encryption key | At setup | *Device mode (default):* a non-extractable key stored in this browser profile. *Passphrase mode:* the key is wrapped by your passphrase (PBKDF2-SHA256, 600,000 iterations) and a recovery key; neither is ever stored. |
| A search index | While AegisMem is open | Built in memory from your encrypted data; never written to disk unencrypted |
| Settings | When you change them | Which sites save chats, auto-lock time |

Before saving, AegisMem masks API keys, payment card numbers, US Social Security numbers and
"password: …" text in your chats.

The on-device search model (all-MiniLM-L6-v2) is bundled with the extension. It never downloads
anything and never sends text anywhere.

## When text leaves your device

Only when **you** click **Continue in…** or **Ask…**. AegisMem then opens the AI you picked and places
the prepared text in its message box. **Nothing is sent until you press Enter there**, and it is then
handled under that AI provider's privacy policy.

Your history is never displayed inside AI websites, so those sites' scripts can't read it.

## Your control

- **View and delete.** View, search and delete any conversation, or delete everything.
- **Back up and restore.** Download an encrypted backup (protected by a password you choose) and
  restore it, on this or another device.
- **Export.** Export everything as Markdown.
- **Turn off saving.** Turn automatic saving off per site at any time.
- **Uninstall.** Uninstalling removes all of AegisMem's local data.

If you use passphrase mode and lose both your passphrase and your recovery key, your library can't be
recovered by anyone, including us.

## Permissions and why

| Permission | Why |
|---|---|
| Access to chatgpt.com, chat.openai.com, claude.ai, gemini.google.com, www.perplexity.ai | Read conversations on those sites (only where saving is on) and place handoff text in the message box when you ask |
| storage, unlimitedStorage | Keep your encrypted library and settings on your device |
| offscreen | Run the on-device search model and hold the search index |
| alarms | Auto-lock in passphrase mode |

## Contact

Open an issue at https://github.com/Ajay-quan/AegisMem
