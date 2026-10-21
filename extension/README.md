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

## What it does (v0.2)

- **Capture.** On sites where you turn it on (ChatGPT, Claude; Gemini and Perplexity in beta), statements
  you make about yourself are saved. Questions, requests to the AI, small talk and reactions to the AI's
  reply ("I like these ideas") are not. AI replies and page text are never captured. There are two
  independent capture paths: rendered messages, and the draft at the moment you press Enter.
- **Redaction.** Card numbers (Luhn-checked), passwords, API keys, SSNs, emails and phone numbers are
  removed before anything is stored.
- **Screening.** Text that looks like instructions aimed at an AI is held in **Review** and never used
  unless you approve it.
- **Smart search, on-device.** all-MiniLM-L6-v2 (int8 ONNX, bundled, about 23 MB) runs in an offscreen
  document, combined with BM25 at 0.7 lexical weight (the configuration validated in the main repo).
  If the model can't load, search falls back to keyword-only, and the panel says so.
- **Categories.** Keyword rules, plus a meaning-based fallback (nearest category examples). You can
  re-categorize any memory.
- **Updates.** A newer value for where you live, where you work, your diet or your relationship status
  is linked to the older one. Both are shown with dates, oldest first.
- **＋ Memories button.** Adds relevant memories above your draft. You see them before sending.
  Inserted memories are never re-captured.
- **Control.** Search, view, edit, re-categorize, delete (verified removal), export, delete all, lock,
  auto-lock (default 30 minutes), change passphrase, recover with the recovery key.

## Measured quality (honest)

`npm run eval` runs the extension's real pipeline on **LongMemEval-S** (MIT, real long-term chats),
**dev split** (238 questions). Every user turn is captured exactly as on a site, then the question is
searched. Results are in `eval/longmemeval-dev.json`.

Held-out **test split** (232 questions, run once after all tuning on dev). "hit@5" means a memory from
the gold evidence is in the top 5. Figures are 95% bootstrap CIs.

| System (same captured memories) | hit@5 |
|---|---|
| **Shipped: hybrid (on-device model + BM25, weight 0.7)** | **78.4%** [72.0, 83.6] |
| Keyword only (BM25) | 71.6% [65.1, 76.3] |
| Meaning only (on-device model) | 80.2% [74.1, 86.2] |
| BM25 over raw user turns (no capture filter) | 70.3% [63.4, 75.0] |

- **Hybrid vs keyword-only: +6.9 pts [+3.4, +9.9].** The on-device model measurably helps.
- **Meaning-only scored 1.8 pts above hybrid on test.** The difference is not significant, and the 0.7
  weight was fixed on dev, so it is not re-tuned on test. On dev (238 q) hybrid was 80.7%,
  meaning-only 80.3%, keyword 77.3%.
- **Evidence captured:** 86.1% of gold evidence turns. The misses are almost all questions whose answer
  is only in the **AI's** reply ("single-session-assistant", 3%), which the extension never stores by
  design. Excluding that type, hit@5 is about 90%.
- **By type (hybrid, test):**

| Question type | hit@5 |
|---|---|
| Knowledge update | 100% |
| Single-session user | 100% |
| Multi-session | 90% |
| Temporal reasoning | 88% |
| Preference | 53% |

- About 270 memories are kept per user from about 250 user turns.

**Category audit (author, manual, 60 random memories from real chats):** about 68% of memories get a
category other than "other". About 63% of those categories look right. Categories are a convenience
for browsing, not used for search, and can be corrected in one click.

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

- **Capture noise.** Some captured sentences are conversational rather than facts about you. Delete
  them in the panel.
- **Categories.** About 63% precision in the author audit above.
- **Update linking.** Only covers residence, employer, diet and relationship status. Other changes are
  handled by showing dates, oldest first.
- **Site markup.** Adapters depend on each site's page markup. ChatGPT and Claude selectors were checked
  by tests against stand-in pages, not against the live sites. Gemini and Perplexity are best-effort
  (beta). Enter-time capture keeps working if only the message selector breaks.
- **Screening.** Rule-based. It is not a guarantee against every injection.
- **Memories leave the device when you send them.** When you click ＋ Memories, they go to that AI
  provider with your message.
- **Size.** The extension is about 50 MB unpacked, mostly the bundled model and ONNX runtime, so it
  works with no network access.

## Tests

```bash
npm test        # unit: encryption, redaction, screening, updates, erasure
npm run e2e     # real Chromium + built extension + side panel UI + stand-in chatgpt.com / claude.ai pages
npm run eval    # extension pipeline on LongMemEval-S dev split (needs the dataset in ~/.cache/aegis-bench)
npm run package # dist/ zipped for the Chrome Web Store
```
