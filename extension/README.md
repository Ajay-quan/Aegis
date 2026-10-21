# AegisMem for Chrome

Private memory that follows you across ChatGPT and Claude. Everything is encrypted on your device
with your passphrase. No server is involved, and nobody else (including AegisMem) can read it.

## Try it (developer mode)

```bash
cd extension
npm install
npm run build          # -> dist/
```

Chrome → `chrome://extensions` → enable **Developer mode** → **Load unpacked** → choose `extension/dist`.
Click the AegisMem icon to open the side panel, create your vault, save the recovery key, and turn on
capture for a site in **Settings**.

## What it does (v0.1)

- **Capture.** On sites where you turn it on, first-person facts from messages *you* send are saved.
  For example, "I'm vegetarian" is saved and "Can you explain recursion?" is not. AI replies and page
  text are not captured.
- **Redaction.** Card numbers (Luhn-checked), passwords, API keys, SSNs, emails and phone numbers are
  removed before anything is stored.
- **Screening.** Text that looks like instructions aimed at an AI ("ignore previous instructions…")
  is held in **Review** and never used unless you approve it.
- **Updates.** A newer value for where you live, where you work, your diet or your relationship status
  is linked to the older one. Both are shown with dates, oldest first.
- **＋ Memories button.** On ChatGPT or Claude it adds relevant memories above your draft. You see them
  before you send. They then go to that AI provider as part of your message.
- **Control.** View, edit, recategorize, delete (verified removal from storage), export, delete all, lock.

## Security model

| Layer | Detail |
|---|---|
| Data key | Random AES-256-GCM key; each memory is encrypted separately |
| Passphrase | PBKDF2-SHA256, 600,000 iterations, wraps the data key; never stored |
| Recovery key | 256-bit, shown once, also wraps the data key |
| At rest | IndexedDB holds only ciphertext, salts and wrapped keys |
| While unlocked | Data key held in `chrome.storage.session` (memory only, never written to disk, hidden from web pages) |
| Web pages | Can only submit captured text and request context for one draft; cannot list, export or delete memories |

## Known limitations (honest)

- Categories, "memorable" detection and update slots are keyword heuristics. On-device models
  (Chrome built-in AI / small WebGPU models) come next, with accuracy measured before any claim.
- Search is BM25 (keyword). On-device embeddings and the hybrid fusion validated in the main repo come next.
- Site adapters depend on ChatGPT's and Claude's page markup and can break when those sites change.
- Screening is rule-based at this stage. It is not a guarantee against every injection.

## Tests

```bash
npm test        # unit: encryption, redaction, screening, updates, erasure
npm run e2e     # real Chromium + built extension + side panel UI + stand-in chatgpt.com page
```
