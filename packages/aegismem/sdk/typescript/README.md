# @aegismem/client

Official TypeScript client for AegisMem, the trust layer for agent memory (Node 18+).

```ts
import { AegisMem } from "@aegismem/client";

const mem = new AegisMem({ baseUrl: "https://aegismem.internal", apiKey: process.env.AEGISMEM_API_KEY });
const w = await mem.ingest({ text: pageText, userId: "u1", sourceType: "tool_output", origin: "domain:example.com" });
if (w.status === "pending") { /* quarantined for review */ }
const r = await mem.retrieve({ query: "refund policy", userId: "u1" });
await mem.feedback({ retrievalId: r.retrieval_id, userId: "u1", used: [r.results[0]!.memory_id] });
```

Typed errors, retries with backoff, and automatic idempotency keys on writes.
