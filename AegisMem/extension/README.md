# AegisMem: search all your AI chats

One search box across every conversation you've had with ChatGPT, Claude, Gemini and Perplexity,
plus one click to continue any chat in another AI. Private: encrypted, on your device, no servers.

## Install (developer mode)

```bash
cd extension
npm install
npm run build        # → dist/
```

Chrome → `chrome://extensions` → **Developer mode** → **Load unpacked** → `extension/dist`.
A welcome tab opens. Choose the protection mode, then import your history.

**Quick search:** Ctrl/Cmd+Shift+K (toolbar popup). **Full app:** Ctrl/Cmd+Shift+Y.

## What it does

| | |
|---|---|
| **Search everything** | Keyword *and* meaning-based search across all platforms, with highlighted snippets. Filter by app, date, or whether a match is in your message or the AI's reply. Results jump to the matching message. |
| **Full history on day one** | Import the official exports: ChatGPT (`.zip` or `conversations*.json`), Claude (`.zip` or `conversations.json`), Gemini (Google Takeout → My Activity → Gemini Apps, JSON). Search works immediately; meaning-based indexing finishes in the background. |
| **Automatic saving** | After each reply on enabled sites, both sides of the conversation are saved. ChatGPT is verified; Claude, Gemini and Perplexity are beta. Saving waits until the reply has finished streaming, and a partial page never overwrites a fuller imported copy. |
| **Continue in another AI** | Builds a compact handoff: the original request, a summary of the middle, and the latest turns verbatim. It opens the AI you pick with the text in the message box. You review it and press Enter. The handoff is one-time, only for the tab AegisMem opened, and survives login walls. |
| **Ask an AI using your results** | Turns the top results into a cited question for any AI. |
| **Your data, portable** | Encrypted backup and restore (password-protected file), Markdown export, delete per conversation or everything. |

## Privacy and security model

| Layer | Detail |
|---|---|
| No servers | No accounts, analytics or telemetry. Extension pages are under a strict CSP (`connect-src 'self'`): they *cannot* reach the internet (checked in e2e). |
| At rest | Every conversation is encrypted with AES-256-GCM in IndexedDB. Default key: non-extractable, device-bound. Optional passphrase mode: PBKDF2-SHA256 600k plus a recovery key, with auto-lock. |
| In memory | The decrypted search index lives only in the extension's offscreen document. |
| AI websites | Content scripts can only *submit* captured chats and collect a handoff meant for their own tab. They can never read history (`src/trust.ts`, unit-tested). History is never rendered inside AI pages, so those sites' scripts can't see it. |
| Secrets | API keys, card numbers (Luhn-checked), SSNs and "password: …" are masked before saving. |
| Model | Snowflake arctic-embed-xs (Apache-2.0, 22M params, int8 ONNX, about 23 MB) is bundled and runs locally in a worker. Nothing is downloaded at runtime. |

## Measured quality

**"Find that chat" benchmark.** `npm run eval` uses LongMemEval-S (MIT, Wu et al., ICLR 2025). The
library is every distinct chat session in a split's histories: about 10,000 conversations and
100M+ characters, far heavier than a typical user. The queries are the benchmark's own questions; the
target is the conversation that holds the answer. The product's own chunking and index code are used.
Everything was tuned on the **dev** split; the **test** split (232 questions) was run **once**.
95% bootstrap CIs.

| Test split (232 q, 9,964 conversations) | Right chat ranked first | In top 5 | MRR |
|---|---|---|---|
| **Shipped: hybrid (keyword + on-device meaning, 0.7)** | **34.1%** [28.0, 39.2] | **56.0%** [49.1, 62.1] | **0.455** |
| Keyword only (BM25) | 32.3% [26.7, 38.4] | 56.5% [50.0, 62.1] | 0.442 |
| Meaning only (arctic-embed-xs) | 26.3% | 50.0% | 0.370 |

What this does and doesn't show:
- **Hybrid vs keyword-only: +1.7 pts ranked first, CI [−0.4, +3.9].** That's a tie on this benchmark,
  so we don't claim meaning-based search beats keyword search here. LongMemEval questions reuse the
  chat's own words, which favours keyword search.
- **Meaning-based search matters when you don't remember the words** (for example "is my bread culture
  ruined" → the sourdough chat, verified in e2e). We have no public benchmark for that case, so it is
  shown by example, not by numbers.
- **Model choice was measured on dev.** Snowflake arctic-embed-xs beat all-MiniLM-L6-v2 at the same
  size (meaning-only top-5: 50.4% vs 45.0%). Tuning experiments that did *not* beat the baseline (role
  weighting, chunk aggregation, BM25 parameters) were not adopted.
- **Latency** for the full search (keyword + meaning over about 137k passages, single thread, M1 Pro):
  **p50 100 ms, p95 145 ms**. Typical libraries are 10–100× smaller.
- **Indexing speed in Chrome:** meaning vectors are built in the background at about 20 passages/s
  with multi-threaded WASM, measured while sharing the CPU. Keyword search works immediately.

## Architecture

```
AI site tab ──content.js──► background.js (router + gatekeeper) ──► offscreen.html (library host)
  capture both sides           trust check, settings, handoff,          encrypted store (IndexedDB)
  one-time handoff insert      auto-lock, session key                   hybrid index (BM25 + int8 dense)
                                                                        on-device embedder (ONNX WASM)
app.html / popup.html ─────────────────────► background.js ──────────► offscreen
  search, viewer, import (parsed in-page), settings, backup
```

- `src/core/`: crypto, keys, db, `index.ts` (search), `library.ts`, `handoff.ts`, `backup.ts`, `redact.ts`.
- `src/importers/`: ChatGPT (tree to active branch), Claude, Gemini (3 Takeout variants), zip detection.
- `src/content/adapters.ts`: per-site selectors. When a site redesign breaks saving, this is the file to update.

## Tests

```bash
npm test          # unit: importers, library (both key modes), index, handoff, backup, trust rules
npm run e2e       # real Chromium + built extension: onboarding → import → search → viewer → handoff
                  # → live capture → popup → ciphertext at rest → backup/restore → passphrase → no network
npm run eval      # search-quality benchmark on LongMemEval (dataset in ~/.cache/aegis-bench)
npm run package   # store zip
```

## Known limitations (honest)

- **Export formats are reverse-engineered.** None of the three services documents its export format.
  The importers handle every variant we know of and report what they skip. A new variant may need an
  update.
- **Live saving depends on each site's page structure.** Selectors can break when a site changes.
  Imports are unaffected.
- **Gemini exports** from Google omit or truncate some responses. AegisMem reports how many.
- **Very large libraries** (10k+ conversations) take a while to build meaning vectors on first import;
  keyword search works immediately.
- **Handoffs are extractive, not AI-written summaries.** The middle of very long chats is compressed to
  opening sentences.
