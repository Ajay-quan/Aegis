# aegismem-client

Official Python client for [AegisMem](https://github.com/Ajay-quan/AegisMem), the trust layer for agent memory.

```python
from aegismem_client import AegisMem

async with AegisMem("https://aegismem.internal", api_key="aem_...") as mem:
    w = await mem.ingest(page_text, user_id="u1", source_type="tool_output", origin="domain:example.com")
    if w.quarantined: ...                      # held for review, never served as trusted memory
    r = await mem.retrieve("refund policy", user_id="u1")
    await mem.feedback(r.retrieval_id, user_id="u1", used=[r.results[0].memory_id])
    receipt = await mem.forget("u1", memory_ids=[w.memory_id], reason="user request")
```

Writes carry automatic idempotency keys, so retries never duplicate data. `AegisMemSync` is a blocking wrapper.
The tool catalogue in `aegismem_client.tools` powers the MCP server and the framework integrations.
