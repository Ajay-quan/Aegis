# Observability: metrics, traces, logs

## Run it locally
`./aegis up --observability` adds Prometheus (127.0.0.1:9090), Tempo (traces) and Grafana
(http://localhost:3002, dashboard **Aegis → AegisTrace overview**).

## Traces (OpenTelemetry)
One trace per run: `POST /v1/runs` (API) → outbox → queue → `run.execute` (worker) → for each step
`model.complete`, `tool <name>` → `policy.evaluate` → `tool.execute` (→ `mcp.call_tool` /
`aegismem /retrieve` …) → `evidence.checkpoint`. W3C trace context travels in the outbox message, and
outbound calls to AegisMem carry `traceparent`.

Spans carry identifiers and outcomes only (`aegis.run_id`, `aegis.tenant_id`, `aegis.tool`,
`aegis.decision`, `aegis.reason`, `aegis.risk_class`, `aegis.state`, `gen_ai.system`,
`gen_ai.request.model`). **Never content:** no inputs, arguments, outputs, prompts or completions. A test
asserts this. HTTP span names use the route template, never raw paths.

Configure with the standard variables: `OTEL_EXPORTER_OTLP_ENDPOINT` (OTLP/HTTP), `OTEL_SERVICE_NAME`
(default `aegistrace-api|worker|dispatcher`). `AEGIS_TRACING=console` prints spans; unset means off
(no-op, zero export).

## Metrics (Prometheus)
API `/metrics` (with `AEGIS_API_METRICS=1`), worker `:9101`, dispatcher `:9102`. Alert rules:
`infra/observability/alerts.yml`. The dashboard answers: how runs end, what the policy decides and
why, whether tools work, policy-check and gateway latency (p95), backlog, recoveries, anchoring failures.

## Logs
JSON lines with `trace_id` and `span_id`, so a log line links to its trace. Secrets are redacted.
