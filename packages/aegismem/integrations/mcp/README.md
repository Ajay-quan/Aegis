# aegismem-mcp

Mount AegisMem governed memory in any MCP client (Claude Desktop, Claude Code, IDE agents).

```json
{"mcpServers": {"aegismem": {
  "command": "aegismem-mcp",
  "env": {"AEGISMEM_BASE_URL": "https://aegismem.internal", "AEGISMEM_API_KEY": "aem_...",
          "AEGISMEM_USER_ID": "user-123"}}}}
```

| Tool | What it does |
|---|---|
| `remember` | Store a memory; `source="tool"` content is screened and may be held for review |
| `recall` | Verified retrieval (superseded, expired, quarantined and erased memories never returned) |
| `handoff` | Token-budgeted briefing with open questions and recent changes |
| `correct` | `outdated` / `wrong` / `malicious`; feeds continual learning |
| `used` | Report which recalled memories were used (improves ranking) |
| `forget` | Cascading erasure with a signed receipt |

Use an API key scoped to `memory:read memory:write`, and add `privacy` only if the agent may erase.
Tool failures are returned as MCP tool errors (`isError: true`) so the model can recover.
