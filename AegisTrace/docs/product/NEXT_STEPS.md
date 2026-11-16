# Next steps

1. Owner decisions: license; target deployment (AWS account structure, a separate anchor account); IdP choice.
2. Push to GitHub and get CI green there. Pin actions to reviewed SHAs.
3. Managed signing backend (OPEN_ISSUES #2), plus signed trust-store distribution.
4. Independent security review; fix findings.
5. Payload envelope encryption with per-tenant data keys, plus retention and crypto-shredding (§32–33).
6. OpenTelemetry tracing, Grafana dashboards, alert rules.
7. Remote MCP with OAuth 2.1.
8. Multi-worker load tests at 100/500 VUs on dedicated hardware.
