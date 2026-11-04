# aegis-bench results

Recorded 2026-10-10 on commit series `q1/production-core`. Reproduce with the commands shown.

## Recall impact: LoCoMo (real embeddings)

**Current (v0.4.0, hybrid dense + BM25 with RRF → guard → ranking):** recall@5 **0.565** vs 0.514 raw dense
(+5.1 pts), recall@10 **0.665** vs 0.617 (+4.8), hit@5 0.632 vs 0.583; 0 / 5,882 benign turns quarantined.

| Hybrid variant (full dataset) | recall@5 | recall@10 |
|---|---|---|
| dense only (v0.3 Q1 line) | 0.521 | 0.620 |
| BM25 pool 200, blend 0.3 (pre-merge main defaults) | 0.418 | 0.606 |
| pool 2,000, blend 0.5 | 0.531 | 0.639 |
| pool 2,000, blend 0.3 | 0.549 | 0.649 |
| **pool 2,000, blend 0.15 (default)** | **0.565** | **0.665** |

Earlier (dense only):

`AEGIS_BENCH_EMBED_URL=http://localhost:11434/v1 AEGIS_BENCH_EMBED_MODEL=nomic-embed-text AEGIS_BENCH_EMBED_DIM=768 python -m bench.locomo`

10 conversations, 5,882 turns ingested through the full pipeline, 1,536 questions with gold evidence (categories 1–4).

| | AegisMem (screening + guard + ranking) | Raw vector search, same index | Delta |
|---|---|---|---|
| recall@5 | 0.521 | 0.514 | +0.6 pts |
| recall@10 | 0.620 | 0.617 | +0.3 pts |
| hit@5 | 0.591 | 0.583 | +0.8 pts |
| Benign turns quarantined | 0 / 5,882 | n/a | n/a |

History: the first run measured recall@5 **0.262 vs 0.540** (−27.9 pts). Ablation traced it to (1) a popularity
feedback loop (every retrieval raised `access_count`, boosting that memory for all future queries) and (2) query-
independent signals carrying 50% of the score. Fix: utility (Beta-smoothed *used* rate) replaces access count;
relevance-dominant default weights (0.85 / 0.05 / 0.05 / 0.05).

## Out-of-distribution injection: deepset/prompt-injections (EN + DE)

`python -m bench.run --suites external_injection`. Train 546 / test 116, all treated as tool output.

| Condition | Held-out recall | Held-out FPR |
|---|---|---|
| Cold start | 0.12 | 0.00 |
| After reviewer learning, 100% of misses reported | 0.88 | 0.07 |
| After reviewer learning, 50% of misses reported | 0.83 | 0.09 |
| After reviewer learning, 20% of misses reported | 0.60 | 0.00 |

Implicit benign signals (memories the agent actually used) reduced post-learning FPR from 0.20 to 0.07–0.09
by countering the selection bias of only labelling held items.

## Internal gates

`python -m bench.run`: poisoning, learning (8 splits), revocation (0 leaks), erasure (0 residue), latency, and
external injection. All gates pass; thresholds are in `thresholds.json`.

## Integrity audit across systems (aegis-audit 0.1.0)

| System | Score | Failed checks |
|---|---|---|
| AegisMem: Docker Compose (staging config, RLS, Ollama nomic-embed-text) | **7/7** | none |
| AegisMem: Helm on kind, 2 replicas | **7/7** | none |
| Mem0 OSS 2.2.1, `infer=True` (default; local llama3.2 extractor, Qdrant, nomic-embed-text) | 5/7 | DEL-2 duplicate copy survived deletion; POI-2 covert behavioural instruction persisted |
| Mem0 OSS 2.2.1, `infer=False` | 4/7 | DEL-2; POI-1 injected instruction from tool output served (critical); POI-2 |
| Naive vector store (reference) | 1/7 | all but ISO-1 |

Caveats: single run per configuration; Mem0's extraction quality depends on the LLM (a stronger hosted
model may change POI results); checks are judged on returned text. **Do not publish vendor results
before notifying the vendor (responsible disclosure) and re-running on their recommended configuration.**

Reproduce Mem0: `pip install mem0ai`, then `aegis-audit --target mem0-lib --mem0-config mem0.json`
where `mem0.json` holds a Mem0 config (`vector_store`, `embedder`, `llm`) plus optional `"infer": true`.
