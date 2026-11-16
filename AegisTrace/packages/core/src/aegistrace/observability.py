# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Prometheus metrics shared by API and workers. Labels never carry tenant
identifiers or payload content (cardinality and confidentiality)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

TOOL_DECISIONS = Counter("aegis_tool_decisions_total", "Policy decisions at the tool gateway", ["decision", "reason"])
TOOL_EXECUTIONS = Counter("aegis_tool_executions_total", "Tool executions by outcome", ["tool", "outcome"])
POLICY_LATENCY = Histogram(
    "aegis_policy_eval_seconds",
    "OPA evaluation latency",
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5),
)
GATEWAY_OVERHEAD = Histogram("aegis_gateway_overhead_seconds", "Gateway time excluding tool execution")
RUNS_FINISHED = Counter("aegis_runs_finished_total", "Runs reaching a resting state", ["state"])
OUTBOX_DISPATCHED = Counter("aegis_outbox_dispatched_total", "Outbox messages published")
OUTBOX_FAILURES = Counter("aegis_outbox_publish_failures_total", "Outbox publish failures")
OUTBOX_LAG = Gauge("aegis_outbox_lag_seconds", "Age of the oldest pending outbox message")
QUEUE_DEPTH = Gauge("aegis_queue_pending_messages", "Unacknowledged messages in the run stream")
RECOVERIES = Counter("aegis_recoveries_total", "Lease recoveries by resulting state", ["state"])
ANCHOR_FAILURES = Counter("aegis_anchor_failures_total", "Checkpoints that could not be published to the anchor")
