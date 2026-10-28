# AegisMem Recall: roadmap

_Written 2026-10-28. Owner: product + engineering. Status lives in `project_log.md`._

## 1. The problem

People now keep hundreds of conversations across ChatGPT, Claude and Gemini. Three recurring pains:

1. **"Where was that answer?"** Native history search is weak (titles or keywords, one platform at
   a time), and nothing searches across platforms.
2. **"Continue somewhere else."** Users switch AIs mid-task (usage limits, a better model for code or
   writing) and lose all context.
3. **"Can I trust a tool with my chats?"** Store listings in this category report extensions that
   stole users' AI chats. Chats contain health, legal, financial and work secrets.

## 2. Market reality

Demand is validated, and so is competition. Extensions already capture and search AI chats:
LLMnesia, Echoes (about 10k users, 7 platforms), ChatEngram, llm-history-search, AI Memory, ChatTrack.
"Search your AI chats" alone is not a moat. We win only on things a user can verify:

| Differentiator | Why it matters | How we prove it |
|---|---|---|
| **D1 Best search quality** | Users search by meaning ("that thing about my lease"), not exact words | Published, reproducible benchmark on real conversations (LongMemEval), dev/test split. Competitors publish none. |
| **D2 Full history on day one** | An empty index is a dead product; live capture takes weeks to become useful | Import official exports (ChatGPT, Claude, Gemini Takeout), plus live capture |
| **D3 Portability** | Big providers will never build "continue in a competitor" | One click: compact handoff, opened in the target AI |
| **D4 Verifiable privacy** | Trust is the buying criterion in this category | No servers. Extension pages are forbidden by CSP from any network connection. Encrypted at rest. Open source. History is never rendered into third-party pages. |
| **D5 Speed** | Search must feel instant | Benchmark: p95 query latency at 50k chunks |

## 3. World-class approach, per component

| Component | Approach | Rationale / prior art |
|---|---|---|
| Retrieval | Hybrid: BM25 plus dense (all-MiniLM-L6-v2, int8, on-device), min-max convex fusion | Hybrid beats either alone on our measurements (Sessions 11, 13). Standard in modern IR (BEIR results). |
| Unit of indexing | Message-level chunks (≤ ~1,000 chars, overlapping windows for long messages); results grouped by conversation | Known-item search returns *conversations*; chunks give precise snippets |
| Ranking to conversations | Conversation score = best chunk score, plus a small bonus for multiple matching chunks | Standard max-passage aggregation (MaxP, Dai & Callan 2019) |
| Vectors | 384-d, int8 scalar-quantized, brute-force dot product | 50k × 384 int8 is about 19 MB and brute force is under 50 ms; no ANN error |
| Lexical index | Incremental inverted index (term → postings), updated on insert | Rebuilding BM25 per query is O(N) and too slow at scale |
| Import | Tolerant parsers; ChatGPT tree resolved via `current_node` path; split files; zip via fflate | Formats are undocumented and vary between export versions |
| Live capture | Both user and assistant messages; conversation ID from the URL; debounce until streaming ends | History search needs the answers, not just the questions |
| Encryption | Default: device-bound non-extractable AES-GCM key stored in IndexedDB (zero friction). Optional: passphrase mode (PBKDF2-600k-wrapped key, recovery key) | Removes the biggest setup friction from v0.2 and keeps data encrypted at rest |
| Security boundary | Search UI only on extension pages (popup, full-page app, side panel), never as an overlay inside ChatGPT/Claude pages | An in-page overlay would expose Claude history to chatgpt.com scripts |
| Handoff | Extractive: goal (first user message), latest turns verbatim, middle turns compressed, within a character budget | No LLM required, deterministic, testable |
| Ask my history | Top results packed into a prompt and opened in the user's chosen AI | The user's own AI does the reasoning; we stay small and private |

## 4. Scope decisions

- **Dropped:** the v0.2 "facts about me" memory and ＋ Memories insertion. Built-in AI memory already
  covers this; the old code stays in git history.
- **Kept and reused:** crypto vault, BM25, on-device embedder, redaction (optional secret masking), site
  adapters, test and eval infrastructure.

## 5. Phases and acceptance criteria

| Phase | Deliverable | Done when |
|---|---|---|
| P0 | New data model (Conversation, Message, Chunk), store v2, device-key encryption plus optional passphrase | Unit tests: ciphertext-only at rest, both key modes, migration-free fresh install |
| P1 | Importers: ChatGPT (`conversations*.json`, zip), Claude (`conversations.json`, zip), Gemini Takeout (both variants) | Fixture tests per format, including branches, split files, odd parts, truncated responses |
| P2 | Index and search: incremental BM25, int8 dense, hybrid fusion, conversation aggregation, filters (platform, date, role), highlighted snippets | Unit tests; p95 < 150 ms at 50k chunks (bench) |
| P3 | Live capture of both roles on ChatGPT and Claude (Gemini and Perplexity beta), titles, upserts | E2E on stand-in pages: streaming update captured once, final text stored |
| P4 | UI: popup quick search (Ctrl/Cmd+Shift+K), full-page app (search, filters, conversation viewer, open original, copy), side panel | E2E: import, then search, then open viewer |
| P5 | Continue in another AI; Ask my history | E2E: handoff text inserted into target stand-in page |
| P6 | Settings: sites, encryption mode, backup (encrypted file) and restore, Markdown export, delete conversation or all, storage stats | E2E: backup, wipe, restore round-trip |
| P7 | Evaluation: known-item conversation search on LongMemEval sessions (tune on dev, test once) plus a scale benchmark | Numbers in README; hybrid vs keyword vs meaning with CIs |
| P8 | Store package, privacy policy, listing, landing page (local file, not published without approval) | `npm run package` zip; docs updated |

## 6. Honest risks

- The export formats are reverse-engineered. The first real user export may reveal variants, so the
  parsers are tolerant and report what they skipped.
- DOM capture can break when sites change. Import does not depend on the page DOM.
- Competitors can copy features, but not a published benchmark and an auditable privacy model
  overnight.
- Demand for *our* version is unproven until real users try it. The 2-week validation plan (waitlist,
  then 50–100 users, then ≥ 30% weekly retention) still applies before investing beyond this build.
