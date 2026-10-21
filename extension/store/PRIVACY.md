# AegisMem Privacy Policy

_Last updated: 2026-10-21_

AegisMem is a browser extension that keeps a private memory of facts you share with AI assistants.

## What we collect

**Nothing.** AegisMem has no servers, no accounts, no analytics and no telemetry. We never receive
your conversations, your memories, your passphrase or any usage data.

## What the extension stores on your device

- **Memories.** Sentences from messages *you* send on AI sites where *you* turned capture on. Each one
  is encrypted with AES-256-GCM before it is stored in your browser's local storage (IndexedDB).
- **A wrapped key.** Your data key, encrypted with a key derived from your passphrase (PBKDF2-SHA256,
  600,000 iterations) and, separately, with your recovery key. Neither the passphrase nor the recovery
  key is ever stored.
- **Settings.** Which sites capture is on for, and the auto-lock time.

Before storing, the extension removes card numbers, passwords, API keys, SSNs, email addresses and
phone numbers. AI replies and other page content are not captured.

## When data leaves your device

Only when **you** click **＋ Memories** on an AI site. The memories shown are then inserted into your
message, and the AI provider receives them when you send it, under that provider's privacy policy.
You can review or remove them before sending.

The on-device search model is bundled with the extension. It never downloads code or sends text anywhere.

## Your control

In the side panel you can view, edit, re-categorize, delete any memory, delete everything, export
your data, change your passphrase, and lock the vault. Uninstalling the extension deletes all of its
local data.

If you lose both your passphrase and your recovery key, your memories cannot be recovered by anyone,
including us.

## Permissions and why

| Permission | Why |
|---|---|
| Access to chatgpt.com, claude.ai, gemini.google.com, www.perplexity.ai | Read the messages you send (only where capture is on) and insert memories when you click the button |
| storage, unlimitedStorage | Keep your encrypted memories and settings on your device |
| sidePanel | The memory panel |
| offscreen | Run the on-device search model |
| alarms | Auto-lock after inactivity |

## Contact

Questions: open an issue at https://github.com/Ajay-quan/AegisMem
