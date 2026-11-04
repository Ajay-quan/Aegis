# MCP security model (`aegistrace.mcpgw.bridge`)

Built on the official MCP Python SDK 2.3.0 (protocol revision 2026-07-28). Stdio transport only.

| Rule | Implementation | Test |
|---|---|---|
| Servers are untrusted | Names, descriptions, annotations, schemas and results are data; descriptions are prefixed `[untrusted MCP description]` | `test_only_mapped_tools_registered_and_annotations_ignored` |
| Explicit mapping | Only tools listed in `McpServerConfig.tools` are registered, with a platform-assigned risk class. Server `readOnlyHint` is ignored. | same |
| Schema pinning | The SHA-256 digest of the input schema is pinned at approval time. A change disables the tool. | `test_schema_rug_pull_disables_tool` |
| Strict arguments | Undeclared top-level arguments are rejected unless the pinned schema explicitly sets `additionalProperties` | `test_malicious_mcp_end_to_end` (`grant: class4` injection) |
| No token passthrough | The server process gets only PATH/LANG/LC_ALL/TZ plus per-server credentials from the platform. Caller and AegisTrace credentials are never forwarded. | env_probe assertion in `test_malicious_mcp_end_to_end` |
| Connection isolation | A fresh server process per call, with a timeout | — |
| Same enforcement path | MCP tools are ordinary registry entries: grants, OPA, approvals and the evidence chain all apply | `test_malicious_mcp_end_to_end` |

**Not implemented:**
- Remote (Streamable HTTP) MCP servers
- OAuth 2.1 authorization with resource indicators and audience-bound tokens
- Official conformance-suite runs

Until those exist, AegisTrace does not connect to remote MCP servers.
