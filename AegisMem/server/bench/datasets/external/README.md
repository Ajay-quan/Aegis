# External datasets

| File | Source | License | Notes |
|---|---|---|---|
| `deepset_prompt_injections_{train,test}.jsonl` | [deepset/prompt-injections](https://huggingface.co/datasets/deepset/prompt-injections) | Apache-2.0 | English and German. Converted to `{text, label, source}`; every row is treated as arriving via a tool/document (`tool_output`), the worst case for memory poisoning. |

These datasets target prompt injection in *user queries*, not memory poisoning specifically, so they are
an out-of-distribution robustness check rather than the primary gate. LoCoMo (recall impact) is downloaded at
run time and never committed (CC BY-NC 4.0).
