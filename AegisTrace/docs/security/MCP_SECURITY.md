# MCP security model (`aegistrace.mcpgw.bridge`)

Built on the official MCP Python SDK 2.3.0 (protocol revision 2026-07-28). Local servers (stdio) and remote servers (Streamable HTTP).

| Rule | Implementation | Test |
|---|---|---|
| Servers are untrusted | Names, descriptions, annotations, schemas and results are data; descriptions are prefixed `[untrusted MCP description]` | `test_only_mapped_tools_registered_and_annotations_ignored` |
| Explicit mapping | Only tools listed in `McpServerConfig.tools` are registered, with a platform-assigned risk class. Server `readOnlyHint` is ignored. | same |
| Schema pinning | The SHA-256 digest of the input schema is pinned at approval time. A change disables the tool. | `test_schema_rug_pull_disables_tool` |
| Strict arguments | Undeclared top-level arguments are rejected unless the pinned schema explicitly sets `additionalProperties` | `test_malicious_mcp_end_to_end` (`grant: class4` injection) |
| No token passthrough | The server process gets only PATH/LANG/LC_ALL/TZ plus per-server credentials from the platform. Caller and AegisTrace credentials are never forwarded. | env_probe assertion in `test_malicious_mcp_end_to_end` |
| Connection isolation | A fresh server process per call, with a timeout | — |
| Same enforcement path | MCP tools are ordinary registry entries: grants, OPA, approvals and the evidence chain all apply | `test_malicious_mcp_end_to_end` |

## Remote servers (Streamable HTTP)

| Rule | Implementation | Test (`tests/end_to_end/test_remote_mcp.py`) |
|---|---|---|
| Admin-configured destination | The URL comes from `AEGIS_MCP_SERVERS_FILE`, never from the model | `test_servers_file_wires_remote_tools_and_keeps_secrets_out_of_the_file` |
| HTTPS only | Plain HTTP only to loopback with `allow_insecure_http` (development) | `test_destination_rules` |
| Destination checks before every connection | Link-local/metadata, multicast, reserved and unspecified addresses always refused; private and loopback only with `allow_private_network`; any one bad DNS answer refuses; no credentials in URLs | `test_destination_rules` |
| No off-origin redirects | The SDK follows redirects only within the endpoint's origin, for MCP and OAuth requests alike | (SDK guarantee) |
| OAuth 2.1 client credentials | Protected-resource metadata discovery (RFC 9728), then authorization-server metadata (RFC 8414) | `test_discovers_and_runs_remote_tools_through_policy_and_evidence` |
| Audience-bound tokens | Every token request carries `resource=<server URL>` (RFC 8707); the server only accepts tokens issued for itself | same, and `test_server_refuses_tokens_issued_for_another_server` |
| Issuer pinning | Credentials are only ever sent to the configured issuer; a server pointing elsewhere fails before any token request | `test_only_the_configured_issuer_is_trusted` |
| Secrets out of config | The file names environment variables (`client_secret_env`); a missing secret fails loudly | `test_servers_file_wires_remote_tools_and_keeps_secrets_out_of_the_file` |
| Tokens stay in memory | Per-server, per-process cache until expiry; never persisted, logged or forwarded to tools or models | `test_tokens_are_cached_per_server_until_expiry` |
| Failure isolation | A server that is down, or whose schemas changed, is reported and skipped; startup continues and no unmapped tool appears | `test_unreachable_server_is_reported_not_fatal` |

Pin schemas with `aegistrace mcp discover <server> --config mcp.yaml` (prints each tool's digest and
whether it is pinned, unmapped or changed).

**Known limits:**
- DNS rebinding between the check and the connection remains possible; production needs network-level
  egress control (same as `tools/egress.py`).
- Only the client-credentials grant (machine-to-machine). Acting on behalf of an end user (authorization
  code, token exchange) is not implemented.
- The official MCP conformance suite has not been run.
