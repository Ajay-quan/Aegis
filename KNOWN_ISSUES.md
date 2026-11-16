# Known issues

| ID | Issue | Severity | Workaround | Status |
|---|---|---|---|---|
| K-01 | AegisMem runs with auth off in local compose (internal network only) | medium | not reachable from the host | open (S-05) |
| K-02 | Remote MCP: the SDK resolves DNS again after our check (rebinding window) | medium | network-level egress control | open |
| K-03 | Payload KEK and API-key pepper are files in dev; production needs KMS / secret manager | high for prod | — | open |
| K-04 | Parallel Playwright workers can hit the 600 req/min rate limit with one shared token | low (tests only) | run with one worker (default in ./aegis test) | open |
| K-05 | iCloud-synced checkout creates "name 2.*" duplicates | low | excluded from images; .venv in .venv.nosync | mitigated |
